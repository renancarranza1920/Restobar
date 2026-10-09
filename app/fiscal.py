"""Explicit sandbox actions. No production transmission or implicit retries."""

from datetime import datetime, timedelta
import json

from flask import Blueprint, Response, abort, current_app, flash, redirect, request, url_for
from flask_login import fresh_login_required
from sqlalchemy import event, or_, update
from sqlalchemy.exc import IntegrityError

from .billing import BillingError, check_csrf, decimal_json, require_permission, validate_current_payload, verified_payload
from .dte_transport import HaciendaClient, TransportError, classify_receipt, qr_url
from .extensions import db
from .models import DocumentoFiscal, FiscalEnvio, FiscalIntento
from .services import audit_event


fiscal_bp = Blueprint("fiscal", __name__, url_prefix="/facturacion")
ACCEPTED = "ACEPTADO_PRUEBA"
RECEIPT_FIELDS = {"version", "ambiente", "versionApp", "estado", "codigoGeneracion", "selloRecibido",
                  "fhProcesamiento", "clasificaMsg", "codigoMsg", "descripcionMsg", "observaciones"}


def transport_readiness(config=None):
    config = current_app.config if config is None else config
    reasons = []
    if not config.get("DTE_TRANSMISSION_ENABLED"):
        reasons.append("La transmisión de pruebas está desactivada.")
    if config.get("DTE_ENVIRONMENT", "00") != "00":
        reasons.append("Esta versión únicamente permite el ambiente de pruebas 00.")
    missing = [name for name in ("DTE_API_USER", "DTE_API_PASSWORD", "DTE_SIGNER_PASSWORD", "DTE_SIGNER_URL")
               if not str(config.get(name) or "").strip()]
    if missing:
        labels = {"DTE_API_USER": "usuario de Hacienda", "DTE_API_PASSWORD": "contraseña de Hacienda",
                  "DTE_SIGNER_PASSWORD": "contraseña del firmador", "DTE_SIGNER_URL": "servicio de firma"}
        reasons.append("Falta configurar de forma segura: " + ", ".join(labels[name] for name in missing) + ".")
    return {"enabled": not reasons, "reasons": reasons}


def clean_receipt(receipt):
    """Persist protocol evidence, never arbitrary authentication response data."""
    if not isinstance(receipt, dict):
        return {}
    result = {}
    for key in RECEIPT_FIELDS:
        value = receipt.get(key)
        if isinstance(value, str):
            result[key] = value[:1000]
        elif key == "observaciones" and isinstance(value, list):
            result[key] = [str(item)[:500] for item in value[:100]]
        elif type(value) in (int, bool) or value is None:
            result[key] = value
    return result


def receipt_for(envio):
    try:
        return json.loads(envio.respuesta_json or "{}")
    except (ValueError, TypeError):
        return {}


def transport_context(document, payload, legacy=False):
    envio = FiscalEnvio.query.filter_by(documento_id=document.id).first()
    receipt = receipt_for(envio) if envio else {}
    attempts = (FiscalIntento.query.filter_by(envio_id=envio.id).order_by(FiscalIntento.id.desc()).limit(10).all()
                if envio else [])
    accepted = bool(not legacy and payload.get("identificacion", {}).get("ambiente") == "00"
                    and envio and envio.estado == ACCEPTED and envio.firma and envio.sello
                    and classify_receipt(receipt, payload) == "accepted")
    return {"fiscal_envio": envio, "fiscal_attempts": attempts, "fiscal_receipt": receipt,
            "fiscal_readiness": transport_readiness(), "fiscal_accepted": accepted,
            "fiscal_qr_url": qr_url(payload) if accepted and not legacy else None}


def _get_envio(document):
    existing = FiscalEnvio.query.filter_by(documento_id=document.id).first()
    if existing is None:
        try:
            with db.session.begin_nested():
                db.session.add(FiscalEnvio(documento_id=document.id))
                db.session.flush()
        except IntegrityError:
            pass  # A concurrent click created the unique document transmission.
        existing = FiscalEnvio.query.filter_by(documento_id=document.id).one()
    db.session.commit()
    return existing


