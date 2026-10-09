"""El Salvador DTE preparation. No signing, transmission or acceptance claims."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache, wraps
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from jsonschema import Draft7Validator, FormatChecker
from sqlalchemy import event, update
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import DocumentoFiscal, Orden, PreferenciaSistema, SecuenciaBorradorDTE
from .services import audit_event, user_can


billing_bp = Blueprint("billing", __name__, url_prefix="/facturacion")
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
IVA_RATE = Decimal("0.13")
PROFILE_KEY = "dte.emisor.v1"
REFERENCE = json.loads((Path(__file__).parent / "schemas/dte-reference.json").read_text())
PROFILE_FIELDS = [
    ("nit", "NIT sin guiones", 14), ("nrc", "NRC sin guiones", 8),
    ("nombre", "Razón social", 250), ("nombreComercial", "Nombre comercial (opcional)", 150),
    ("codActividad", "Código de actividad MH", 6), ("descActividad", "Actividad económica", 150),
    ("departamento", "Código de departamento", 2), ("municipio", "Código de municipio del esquema v1", 2),
    ("complemento", "Dirección del establecimiento", 200), ("telefono", "Teléfono", 30),
    ("correo", "Correo del emisor", 100), ("codEstable", "Código interno del establecimiento (4 caracteres)", 4),
    ("codPuntoVenta", "Código interno del punto de venta (4 caracteres)", 4),
    ("codEstableMH", "Código de establecimiento asignado por MH (opcional)", 4),
    ("codPuntoVentaMH", "Código de punto de venta asignado por MH (opcional)", 4),
]


class BillingError(ValueError):
    pass


def amount(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise BillingError("Monto inválido.")
        result = number.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise BillingError("Monto inválido.")
    return result


def decimal_json(value):
    """Encode Decimal as exact JSON numbers, never binary floats for tax math."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise BillingError("Monto inválido.")
        return format(value, "f")
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + decimal_json(item)
                              for key, item in value.items()) + "}"
    if isinstance(value, (tuple, list)):
        return "[" + ",".join(decimal_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@lru_cache(maxsize=8)
def _load_schema(path, modified_ns):
    content = Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest() != REFERENCE["sha256"]:
        raise BillingError("La referencia DTE no coincide con su checksum. Revisa la instalación.")
    schema = json.loads(content, parse_float=Decimal)
    # Check the metaschema using ordinary JSON numbers; validation uses Decimal.
    Draft7Validator.check_schema(json.loads(content))
    return schema


def load_schema():
    path = Path(current_app.config.get("DTE_SCHEMA_PATH") or
                Path(current_app.instance_path) / "dte-schemas/dte-fe-v1.json")
    if not path.is_file():
        raise BillingError("Falta instalar la referencia DTE. Sigue la guía de facturación del repositorio.")
    return _load_schema(str(path.resolve()), path.stat().st_mtime_ns)


def validate_schema(payload, schema=None):
    errors = sorted(Draft7Validator(schema or load_schema(), format_checker=FormatChecker()).iter_errors(payload),
                    key=lambda error: tuple(str(part) for part in error.absolute_path))
    if errors:
        messages = [f"{'.'.join(str(part) for part in error.absolute_path) or 'documento'}: {error.message[:240]}"
                    for error in errors[:5]]
        raise BillingError("Revisa los datos fiscales: " + "; ".join(messages))


def require_permission(permission):
    def decorate(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not user_can(current_user, permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def csrf_token():
    if "billing_csrf" not in session:
        session["billing_csrf"] = secrets.token_urlsafe(32)
    return session["billing_csrf"]


def check_csrf():
    submitted = request.form.get("billing_csrf", "")
    expected = session.get("billing_csrf", "")
    if not expected or not hmac.compare_digest(expected, submitted):
        abort(400, "La sesión del formulario venció. Recarga la página.")


def get_profile():
    stored = db.session.get(PreferenciaSistema, PROFILE_KEY)
    if not stored or not stored.valor:
        return {}
    try:
        return json.loads(stored.valor)
    except (ValueError, TypeError):
        return {}


def issuer_from_profile(profile):
    required = {field[0] for field in PROFILE_FIELDS} - {"nombreComercial", "codEstableMH", "codPuntoVentaMH"}
    if any(not str(profile.get(key, "")).strip() for key in required):
        raise BillingError("Completa todos los datos obligatorios del emisor en Perfil fiscal.")
    if profile.get("precios_iva_incluido") is not True:
        raise BillingError("Confirma que los precios de venta ya incluyen el IVA estándar del 13 %.")
    for key, label, maxlength in PROFILE_FIELDS:
        if len(str(profile.get(key, ""))) > maxlength:
            raise BillingError(f"{label}: máximo {maxlength} caracteres.")
    for key in ("codEstable", "codPuntoVenta"):
        if not re.fullmatch(r"[A-Z0-9]{4}", profile.get(key, "")):
            raise BillingError("Los códigos internos de establecimiento y punto de venta deben tener 4 letras mayúsculas o números.")
    issuer = {key: profile.get(key) or None for key in
              ("nit", "nrc", "nombre", "codActividad", "descActividad", "nombreComercial", "telefono", "correo",
               "codEstable", "codPuntoVenta", "codEstableMH", "codPuntoVentaMH")}
    issuer["tipoEstablecimiento"] = profile.get("tipoEstablecimiento", "")
    issuer["direccion"] = {key: profile.get(key, "") for key in ("departamento", "municipio", "complemento")}
    validate_address_codes(issuer["direccion"])
    validate_schema(issuer, load_schema()["properties"]["emisor"])
    return issuer


def validate_address_codes(address):
    if not re.fullmatch(r"(?:0[1-9]|1[0-4])", address.get("departamento", "")):
        raise BillingError("El departamento debe ser un código de dos dígitos entre 01 y 14.")
    if not re.fullmatch(r"[0-9]{2}", address.get("municipio", "")):
        raise BillingError("El municipio debe ser un código de dos dígitos de la referencia v1.")


def recipient_from_form(form, total):
    name = form.get("nombre", "").strip()
    if not name:
        raise BillingError("Escribe el nombre del cliente para el borrador.")
    doc_type = form.get("tipoDocumento", "").strip() or None
    doc_number = form.get("numDocumento", "").strip() or None
    if doc_type not in (None, "13", "36", "02", "03", "37"):
        raise BillingError("Tipo de documento del cliente inválido.")
    if bool(doc_type) != bool(doc_number):
        raise BillingError("Completa el tipo y número de documento del cliente, o deja ambos vacíos.")
    if total >= Decimal("200") and not doc_type:
        raise BillingError("La referencia v1 exige identificar al receptor en operaciones desde $200.00.")
    recipient = {"tipoDocumento": doc_type, "numDocumento": doc_number, "nrc": None, "nombre": name,
                 "codActividad": None, "descActividad": None}
    email = form.get("correo", "").strip()
    if email:
        recipient["correo"] = email
    phone = form.get("telefono", "").strip()
    if phone:
        recipient["telefono"] = phone
    address = {key: form.get(key, "").strip() for key in ("departamento", "municipio", "complemento")}
    if any(address.values()):
        if not all(address.values()):
            raise BillingError("Completa departamento, municipio y dirección del cliente, o deja los tres vacíos.")
        validate_address_codes(address)
        recipient["direccion"] = address
    validate_schema(recipient, load_schema()["properties"]["receptor"])
    return recipient


def _spanish_integer(number):
    units = ["CERO", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE",
             "VEINTE", "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    if number < 30:
        return units[number]
    if number < 100:
        tens, rest = divmod(number, 10)
        return ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"][tens] + (" Y " + units[rest] if rest else "")
    if number == 100:
        return "CIEN"
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        return ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"][hundreds] + (" " + _spanish_integer(rest) if rest else "")
    thousands, rest = divmod(number, 1000)
    prefix = "MIL" if thousands == 1 else _spanish_integer(thousands).removesuffix("UNO") + ("UN" if _spanish_integer(thousands).endswith("UNO") else "") + " MIL"
    return prefix + (" " + _spanish_integer(rest) if rest else "")


def total_in_words(total):
    whole = int(total)
    cents = int((total - whole) * 100)
    word = _spanish_integer(whole)
    if word.endswith("UNO"):
        word = word[:-3] + "UN"
    return f"{word} {'DÓLAR' if whole == 1 else 'DÓLARES'} CON {cents:02d}/100 USD"


def snapshot_order(order):
    if order.estado != "pagada":
        raise BillingError("Solo se preparan documentos de órdenes completamente pagadas.")
    total = amount(order.total)
    if total <= ZERO or total >= Decimal("1000000"):
        raise BillingError("El borrador admite órdenes entre $0.01 y $999,999.99.")
    if amount(order.total_pagado) != total:
        raise BillingError("Los pagos deben coincidir exactamente con el total de la orden.")
    if any(amount(payment.propina or 0) != ZERO for payment in order.pagos):
        raise BillingError("Esta orden tiene propina. Define su tratamiento fiscal antes de generar un DTE; este preparador todavía no la admite.")
    lines = []
    for item in sorted(order.items_activos, key=lambda entry: entry.id):
        if not item.pagado or item.cantidad <= 0 or not item.producto:
            raise BillingError("Todos los productos activos deben estar pagados y tener cantidades válidas.")
        price = amount(item.precio_unitario)
        if price < ZERO:
            raise BillingError("No se admiten precios negativos.")
        description = item.producto.nombre.strip()
        if len(description) < 3:
            raise BillingError("Los nombres de productos necesitan al menos 3 caracteres para el esquema DTE.")
        lines.append({"item_id": item.id, "product_id": item.producto_id, "description": description,
                      "quantity": item.cantidad, "unit_price": price,
                      "total": amount(price * item.cantidad)})
    if not lines or len(lines) > 2000 or sum((line["total"] for line in lines), ZERO) != total:
        raise BillingError("El detalle de productos no coincide con el total pagado.")
    payments = []
    for payment in sorted(order.pagos, key=lambda entry: entry.id):
        if payment.metodo not in ("efectivo", "tarjeta") or amount(payment.monto) <= ZERO:
            raise BillingError("La orden contiene un pago no compatible con este preparador.")
        payments.append({"id": payment.id, "method": payment.metodo, "amount": amount(payment.monto)})
    return {"order_id": order.id, "table": order.mesa_etiqueta, "total": total, "lines": lines, "payments": payments,
            "prices_include_vat": True, "vat_rate": IVA_RATE, "special_tax_treatment": "no incluido"}


def build_payload(snapshot, issuer, recipient, sequence, generation_code, issued_at):
    lines = []
    for index, line in enumerate(snapshot["lines"], 1):
        iva = amount(line["total"] * IVA_RATE / (Decimal("1") + IVA_RATE))
        lines.append({"numItem": index, "tipoItem": 1, "numeroDocumento": None, "cantidad": line["quantity"],
                      "codigo": str(line["product_id"]), "codTributo": None, "uniMedida": 59,
                      "descripcion": line["description"], "precioUni": line["unit_price"], "montoDescu": ZERO,
                      "ventaNoSuj": ZERO, "ventaExenta": ZERO, "ventaGravada": line["total"], "tributos": None,
                      "psv": ZERO, "noGravado": ZERO, "ivaItem": iva})
    total = snapshot["total"]
    total_iva = sum((line["ivaItem"] for line in lines), ZERO)
    return {
        "identificacion": {"version": 1, "ambiente": "00", "tipoDte": "01",
            "numeroControl": f"DTE-01-{issuer['codEstable']}{issuer['codPuntoVenta']}-{sequence:015d}",
            "codigoGeneracion": generation_code, "tipoModelo": 1, "tipoOperacion": 1,
            "tipoContingencia": None, "motivoContin": None, "fecEmi": issued_at.strftime("%Y-%m-%d"),
            "horEmi": issued_at.strftime("%H:%M:%S"), "tipoMoneda": "USD"},
        "documentoRelacionado": None, "emisor": issuer, "receptor": recipient,
        "otrosDocumentos": None, "ventaTercero": None, "cuerpoDocumento": lines,
        "resumen": {"totalNoSuj": ZERO, "totalExenta": ZERO, "totalGravada": total, "subTotalVentas": total,
            "descuNoSuj": ZERO, "descuExenta": ZERO, "descuGravada": ZERO, "porcentajeDescuento": ZERO,
            "totalDescu": ZERO, "tributos": None, "subTotal": total, "ivaRete1": ZERO, "reteRenta": ZERO,
            "montoTotalOperacion": total, "totalNoGravado": ZERO, "totalPagar": total,
            "totalLetras": total_in_words(total), "totalIva": total_iva, "saldoFavor": ZERO,
            "condicionOperacion": 1, "pagos": [{"codigo": payment["fiscal_payment_code"],
                "montoPago": payment["amount"], "referencia": None, "plazo": None, "periodo": None}
                for payment in snapshot["payments"]], "numPagoElectronico": None},
        "extension": {"nombEntrega": None, "docuEntrega": None, "nombRecibe": None, "docuRecibe": None,
            "observaciones": "BORRADOR SIN VALIDEZ TRIBUTARIA. Sin firma ni sello de recepción de MH. Numeración local provisional.",
            "placaVehiculo": None},
        "apendice": [{"campo": "estado", "etiqueta": "Estado", "valor": "BORRADOR SIN VALIDEZ TRIBUTARIA"}],
    }


def _next_sequence(scope):
    existing = db.session.get(SecuenciaBorradorDTE, scope)
    if existing is None:
        try:
            with db.session.begin_nested():
                db.session.add(SecuenciaBorradorDTE(alcance=scope, siguiente=0))
                db.session.flush()
        except IntegrityError:
            pass  # Another transaction initialized the same sequence.
    # UPDATE acquires a write lock on SQLite and row lock on MySQL; the read is
    # inside that same transaction. A failed document insertion rolls it back.
    db.session.execute(update(SecuenciaBorradorDTE).where(SecuenciaBorradorDTE.alcance == scope)
                       .values(siguiente=SecuenciaBorradorDTE.siguiente + 1))
    row = db.session.execute(db.select(SecuenciaBorradorDTE).where(SecuenciaBorradorDTE.alcance == scope)
                             .execution_options(populate_existing=True)).scalar_one()
    return row.siguiente


def prepare_document(order, recipient_form, creator_id):
    existing = DocumentoFiscal.query.filter_by(orden_id=order.id).first()
    if existing:
        return existing, False
    issuer = issuer_from_profile(get_profile())
    snapshot = snapshot_order(order)
    if recipient_form.get("operacion_estandar") != "1":
        raise BillingError("Confirma que toda la orden corresponde al IVA estándar sin impuestos especiales, exenciones ni retenciones.")
    for payment in snapshot["payments"]:
        if payment["method"] == "efectivo":
            payment["fiscal_payment_code"] = "01"
        else:
            code = recipient_form.get(f"tarjeta_codigo_{payment['id']}")
            if code not in {"02", "03"}:
                raise BillingError("Selecciona si cada pago con tarjeta fue de débito o crédito.")
            payment["fiscal_payment_code"] = code
    recipient = recipient_from_form(recipient_form, snapshot["total"])
    issued_at = datetime.now(ZoneInfo("America/El_Salvador"))
    scope = f"{issuer['nit']}:00:01:{issued_at.year}:{issuer['codEstable']}:{issuer['codPuntoVenta']}"
    sequence = _next_sequence(scope)
    if sequence > 999999999999999:
        raise BillingError("Se agotó la secuencia local de borradores.")
    generation_code = str(uuid4()).upper()
    payload = build_payload(snapshot, issuer, recipient, sequence, generation_code, issued_at)
    validate_schema(payload)
    encoded = decimal_json(payload)
    document = DocumentoFiscal(orden_id=order.id, usuario_id=creator_id, codigo_generacion=generation_code,
        numero_control=payload["identificacion"]["numeroControl"], nombre_receptor=recipient["nombre"],
        total=snapshot["total"], iva=payload["resumen"]["totalIva"], documento_json=encoded,
        documento_sha256=hashlib.sha256(encoded.encode()).hexdigest(), snapshot_json=decimal_json(snapshot))
    db.session.add(document)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        existing = DocumentoFiscal.query.filter_by(orden_id=order.id).first()
        if existing:
            return existing, False
        raise
    audit_event("dte.borrador", "documento_fiscal", document.id,
                f"Borrador DTE 01 de orden #{order.id}. No transmitido.",
                {"orden_id": order.id, "estado": "BORRADOR", "ambiente": "00"})
    db.session.commit()
    return document, True


@event.listens_for(DocumentoFiscal, "before_update")
@event.listens_for(DocumentoFiscal, "before_delete")
def prevent_snapshot_changes(mapper, connection, target):
    raise BillingError("Los borradores fiscales son snapshots inmutables.")


def verified_payload(document):
    if hashlib.sha256(document.documento_json.encode()).hexdigest() != document.documento_sha256:
        raise BillingError("El snapshot fiscal no supera la verificación de integridad.")
    return json.loads(document.documento_json, parse_float=Decimal)


@billing_bp.app_context_processor
def billing_context():
    return {"billing_csrf_token": csrf_token}


@billing_bp.after_request
def fiscal_response_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@billing_bp.route("/")
@require_permission("facturacion.view")
def index():
    profile = get_profile()
    issues = []
    try:
        issuer_from_profile(profile)
    except BillingError as error:
        issues.append(str(error))
    documents = DocumentoFiscal.query.order_by(DocumentoFiscal.id.desc()).limit(100).all()
    paid_orders = Orden.query.filter(Orden.estado == "pagada", ~Orden.id.in_(db.select(DocumentoFiscal.orden_id)))\
        .order_by(Orden.id.desc()).limit(50).all()
    return render_template("billing.html", documents=documents, paid_orders=paid_orders, issues=issues,
                           profile=profile, reference=REFERENCE)


@billing_bp.route("/perfil", methods=["GET", "POST"])
@require_permission("facturacion.configure")
def setup():
    profile = get_profile()
    if request.method == "POST":
        check_csrf()
        profile = {key: request.form.get(key, "").strip() for key, _, _ in PROFILE_FIELDS}
        profile["tipoEstablecimiento"] = request.form.get("tipoEstablecimiento", "")
        profile["precios_iva_incluido"] = request.form.get("precios_iva_incluido") == "1"
        try:
            issuer_from_profile(profile)
            row = db.session.get(PreferenciaSistema, PROFILE_KEY)
            if row is None:
                row = PreferenciaSistema(clave=PROFILE_KEY)
                db.session.add(row)
            row.valor = json.dumps(profile, ensure_ascii=False)
            audit_event("dte.perfil", "preferencia", PROFILE_KEY, "Actualización del perfil fiscal del emisor.")
            db.session.commit()
            flash("Perfil fiscal guardado. La conexión con Hacienda sigue pendiente.", "success")
            return redirect(url_for("billing.index"))
        except BillingError as error:
            db.session.rollback()
            flash(str(error), "error")
    return render_template("billing_setup.html", profile=profile, fields=PROFILE_FIELDS)


@billing_bp.route("/orden/<int:order_id>/preparar", methods=["GET", "POST"])
@require_permission("facturacion.create")
def new(order_id):
    order = db.get_or_404(Orden, order_id)
    existing = DocumentoFiscal.query.filter_by(orden_id=order.id).first()
    if existing:
        return redirect(url_for("billing.detail", document_id=existing.id))
    issue = None
    try:
        issuer_from_profile(get_profile())
        snapshot_order(order)
    except BillingError as error:
        issue = str(error)
    form = request.form if request.method == "POST" else {"nombre": order.nombre_cliente or ""}
    if request.method == "POST":
        check_csrf()
        try:
            document, created = prepare_document(order, request.form, current_user.id)
            flash("Borrador preparado y validado contra la referencia v1. No se envió a Hacienda." if created
                  else "Esta orden ya tiene un borrador.", "success")
            return redirect(url_for("billing.detail", document_id=document.id))
        except BillingError as error:
            db.session.rollback()
            flash(str(error), "error")
    return render_template("billing_new.html", order=order, issue=issue, form=form)


@billing_bp.route("/<int:document_id>")
@require_permission("facturacion.view")
def detail(document_id):
    document = db.get_or_404(DocumentoFiscal, document_id)
    try:
        payload = verified_payload(document)
    except BillingError as error:
        abort(409, str(error))
    return render_template("billing_detail.html", document=document, payload=payload, reference=REFERENCE)


@billing_bp.route("/<int:document_id>/borrador.json")
@require_permission("facturacion.view")
def download(document_id):
    document = db.get_or_404(DocumentoFiscal, document_id)
    try:
        validate_schema(verified_payload(document))
    except BillingError as error:
        abort(409, str(error))
    response = Response(document.documento_json + "\n", mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="BORRADOR-DTE-01-orden-{document.orden_id}.json"'
    response.headers["X-Restobar-Estado"] = "BORRADOR-SIN-VALIDEZ-TRIBUTARIA"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
