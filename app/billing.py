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
from .fiscal_catalogs import catalog_options, catalog_label, validate_catalog_code, municipality_options, district_options
from .models import DocumentoFiscal, Orden, PreferenciaSistema, SecuenciaBorradorDTE
from .services import audit_event, user_can


billing_bp = Blueprint("billing", __name__, url_prefix="/facturacion")
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
IVA_RATE = Decimal("0.13")
BODY_PRECISION = Decimal("0.00000001")
PROFILE_KEY = "dte.emisor.v1"
REFERENCE = json.loads((Path(__file__).parent / "schemas/dte-reference.json").read_text())
PROFILE_FIELDS = [
    ("nit", "NIT sin guiones", 14), ("nrc", "NRC sin guiones", 8),
    ("nombre", "Razón social", 250), ("nombreComercial", "Nombre comercial (opcional)", 150),
    ("codActividad", "Código de actividad MH", 6), ("descActividad", "Actividad económica", 150),
    ("departamento", "Código de departamento", 2), ("municipio", "Municipio", 2), ("distrito", "Distrito", 2),
    ("complemento", "Dirección del establecimiento", 200), ("telefono", "Teléfono", 30),
    ("correo", "Correo del emisor", 100), ("codEstable", "Código interno del establecimiento (4 caracteres)", 4),
    ("codPuntoVenta", "Código interno del punto de venta (4 caracteres)", 4),
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


def schema_metadata(tipo_dte="01", version=None):
    reference = REFERENCE["schemas"].get(tipo_dte)
    if reference is None or (version is not None and version != reference["version"]):
        raise BillingError("Esquema fiscal anterior o no compatible. Conserva el documento original; no puede enviarse con los esquemas actuales.")
    return reference


@lru_cache(maxsize=8)
def _load_schema(path, modified_ns, expected_sha):
    content = Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha:
        raise BillingError("La referencia DTE no coincide con su checksum. Revisa la instalación.")
    Draft7Validator.check_schema(json.loads(content))
    return json.loads(content, parse_float=Decimal)


def load_schema(tipo_dte="01", version=None):
    reference = schema_metadata(tipo_dte, version)
    # The optional override remains compatible with existing FE configuration.
    override = current_app.config.get("DTE_SCHEMA_PATH") if tipo_dte == "01" else None
    path = Path(override or Path(__file__).parent / "schemas" / reference["path"])
    if not path.is_file():
        raise BillingError("Falta la referencia DTE oficial incluida. Verifica los archivos de la aplicación.")
    return _load_schema(str(path.resolve()), path.stat().st_mtime_ns, reference["sha256"])


def validate_schema(payload, schema=None):
    if schema is None:
        identification = payload.get("identificacion", {})
        schema = load_schema(identification.get("tipoDte", ""), identification.get("version"))
    errors = sorted(Draft7Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
                    key=lambda error: tuple(str(part) for part in error.absolute_path))
    if errors:
        messages = [f"{'.'.join(str(part) for part in error.absolute_path) or 'documento'}: {error.message[:240]}"
                    for error in errors[:5]]
        raise BillingError("Revisa los datos fiscales: " + "; ".join(messages))


def validate_current_payload(payload):
    """Require an explicit supported type/version before any signing or sending."""
    if not isinstance(payload, dict):
        raise BillingError("Documento fiscal inválido.")
    identification = payload.get("identificacion", {})
    if not isinstance(identification, dict) or identification.get("tipoDte") not in {"01", "03"}:
        raise BillingError("Tipo de documento fiscal no compatible.")
    if identification.get("version") != schema_metadata(identification["tipoDte"])["version"]:
        raise BillingError("Este snapshot usa un esquema anterior. Se conserva para consulta y no puede firmarse ni enviarse.")
    validate_schema(payload)
    validate_address_codes(payload["emisor"]["direccion"])
    if payload["receptor"].get("direccion"):
        validate_address_codes(payload["receptor"]["direccion"])
    for party in (payload["emisor"], payload["receptor"]):
        if party.get("codActividad") and not validate_catalog_code("CAT-019", party["codActividad"]):
            raise BillingError("Actividad económica fuera del catálogo oficial.")
    for payment in payload["resumen"].get("pagos") or []:
        if not validate_catalog_code("CAT-017", payment["codigo"]):
            raise BillingError("Forma de pago fuera del catálogo oficial.")
    _validate_standard_arithmetic(payload)


def _validate_standard_arithmetic(payload):
    """Validate supported fiscal math as well as the structural MH schema.

    The Functional Manual pp. 52–54 uses eight body decimals, two summary
    decimals and a one-cent line arithmetic tolerance. Restobar only prepares
    standard 13% VAT sales without discounts or additional fiscal treatments.
    """
    def number(value):
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise BillingError("Monto fiscal inválido.") from error
        if not result.is_finite():
            raise BillingError("Monto fiscal inválido.")
        return result

    def ensure(condition):
        if not condition:
            raise BillingError("Los cálculos del documento fiscal no concilian con el IVA del 13 % y el total cobrado. Conserva el snapshot para revisión; no puede firmarse ni enviarse.")

    kind = payload["identificacion"]["tipoDte"]
    summary = payload["resumen"]
    total_base = ZERO
    total_vat = ZERO
    for line in payload["cuerpoDocumento"]:
        taxable = number(line["ventaGravada"])
        quantity = number(line["cantidad"])
        unit = number(line["precioUni"])
        ensure(unit >= ZERO and quantity > ZERO)
        ensure(abs(unit * quantity - taxable) <= CENT)
        ensure(all(number(line[key]) == ZERO for key in ("ventaNoSuj", "ventaExenta", "montoDescu", "psv", "noGravado")))
        ensure(line["tipoItem"] == 1 and line["codTributo"] is None)
        if kind == "01":
            expected_vat = (taxable * IVA_RATE / (Decimal("1") + IVA_RATE)).quantize(BODY_PRECISION, rounding=ROUND_HALF_UP)
            ensure(line["tributos"] is None and number(line["ivaItem"]) == expected_vat)
            total_vat += number(line["ivaItem"])
        else:
            ensure(line["tributos"] == ["20"])
            total_vat += (taxable * IVA_RATE).quantize(BODY_PRECISION, rounding=ROUND_HALF_UP)
        total_base += taxable
    total_base = amount(total_base)
    ensure(all(number(summary[key]) == ZERO for key in ("totalNoSuj", "totalExenta", "descuNoSuj", "descuExenta", "descuGravada", "porcentajeDescuento", "totalDescu", "ivaRete", "totalNoGravado", "saldoFavor")))
    ensure(number(summary["totalGravada"]) == total_base and number(summary["subTotalVentas"]) == total_base and number(summary["subTotal"]) == total_base)
    ensure(summary["condicionOperacion"] == 1)
    if kind == "01":
        ensure(summary["tributos"] is None and number(summary["totalIva"]) == amount(total_vat))
        operation = total_base
    else:
        tributes = summary["tributos"] or []
        ensure(len(tributes) == 1 and tributes[0]["codigo"] == "20")
        ensure(number(tributes[0]["valor"]) == amount(total_vat) and number(summary["ivaPerci"]) == ZERO)
        total_vat = amount(total_vat)
        operation = total_base + total_vat
    ensure(number(summary["montoTotalOperacion"]) == operation and number(summary["totalPagar"]) == operation)
    payments = summary["pagos"] or []
    ensure(bool(payments) and sum((number(payment["montoPago"]) for payment in payments), ZERO) == operation)
    ensure(all(payment["codigo"] in {"01", "02", "03"} and number(payment["montoPago"]) > ZERO for payment in payments))


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
        profile = json.loads(stored.valor)
        return profile if isinstance(profile, dict) else {}
    except (ValueError, TypeError):
        return {}


def _validate_tax_id(value, label):
    if not re.fullmatch(r"(?:[0-9]{9}|[0-9]{14})", value or ""):
        raise BillingError(f"{label}: usa 9 o 14 dígitos sin guiones, según tu inscripción.")


def issuer_from_profile(profile, tipo_dte="01"):
    required = {field[0] for field in PROFILE_FIELDS} - {"nombreComercial"}
    if any(not str(profile.get(key, "")).strip() for key in required):
        raise BillingError("Completa todos los datos obligatorios del emisor en Perfil fiscal.")
    if profile.get("precios_iva_incluido") is not True:
        raise BillingError("Confirma que los precios de venta ya incluyen el IVA estándar del 13 %.")
    for key, label, maxlength in PROFILE_FIELDS:
        if len(str(profile.get(key, ""))) > maxlength:
            raise BillingError(f"{label}: máximo {maxlength} caracteres.")
    _validate_tax_id(profile.get("nit"), "NIT del emisor")
    if not re.fullmatch(r"[0-9]{2,8}", profile.get("nrc", "")):
        raise BillingError("NRC del emisor: usa de 2 a 8 dígitos sin guiones.")
    if not re.fullmatch(r"[MBSP][0-9]{3}", profile.get("codEstable", "")) or not re.fullmatch(r"P[0-9]{3}", profile.get("codPuntoVenta", "")):
        raise BillingError("Número de control: el establecimiento debe usar M/B/S/P y 3 dígitos; el punto de venta P y 3 dígitos (ej. M001/P001).")
    if not validate_catalog_code("CAT-019", profile["codActividad"]):
        raise BillingError("Selecciona una actividad económica del catálogo oficial.")
    issuer = {key: profile.get(key) or None for key in
              ("nit", "nrc", "nombre", "codActividad", "descActividad", "nombreComercial", "telefono", "correo",
               "codEstable", "codPuntoVenta")}
    issuer["direccion"] = {key: profile.get(key, "") for key in ("departamento", "municipio", "distrito", "complemento")}
    validate_address_codes(issuer["direccion"])
    if not FormatChecker().conforms(issuer["correo"], "email"):
        raise BillingError("Correo del emisor inválido.")
    validate_schema(issuer, load_schema(tipo_dte)["properties"]["emisor"])
    return issuer


def validate_address_codes(address):
    department = address.get("departamento", "")
    if not validate_catalog_code("CAT-012", department):
        raise BillingError("Selecciona un departamento del catálogo oficial.")
    if not validate_catalog_code("CAT-013", address.get("municipio", ""), department=department):
        raise BillingError("El municipio no corresponde al departamento en el catálogo oficial de 44 municipios.")
    if address.get("distrito", "") not in {item["code"] for item in district_options(department)}:
        raise BillingError("El distrito no corresponde al departamento del catálogo oficial.")
    # The workbook groups districts by department, without a municipality/district relation.


def recipient_from_form(form, total, tipo_dte="01"):
    name = form.get("nombre", "").strip()
    if not name:
        raise BillingError("Escribe el nombre del cliente para el borrador (regla de Restobar).")
    email = form.get("correo", "").strip() or None
    phone = form.get("telefono", "").strip() or None
    if email and not FormatChecker().conforms(email, "email"):
        raise BillingError("Correo del cliente inválido.")
    address = {key: form.get(key, "").strip() for key in ("departamento", "municipio", "distrito", "complemento")}
    if any(address.values()) or tipo_dte == "03":
        if not all(address.values()):
            raise BillingError("Completa departamento, municipio, distrito y dirección del cliente.")
        validate_address_codes(address)
    else:
        address = None
    if tipo_dte == "03":
        nit = form.get("nit", "").strip()
        nrc = form.get("nrc", "").strip()
        activity = form.get("codActividad", "").strip()
        _validate_tax_id(nit, "NIT del cliente")
        if not re.fullmatch(r"[0-9]{2,8}", nrc):
            raise BillingError("Para CCF, Restobar requiere el NRC del cliente (2 a 8 dígitos).")
        if not validate_catalog_code("CAT-019", activity):
            raise BillingError("Selecciona la actividad económica del cliente del catálogo oficial.")
        recipient = {"nit": nit, "nrc": nrc, "nombre": name, "codActividad": activity,
                     "descActividad": form.get("descActividad", "").strip(),
                     "nombreComercial": form.get("nombreComercial", "").strip() or None,
                     "direccion": address, "telefono": phone, "correo": email}
    elif tipo_dte == "01":
        doc_type = form.get("tipoDocumento", "").strip() or None
        doc_number = form.get("numDocumento", "").strip() or None
        if doc_type and not validate_catalog_code("CAT-022", doc_type):
            raise BillingError("Tipo de documento del cliente inválido.")
        if bool(doc_type) != bool(doc_number):
            raise BillingError("Completa el tipo y número de documento del cliente, o deja ambos vacíos.")
        if doc_type == "13" and not re.fullmatch(r"[0-9]{8}-[0-9]", doc_number):
            raise BillingError("DUI del cliente: usa 8 dígitos, guion y 1 dígito.")
        if doc_type == "36":
            _validate_tax_id(doc_number, "NIT del cliente")
        recipient = {"tipoDocumento": doc_type, "numDocumento": doc_number, "nrc": None, "nombre": name,
                     "codActividad": None, "descActividad": None, "direccion": address, "telefono": phone, "correo": email}
    else:
        raise BillingError("Selecciona Factura 01 o Comprobante de Crédito Fiscal 03.")
    validate_schema(recipient, load_schema(tipo_dte)["properties"]["receptor"])
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
        if not isinstance(item.cantidad, int) or isinstance(item.cantidad, bool):
            raise BillingError("Restobar admite cantidades enteras de productos; revisa esta orden antes de preparar su documento fiscal.")
        if not item.pagado or item.cantidad <= 0 or not item.producto:
            raise BillingError("Todos los productos activos deben estar pagados y tener cantidades válidas.")
        price = amount(item.precio_unitario)
        if price < ZERO:
            raise BillingError("No se admiten precios negativos.")
        description = item.producto.nombre.strip()
        if not description:
            raise BillingError("Los productos necesitan un nombre para el documento fiscal.")
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


def _ccf_net_lines(snapshot):
    """Keep eight net body decimals, then round aggregate base and item VAT.

    Functional Manual p. 32 consolidates taxes calculated per item; pp. 52–54
    give eight body decimals and two summary decimals. VAT is calculated from
    the unrounded body base, never from the already rounded summary base.
    """
    net = [(line["total"] / (Decimal("1") + IVA_RATE)).quantize(BODY_PRECISION, rounding=ROUND_HALF_UP)
           for line in snapshot["lines"]]
    iva = amount(sum(((value * IVA_RATE).quantize(BODY_PRECISION, rounding=ROUND_HALF_UP)
                      for value in net), ZERO))
    if amount(sum(net, ZERO)) + iva != snapshot["total"]:
        raise BillingError("El redondeo de esta orden de CCF requiere revisión del contador. No se modificará el monto cobrado.")
    return net, iva


def build_payload(snapshot, issuer, recipient, sequence, generation_code, issued_at, tipo_dte="01"):
    reference = schema_metadata(tipo_dte)
    if tipo_dte not in {"01", "03"}:
        raise BillingError("Tipo de DTE no compatible.")
    net, ccf_iva = _ccf_net_lines(snapshot) if tipo_dte == "03" else (None, None)
    lines = []
    for index, line in enumerate(snapshot["lines"], 1):
        # Functional Manual pp. 52–54: body amounts retain up to eight
        # decimals; only the summary is rounded to cents.
        iva = (line["total"] * IVA_RATE / (Decimal("1") + IVA_RATE)).quantize(BODY_PRECISION, rounding=ROUND_HALF_UP)
        taxable = line["total"] if tipo_dte == "01" else net[index - 1]
        unit = line["unit_price"] if tipo_dte == "01" else (line["unit_price"] / (Decimal("1") + IVA_RATE)).quantize(BODY_PRECISION, rounding=ROUND_HALF_UP)
        if tipo_dte == "03" and abs(unit * Decimal(line["quantity"]) - taxable) > CENT:
            raise BillingError("La cantidad de esta línea de CCF no permite conciliar el precio unitario a ocho decimales. Revisa su presentación con el contador; no se modificará el total cobrado.")
        item = {"numItem": index, "tipoItem": 1, "numeroDocumento": None, "cantidad": line["quantity"],
                "codigo": str(line["product_id"]), "codTributo": None, "uniMedida": 59,
                "descripcion": line["description"], "precioUni": unit, "montoDescu": ZERO,
                "ventaNoSuj": ZERO, "ventaExenta": ZERO, "ventaGravada": taxable,
                "tributos": None if tipo_dte == "01" else ["20"], "psv": ZERO, "noGravado": ZERO}
        if tipo_dte == "01":
            item["ivaItem"] = iva
        lines.append(item)
    total = snapshot["total"]
    taxable_total = amount(sum((line["ventaGravada"] for line in lines), ZERO))
    total_iva = amount(sum((line["ivaItem"] for line in lines), ZERO)) if tipo_dte == "01" else ccf_iva
    summary = {"totalNoSuj": ZERO, "totalExenta": ZERO, "totalGravada": taxable_total, "subTotalVentas": taxable_total,
        "descuNoSuj": ZERO, "descuExenta": ZERO, "descuGravada": ZERO, "porcentajeDescuento": ZERO,
        "totalDescu": ZERO, "tributos": None if tipo_dte == "01" else [{"codigo": "20", "descripcion": "Impuesto al Valor Agregado 13%", "valor": total_iva}],
        "subTotal": taxable_total, "ivaRete": ZERO, "montoTotalOperacion": total, "totalNoGravado": ZERO, "totalPagar": total,
        "totalLetras": total_in_words(total), "saldoFavor": ZERO,
        "condicionOperacion": 1, "pagos": [{"codigo": payment["fiscal_payment_code"], "montoPago": payment["amount"],
            "referencia": None, "plazo": None, "periodo": None} for payment in snapshot["payments"]],
        "numPagoElectronico": None,
        "observaciones": "BORRADOR SIN VALIDEZ TRIBUTARIA. Sin firma ni sello de recepción de MH. Numeración local provisional."}
    if tipo_dte == "01":
        summary["totalIva"] = total_iva
    else:
        summary["ivaPerci"] = ZERO
    return {
        "identificacion": {"version": reference["version"], "ambiente": "00", "tipoDte": tipo_dte,
            "numeroControl": f"DTE-{tipo_dte}-{issuer['codEstable']}{issuer['codPuntoVenta']}-{sequence:015d}",
            "codigoGeneracion": generation_code, "tipoModelo": 1, "tipoOperacion": 1,
            "tipoContingencia": None, "motivoContin": None, "fecEmi": issued_at.strftime("%Y-%m-%d"),
            "horEmi": issued_at.strftime("%H:%M:%S"), "tipoMoneda": "USD"},
        "documentoRelacionado": None, "emisor": issuer, "receptor": recipient,
        "otrosDocumentos": None, "ventaTercero": None, "cuerpoDocumento": lines, "resumen": summary,
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
    tipo_dte = recipient_form.get("tipo_dte", "01")
    if tipo_dte not in {"01", "03"}:
        raise BillingError("Selecciona Factura 01 o Comprobante de Crédito Fiscal 03.")
    issuer = issuer_from_profile(get_profile(), tipo_dte)
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
    recipient = recipient_from_form(recipient_form, snapshot["total"], tipo_dte)
    issued_at = datetime.now(ZoneInfo("America/El_Salvador"))
    scope = f"{issuer['nit']}:00:{tipo_dte}:{issued_at.year}:{issuer['codEstable']}:{issuer['codPuntoVenta']}"
    sequence = _next_sequence(scope)
    if sequence > 999999999999999:
        raise BillingError("Se agotó la secuencia local de borradores.")
    generation_code = str(uuid4()).upper()
    payload = build_payload(snapshot, issuer, recipient, sequence, generation_code, issued_at, tipo_dte)
    validate_current_payload(payload)
    encoded = decimal_json(payload)
    document = DocumentoFiscal(orden_id=order.id, usuario_id=creator_id, codigo_generacion=generation_code,
        numero_control=payload["identificacion"]["numeroControl"], nombre_receptor=recipient["nombre"],
        tipo_dte=tipo_dte, ambiente="00", total=snapshot["total"],
        iva=payload["resumen"].get("totalIva", sum((tribute["valor"] for tribute in payload["resumen"].get("tributos") or [] if tribute["codigo"] == "20"), ZERO)), documento_json=encoded,
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
                f"Borrador DTE {tipo_dte} de orden #{order.id}. No transmitido.",
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
    try:
        payload = json.loads(document.documento_json, parse_float=Decimal)
        if not isinstance(payload, dict) or not isinstance(payload.get("identificacion"), dict):
            raise BillingError("El snapshot fiscal contiene un documento inválido.")
        return payload
    except (ValueError, TypeError) as error:
        raise BillingError("El snapshot fiscal contiene JSON inválido.") from error


@billing_bp.app_context_processor
def billing_context():
    return {"billing_csrf_token": csrf_token, "fiscal_catalog_options": catalog_options,
            "fiscal_catalog_label": catalog_label, "municipality_options": municipality_options,
            "district_options": district_options,
            "fiscal_geography": {"municipalities": {option["code"]: municipality_options(option["code"]) for option in catalog_options("CAT-012")},
                                 "districts": {option["code"]: district_options(option["code"]) for option in catalog_options("CAT-012")}}}


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
            flash("Borrador preparado y validado contra el esquema oficial aportado. No se envió a Hacienda." if created
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
    identification = payload.get("identificacion", {})
    legacy = identification.get("tipoDte") not in {"01", "03"} or identification.get("version") != REFERENCE["schemas"].get(identification.get("tipoDte"), {}).get("version")
    if not legacy:
        try:
            validate_current_payload(payload)
        except BillingError as error:
            abort(409, str(error))
    from .fiscal import transport_context
    return render_template("billing_detail.html", document=document, payload=payload, reference=REFERENCE, legacy=legacy,
                           **transport_context(document, payload, legacy))


@billing_bp.route("/<int:document_id>/borrador.json")
@require_permission("facturacion.view")
def download(document_id):
    document = db.get_or_404(DocumentoFiscal, document_id)
    try:
        payload = verified_payload(document)
        identification = payload.get("identificacion", {})
        legacy = identification.get("version") != REFERENCE["schemas"].get(identification.get("tipoDte"), {}).get("version")
        if not legacy:
            validate_current_payload(payload)
    except BillingError as error:
        abort(409, str(error))
    response = Response(document.documento_json + "\n", mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="{"LEGADO-" if legacy else ""}BORRADOR-DTE-{document.tipo_dte}-orden-{document.orden_id}.json"'
    response.headers["X-Restobar-Estado"] = "BORRADOR-SIN-VALIDEZ-TRIBUTARIA"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