def _claim(envio, query_only=False):
    now = datetime.utcnow()
    db.session.refresh(envio)
    if envio.estado == ACCEPTED:
        return "accepted"
    if envio.ocupado_hasta and envio.ocupado_hasta > now:
        raise BillingError("Hay una operación fiscal en curso. Espera antes de volver a consultar.")
    # A POST was durably recorded before calling Hacienda. An expired lease or
    # ambiguous response can therefore only lead to consultation, never resend.
    query_only = query_only or envio.transmisiones > 0 or envio.estado in {"ENVIO_INCIERTO", "RECHAZADO", "ENVIANDO"}
    if query_only and not envio.transmisiones:
        raise BillingError("Este borrador todavía no se ha transmitido; no hay recepción que consultar.")
    previous = envio.estado
    lease = now + timedelta(seconds=180)
    claimed = db.session.execute(update(FiscalEnvio).where(
        FiscalEnvio.id == envio.id, FiscalEnvio.estado == previous,
        or_(FiscalEnvio.ocupado_hasta.is_(None), FiscalEnvio.ocupado_hasta <= now),
        FiscalEnvio.estado != ACCEPTED,
    ).values(estado="EN_PROCESO", ocupado_hasta=lease, updated_at=now)).rowcount
    db.session.commit()
    if claimed != 1:
        raise BillingError("Otro proceso está atendiendo este documento. Consulta su estado en unos segundos.")
    db.session.refresh(envio)
    return "query" if query_only else "send"


def _record(envio, stage, result, message, receipt=None):
    safe = clean_receipt(receipt) if receipt else None
    db.session.add(FiscalIntento(envio_id=envio.id, etapa=stage, resultado=result,
                                mensaje=message[:500], respuesta_json=decimal_json(safe) if safe else None))


def _finish(envio, state, message, receipt=None):
    envio.estado = state
    envio.mensaje = message[:500]
    envio.ocupado_hasta = None
    if receipt is not None:
        envio.respuesta_json = decimal_json(clean_receipt(receipt))
    if state == ACCEPTED:
        envio.sello = receipt["selloRecibido"]
    db.session.commit()


def _resolve(envio, payload, receipt, stage):
    classification = classify_receipt(receipt, payload)
    if classification == "accepted":
        message = "Hacienda confirmó la recepción en el ambiente de pruebas. Sin validez tributaria."
        state = ACCEPTED
    elif classification == "rejected":
        message = "Hacienda rechazó el documento de prueba. Se conserva la respuesta sin modificar el borrador."
        state = "RECHAZADO"
    else:
        message = "No se pudo confirmar la recepción. Consulta de nuevo; este documento no se reenviará automáticamente."
        state = "ENVIO_INCIERTO"
    _record(envio, stage, state, message, receipt)
    _finish(envio, state, message, receipt)
    return envio


def _consult(envio, payload, client):
    try:
        receipt = client.consult(payload)
    except TransportError as error:
        receipt = error.receipt or {}
        if classify_receipt(receipt, payload) in {"accepted", "rejected"}:
            return _resolve(envio, payload, receipt, "consulta")
        message = "La consulta no confirmó la recepción. Conservamos el estado pendiente; no se reenvía el documento."
        _record(envio, "consulta", "ENVIO_INCIERTO", message, receipt)
        _finish(envio, "ENVIO_INCIERTO", message, receipt)
        return envio
    return _resolve(envio, payload, receipt, "consulta")


