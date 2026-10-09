"""Sandbox adapters for the user-supplied MH Technical Manual V2.0.

These adapters never authorize emission on their own. The application must check
permissions, current schema/catalogs and submission state before calling them.
Decoding a JWS checks document identity, not certificate or signature validity;
the configured official signer and Hacienda perform those checks.
"""

import base64
from datetime import date
from decimal import Decimal
import hashlib
from http.client import HTTPException
import ipaddress
import json
import math
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .billing import decimal_json


SANDBOX_BASE = "https://apitest.dtes.mh.gob.sv"
DEFAULT_SIGNER_URL = "http://127.0.0.1:8113/firmardocumento/"
USER_AGENT = "Restobar-DTE/2.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SUPPORTED_VERSIONS = {"01": 2, "03": 4}
_TOKEN_CACHE = {}
_TOKEN_LOCK = threading.Lock()
_RECEIPT_KEYS = frozenset({
    "version", "ambiente", "versionApp", "estado", "codigoGeneracion",
    "selloRecibido", "fhProcesamiento", "clasificaMsg", "codigoMsg",
    "descripcionMsg", "observaciones",
})


class TransportError(ValueError):
    """Safe error text; ambiguous means MH may already have received a send."""

    def __init__(self, message, ambiguous=False, receipt=None):
        super().__init__(message)
        self.ambiguous = bool(ambiguous)
        self.receipt = receipt


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward an API token or signer password.
        return None


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _parse_json(raw):
    return json.loads(raw, parse_float=Decimal, parse_constant=_reject_constant,
                      object_pairs_hook=_unique_object)


def _json_body(value):
    try:
        return decimal_json(value).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise TransportError("El documento contiene datos JSON inválidos.") from None


def _identification(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("identificacion"), dict):
        raise TransportError("Documento fiscal inválido.")
    identification = payload["identificacion"]
    if identification.get("ambiente") != "00":
        raise TransportError("Este conector permite únicamente el ambiente de pruebas 00.")
    kind, version = identification.get("tipoDte"), identification.get("version")
    if (kind not in SUPPORTED_VERSIONS or not isinstance(version, int) or isinstance(version, bool)
            or version != SUPPORTED_VERSIONS[kind]):
        raise TransportError("El tipo o la versión del DTE no es compatible con este conector.")
    generation = identification.get("codigoGeneracion")
    try:
        code = UUID(generation) if isinstance(generation, str) else None
    except (ValueError, AttributeError):
        code = None
    if code is None or code.version != 4 or str(code).upper() != generation:
        raise TransportError("El código de generación debe ser un UUID v4 en mayúsculas.")
    return identification