def submit_document(document, query_only=False, client=None):
    """Claim one operation, sign once, send at most once, reconcile by query."""
    payload = verified_payload(document)
    validate_current_payload(payload)
    if document.ambiente != "00" or payload["identificacion"]["ambiente"] != "00":
        raise BillingError("La transmisión a producción está bloqueada.")
    readiness = transport_readiness()
    if not readiness["enabled"]:
        raise BillingError(" ".join(readiness["reasons"]))
    envio = _get_envio(document)
    mode = _claim(envio, query_only)
    if mode == "accepted":
        return envio
    try:
        client = client or HaciendaClient(current_app.config)
    except TransportError:
        state = "ENVIO_INCIERTO" if envio.transmisiones else "ERROR_LOCAL"
        message = "Revisa la configuración segura del firmador y del conector de pruebas."
        _record(envio, "configuracion", state, message)
        _finish(envio, state, message)
        return envio
    if mode == "query":
        return _consult(envio, payload, client)
    try:
        if not envio.firma:
            envio.firma = client.sign(payload)
            _record(envio, "firma", "FIRMADO", "Firmador devolvió el JWS del mismo documento de prueba.")
            db.session.commit()
        # Authenticate before the durable send marker: a credential failure
        # cannot be confused with an already transmitted document.
        client.authenticate()
    except TransportError:
        message = "No se completó la firma o autenticación. Revisa el firmador y la configuración segura; no se transmitió el documento."
        _record(envio, "preparacion", "ERROR_LOCAL", message)
        _finish(envio, "ERROR_LOCAL", message)
        return envio
    envio.estado = "ENVIANDO"
    envio.transmisiones += 1
    _record(envio, "envio", "ENVIANDO", "Solicitud de recepción iniciada en el ambiente 00.")
    db.session.commit()
    try:
        receipt = client.send(payload, envio.firma, envio.id)
    except TransportError as error:
        if classify_receipt(error.receipt or {}, payload) in {"accepted", "rejected"}:
            return _resolve(envio, payload, error.receipt, "envio")
        _record(envio, "envio", "ENVIO_INCIERTO", "La solicitud no obtuvo una recepción verificable; se consulta antes de cualquier otra acción.")
        # Keep the lease while consulting; the durable count prevents resend
        # even if this worker dies between sending and storing the receipt.
        envio.estado = "ENVIO_INCIERTO"
        db.session.commit()
        return _consult(envio, payload, client)
    if classify_receipt(receipt, payload) == "unknown":
        _record(envio, "envio", "ENVIO_INCIERTO", "Respuesta sin recepción verificable; consultando estado.", receipt)
        envio.estado = "ENVIO_INCIERTO"
        db.session.commit()
        return _consult(envio, payload, client)
    return _resolve(envio, payload, receipt, "envio")


@event.listens_for(FiscalIntento, "before_update")
@event.listens_for(FiscalIntento, "before_delete")
def prevent_attempt_changes(mapper, connection, target):
    raise BillingError("El historial fiscal es inmutable.")


@event.listens_for(FiscalEnvio, "before_update")
def prevent_accepted_changes(mapper, connection, target):
    previous = connection.execute(db.select(FiscalEnvio.estado).where(FiscalEnvio.id == target.id)).scalar_one()
    if previous == ACCEPTED:
        raise BillingError("La evidencia de una recepción confirmada es inmutable.")


@event.listens_for(FiscalEnvio, "before_delete")
def prevent_transmission_deletion(mapper, connection, target):
    raise BillingError("El historial de transmisión fiscal no puede eliminarse.")


def _action(document_id, query_only):
    check_csrf()
    if not query_only and request.form.get("confirmar_prueba") != "1":
        abort(400, "Confirma explícitamente el envío al ambiente de pruebas.")
    document = db.get_or_404(DocumentoFiscal, document_id)
    try:
        envio = submit_document(document, query_only=query_only)
        audit_event("dte.consulta_prueba" if query_only else "dte.envio_prueba", "documento_fiscal", document.id,
                    envio.mensaje, {"estado": envio.estado, "ambiente": "00", "transmisiones": envio.transmisiones})
        db.session.commit()
        flash(envio.mensaje, "success" if envio.estado == ACCEPTED else "warning")
    except BillingError as error:
        db.session.rollback()
        flash(str(error), "warning")
    return redirect(url_for("billing.detail", document_id=document.id))


@fiscal_bp.post("/<int:document_id>/transmitir-prueba")
@require_permission("facturacion.send_test")
@fresh_login_required
def transmit_test(document_id):
    return _action(document_id, False)


@fiscal_bp.post("/<int:document_id>/consultar-prueba")
@require_permission("facturacion.send_test")
@fresh_login_required
def consult_test(document_id):
    return _action(document_id, True)


@fiscal_bp.get("/<int:document_id>/recepcion-prueba.json")
@require_permission("facturacion.view")
def download_test_receipt(document_id):
    document = db.get_or_404(DocumentoFiscal, document_id)
    try:
        payload = verified_payload(document)
        validate_current_payload(payload)
        envio = FiscalEnvio.query.filter_by(documento_id=document.id, estado=ACCEPTED).first()
        if not envio or not envio.firma or not envio.sello or classify_receipt(receipt_for(envio), payload) != "accepted":
            abort(409, "No hay una recepción de pruebas verificable.")
        payload["firmaElectronica"] = envio.firma
        payload["selloRecibido"] = envio.sello
        response = Response(decimal_json(payload) + "\n", mimetype="application/json")
        response.headers["Content-Disposition"] = f'attachment; filename="DTE-PRUEBA-{document.codigo_generacion}.json"'
        response.headers["Cache-Control"] = "no-store"
        return response
    except BillingError as error:
        abort(409, str(error))