def _decode_segment(segment):
    if not isinstance(segment, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("Invalid base64url")
    return base64.b64decode(segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True)


def _same_json(left, right):
    """Compare JSON values without conflating booleans with 0 or 1."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, Decimal)) and isinstance(right, (int, Decimal)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def _verify_signed_payload(signed, payload):
    try:
        if not isinstance(signed, str) or len(signed) > MAX_RESPONSE_BYTES:
            raise ValueError("Invalid JWS")
        segments = signed.split(".")
        if len(segments) != 3:
            raise ValueError("Invalid JWS")
        header = _parse_json(_decode_segment(segments[0]))
        decoded = _parse_json(_decode_segment(segments[1]))
        signature = _decode_segment(segments[2])
        if (not isinstance(header, dict) or not isinstance(header.get("alg"), str)
                or not header["alg"] or header["alg"].lower() == "none" or not signature):
            raise ValueError("Unsigned JWS")
        expected = _parse_json(_json_body(payload))
        if not _same_json(decoded, expected):
            raise ValueError("Document changed")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise TransportError("La firma recibida no contiene exactamente el documento preparado.") from None
    return signed


def _safe_receipt(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for key in _RECEIPT_KEYS:
        item = value.get(key)
        if key not in value:
            continue
        if key == "observaciones":
            if item is None:
                result[key] = None
            elif isinstance(item, list):
                result[key] = [note[:2000] for note in item[:100] if isinstance(note, str)]
        elif item is None or isinstance(item, (int, bool)):
            result[key] = item
        elif isinstance(item, str):
            result[key] = item[:4000]
    return result or None


def classify_receipt(receipt, payload):
    """A matching seal proves test acceptance; HTTP 200 by itself does not."""
    identification = _identification(payload)
    if not isinstance(receipt, dict):
        return "unknown"
    # Even a rejection belonging to another identity cannot settle this send.
    if (receipt.get("codigoGeneracion") != identification["codigoGeneracion"]
            or receipt.get("ambiente") != identification["ambiente"]):
        return "unknown"
    if receipt.get("estado") == "PROCESADO":
        seal = receipt.get("selloRecibido")
        if isinstance(seal, str) and seal.strip():
            return "accepted"
    if receipt.get("estado") == "RECHAZADO" and not receipt.get("selloRecibido"):
        return "rejected"
    return "unknown"


def qr_url(payload):
    identification = _identification(payload)
    issue_date = identification.get("fecEmi")
    try:
        if not isinstance(issue_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", issue_date):
            raise ValueError("Invalid date")
        date.fromisoformat(issue_date)
    except ValueError:
        raise TransportError("La fecha de emisión no permite generar la consulta QR.")
    return "https://admin.factura.gob.sv/consultaPublica?" + urlencode({
        "ambiente": identification["ambiente"],
        "codGen": identification["codigoGeneracion"], "fechaEmi": issue_date,
    })


class HaciendaClient:
    def __init__(self, config):
        self._user = config.get("DTE_API_USER") or ""
        self._password = config.get("DTE_API_PASSWORD") or ""
        self._signer_password = config.get("DTE_SIGNER_PASSWORD") or ""
        self._signer_url = config.get("DTE_SIGNER_URL") or DEFAULT_SIGNER_URL
        if config.get("DTE_ENVIRONMENT", "00") != "00":
            raise TransportError("Este conector permite únicamente el ambiente de pruebas 00.")
        try:
            self.timeout = float(config.get("DTE_TIMEOUT_SECONDS", 8))
        except (TypeError, ValueError):
            raise TransportError("El tiempo de espera DTE debe ser válido.") from None
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 8:
            raise TransportError("El tiempo de espera DTE debe estar entre 0 y 8 segundos.")
        self._validate_signer_url()
        # Default urllib handlers retain the configured proxy and TLS CA trust.
        self._opener = build_opener(_NoRedirect())

    def _validate_signer_url(self):
        try:
            parsed = urlsplit(self._signer_url)
            hostname = parsed.hostname
            port = parsed.port
            if (parsed.scheme not in {"http", "https"} or not hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or not parsed.path
                    or (port is not None and not 0 < port <= 65535)
                    or any(c.isspace() for c in self._signer_url)):
                raise ValueError("Invalid signer URL")
            if hostname.lower().rstrip(".") in {"metadata.google.internal", "metadata", "instance-data"}:
                raise ValueError("Metadata address")
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                address = None
            if address is not None and (address.is_link_local or address.is_unspecified or address.is_multicast
                                        or (getattr(address, "ipv4_mapped", None) is not None
                                            and address.ipv4_mapped.is_link_local)):
                raise ValueError("Metadata or invalid address")
        except (TypeError, ValueError):
            raise TransportError("Configura una URL válida y confiable para el firmador.") from None

    def _post(self, url, body, content_type, token=None, ambiguous=False, capture_receipt=False):
        headers = {"Content-Type": content_type, "User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = token
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise TransportError("La respuesta del servicio DTE excede el límite permitido.", ambiguous=ambiguous)
            parsed = _parse_json(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Invalid response")
            return parsed
        except HTTPError as error:
            receipt = None
            try:
                raw = error.read(MAX_RESPONSE_BYTES + 1)
                if capture_receipt and len(raw) <= MAX_RESPONSE_BYTES:
                    receipt = _safe_receipt(_parse_json(raw))
            except (OSError, HTTPException, ValueError, TypeError, UnicodeError, RecursionError):
                pass
            finally:
                error.close()
            raise TransportError("El servicio DTE rechazó la solicitud HTTP.",
                                 ambiguous=ambiguous, receipt=receipt) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise TransportError("No fue posible obtener respuesta del servicio DTE.", ambiguous=ambiguous) from None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise TransportError("El servicio DTE devolvió una respuesta inválida.", ambiguous=ambiguous) from None

    def authenticate(self):
        if not isinstance(self._user, str) or not isinstance(self._password, str) or not self._user or not self._password:
            raise TransportError("Faltan las credenciales del ambiente de pruebas de Hacienda.")
        key = hashlib.sha256(_json_body([SANDBOX_BASE, self._user, self._password])).hexdigest()
        now = time.time()
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(key)
            if cached is not None and cached[1] > now + 30:
                return cached[0]
            _TOKEN_CACHE.pop(key, None)
        # No automatic retry: repeated credential failures can block the account.
        response = self._post(SANDBOX_BASE + "/seguridad/auth",
                              urlencode({"user": self._user, "pwd": self._password}).encode("utf-8"),
                              "application/x-www-form-urlencoded")
        token = response.get("body", {}).get("token") if isinstance(response.get("body"), dict) else None
        if response.get("status") != "OK" or not isinstance(token, str):
            raise TransportError("Hacienda no autorizó las credenciales de pruebas.")
        token = token.strip()
        while token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token or re.search(r"\s", token) or len(token) > 32768:
            raise TransportError("Hacienda devolvió un token de acceso inválido.")
        expiry = now + 24 * 60 * 60  # Conservative daily cache; sandbox manual permits 48h.
        try:
            claims = _parse_json(_decode_segment(token.split(".")[1]))
            hint = claims.get("exp") if isinstance(claims, dict) else None
            if isinstance(hint, (int, Decimal)) and not isinstance(hint, bool):
                expiry = min(expiry, float(hint))
        except (ValueError, IndexError, UnicodeError, OverflowError):
            pass
        if expiry <= now + 30:
            raise TransportError("Hacienda devolvió un token vencido o próximo a vencer.")
        authorized = "Bearer " + token
        with _TOKEN_LOCK:
            for old_key in list(_TOKEN_CACHE):
                if _TOKEN_CACHE[old_key][1] <= now:
                    _TOKEN_CACHE.pop(old_key, None)
            if len(_TOKEN_CACHE) >= 64:
                _TOKEN_CACHE.pop(next(iter(_TOKEN_CACHE)))
            _TOKEN_CACHE[key] = (authorized, expiry)
        return authorized

    def sign(self, payload):
        _identification(payload)
        nit = payload.get("emisor", {}).get("nit") if isinstance(payload.get("emisor"), dict) else None
        if not isinstance(nit, str) or not re.fullmatch(r"(?:[0-9]{9}|[0-9]{14})", nit):
            raise TransportError("El NIT del emisor no es válido para el firmador.")
        if not isinstance(self._signer_password, str) or not self._signer_password:
            raise TransportError("Falta la contraseña de la clave privada del firmador de pruebas.")
        response = self._post(self._signer_url, _json_body({
            "nit": nit, "activo": True, "passwordPri": self._signer_password, "dteJson": payload,
        }), "application/json")
        if response.get("status") != "OK":
            raise TransportError("El firmador no pudo firmar el documento de pruebas.")
        return _verify_signed_payload(response.get("body"), payload)

    def send(self, payload, signed, id_envio):
        identification = _identification(payload)
        if isinstance(id_envio, bool) or not isinstance(id_envio, int) or id_envio <= 0:
            raise TransportError("El identificador del envío debe ser un entero positivo.")
        _verify_signed_payload(signed, payload)
        body = _json_body({
            "ambiente": identification["ambiente"], "idEnvio": id_envio,
            "version": identification["version"], "tipoDte": identification["tipoDte"],
            "documento": signed, "codigoGeneracion": identification["codigoGeneracion"],
        })
        token = self.authenticate()
        try:
            response = self._post(SANDBOX_BASE + "/fesv/recepciondte", body, "application/json",
                                  token=token, ambiguous=True, capture_receipt=True)
        except TransportError as error:
            if error.receipt and classify_receipt(error.receipt, payload) in {"accepted", "rejected"}:
                return error.receipt
            raise
        return _safe_receipt(response) or {}

    def consult(self, payload):
        identification = _identification(payload)
        nit = payload.get("emisor", {}).get("nit") if isinstance(payload.get("emisor"), dict) else None
        if not isinstance(nit, str) or not re.fullmatch(r"(?:[0-9]{9}|[0-9]{14})", nit):
            raise TransportError("El NIT del emisor no es válido para la consulta.")
        body = _json_body({"nitEmisor": nit, "tdte": identification["tipoDte"],
                           "codigoGeneracion": identification["codigoGeneracion"]})
        token = self.authenticate()
        try:
            response = self._post(SANDBOX_BASE + "/fesv/recepcion/consultadte", body,
                                  "application/json", token=token, capture_receipt=True)
        except TransportError as error:
            # A query error (including "record does not exist") is not permission
            # to resend. The caller keeps it unresolved and offers another query.
            if error.receipt:
                return error.receipt
            raise
        return _safe_receipt(response) or {}
