"""HTTP contracts from the supplied manual, with no network connections."""

import base64
from copy import deepcopy
from decimal import Decimal
from http.client import IncompleteRead
from io import BytesIO
import json
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from app.billing import decimal_json
from app.dte_transport import (
    DEFAULT_SIGNER_URL, HaciendaClient, MAX_RESPONSE_BYTES, SANDBOX_BASE,
    TransportError, _TOKEN_CACHE, classify_receipt, qr_url,
)


GENERATION = "391E6EA4-9727-416F-A38A-08270F94B0B6"


def payload(kind="01"):
    return {
        "identificacion": {"ambiente": "00", "tipoDte": kind, "version": 2 if kind == "01" else 4,
                           "codigoGeneracion": GENERATION, "fecEmi": "2026-10-09"},
        "emisor": {"nit": "06140000000000"},
        "resumen": {"totalPagar": Decimal("22.60"), "totalIva": Decimal("2.60")},
    }


def segment(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def jws(document, header=None):
    # Synthetic signature bytes: not a valid signature/certificate.
    return ".".join((segment(json.dumps(header or {"alg": "RS256"}).encode()),
                     segment(decimal_json(document).encode("utf-8")), segment(b"synthetic-signature")))


def receipt(**extra):
    result = {"estado": "PROCESADO", "ambiente": "00", "codigoGeneracion": GENERATION,
              "selloRecibido": "A-SYNTHETIC-TEST-SEAL-NOT-VALID", "codigoMsg": "001", "observaciones": []}
    result.update(extra)
    return result


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, bytes):
            return BytesIO(response)
        return BytesIO(decimal_json(response).encode("utf-8"))


class TransportContractTests(unittest.TestCase):
    def setUp(self):
        _TOKEN_CACHE.clear()
        self.config = {"DTE_API_USER": "synthetic-user", "DTE_API_PASSWORD": "synthetic-password",
                       "DTE_SIGNER_PASSWORD": "synthetic-private-key-password", "DTE_TIMEOUT_SECONDS": 8}

    def client(self, *responses, **config):
        opener = FakeOpener(responses)
        with patch("app.dte_transport.build_opener", return_value=opener):
            client = HaciendaClient(dict(self.config, **config))
        return client, opener

    def auth(self, token="Bearer synthetic-token"):
        return {"status": "OK", "body": {"token": token}}

    def test_auth_form_and_cached_bearer_without_duplicate_prefix(self):
        client, opener = self.client(self.auth("Bearer Bearer synthetic-token"))
        self.assertEqual(client.authenticate(), "Bearer synthetic-token")
        self.assertEqual(client.authenticate(), "Bearer synthetic-token")
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, SANDBOX_BASE + "/seguridad/auth")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parse_qs(request.data.decode()), {"user": ["synthetic-user"], "pwd": ["synthetic-password"]})
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        self.assertIn("Restobar", request.get_header("User-agent"))
        self.assertEqual(timeout, 8)
        other, other_opener = self.client()
        self.assertEqual(other.authenticate(), "Bearer synthetic-token")
        self.assertFalse(other_opener.requests)

    def test_controlled_auth_failure_is_sanitized_and_never_retried(self):
        client, opener = self.client({"status": "ERROR", "message": "synthetic-password"})
        with self.assertRaises(TransportError) as caught:
            client.authenticate()
        self.assertNotIn("synthetic-password", str(caught.exception))
        self.assertFalse(caught.exception.ambiguous)
        self.assertIsNone(caught.exception.receipt)
        self.assertEqual(len(opener.requests), 1)
        self.assertFalse(_TOKEN_CACHE)

    def test_expired_token_and_header_injection_are_refused(self):
        jwt = ".".join((segment(b'{"alg":"RS256"}'), segment(json.dumps({"exp": time.time() - 1}).encode()), segment(b"x")))
        for token in (jwt, "Bearer token\r\nAuthorization: evil"):
            client, opener = self.client(self.auth(token))
            with self.assertRaises(TransportError):
                client.authenticate()
            self.assertEqual(len(opener.requests), 1)

    def test_signer_contract_preserves_exact_decimal_json_and_original_object(self):
        document = payload()
        signed = jws(document)
        client, opener = self.client({"status": "OK", "body": signed})
        self.assertEqual(client.sign(document), signed)
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, DEFAULT_SIGNER_URL)
        sent = json.loads(request.data, parse_float=Decimal)
        self.assertEqual(sent["nit"], document["emisor"]["nit"])
        self.assertIs(sent["activo"], True)
        self.assertEqual(sent["passwordPri"], "synthetic-private-key-password")
        self.assertIsInstance(sent["dteJson"], dict)
        self.assertEqual(sent["dteJson"]["resumen"]["totalPagar"], Decimal("22.60"))
        self.assertIn(b'"totalPagar":22.60', request.data)

    def test_nine_digit_emitter_nit_is_preserved_for_signer_and_query(self):
        document = payload()
        document["emisor"]["nit"] = "123456789"
        client, opener = self.client({"status": "OK", "body": jws(document)}, self.auth(), receipt())
        self.assertEqual(client.sign(document), jws(document))
        self.assertEqual(client.consult(document)["estado"], "PROCESADO")
        self.assertEqual(json.loads(opener.requests[0][0].data)["nit"], "123456789")
        self.assertEqual(json.loads(opener.requests[2][0].data)["nitEmisor"], "123456789")

    def test_mismatched_or_unsigned_jws_cannot_be_sent(self):
        altered = deepcopy(payload())
        altered["resumen"]["totalPagar"] = Decimal("22.61")
        for signed in (jws(altered), jws(payload(), {"alg": "none"}), "not-a-jws"):
            client, opener = self.client()
            with self.assertRaises(TransportError):
                client.send(payload(), signed, 1)
            self.assertFalse(opener.requests)

    def test_signer_mismatch_error_does_not_expose_response(self):
        altered = payload()
        altered["emisor"]["nit"] = "06149999999999"
        client, opener = self.client({"status": "OK", "body": jws(altered)})
        with self.assertRaises(TransportError) as caught:
            client.sign(payload())
        self.assertFalse(caught.exception.ambiguous)
        self.assertNotIn("06149999999999", str(caught.exception))
        self.assertEqual(len(opener.requests), 1)

    def test_send_uses_signed_document_identity_and_integer_id(self):
        document = payload("03")
        signed = jws(document)
        client, opener = self.client(self.auth(), receipt())
        accepted = client.send(document, signed, 7)
        self.assertEqual(classify_receipt(accepted, document), "accepted")
        request, _ = opener.requests[1]
        self.assertEqual(request.full_url, SANDBOX_BASE + "/fesv/recepciondte")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
        self.assertEqual(json.loads(request.data), {"ambiente": "00", "idEnvio": 7, "version": 4,
                                                   "tipoDte": "03", "documento": signed, "codigoGeneracion": GENERATION})

    def test_send_timeout_is_ambiguous_without_any_automatic_resend(self):
        client, opener = self.client(self.auth(), TimeoutError("contains-irrelevant-sensitive-detail"))
        with self.assertRaises(TransportError) as caught:
            client.send(payload(), jws(payload()), 1)
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn("sensitive-detail", str(caught.exception))
        self.assertEqual(len(opener.requests), 2)

    def test_incomplete_http_response_also_requires_query_before_retry(self):
        client, opener = self.client(self.auth(), IncompleteRead(b"partial-receipt", 100))
        with self.assertRaises(TransportError) as caught:
            client.send(payload(), jws(payload()), 1)
        self.assertTrue(caught.exception.ambiguous)
        self.assertEqual(len(opener.requests), 2)

    def test_auth_timeout_before_submission_is_not_ambiguous(self):
        client, opener = self.client(URLError("synthetic-password"))
        with self.assertRaises(TransportError) as caught:
            client.send(payload(), jws(payload()), 1)
        self.assertFalse(caught.exception.ambiguous)
        self.assertEqual(len(opener.requests), 1)

    def test_http_controlled_rejection_is_returned_with_identity(self):
        rejected = receipt(estado="RECHAZADO", selloRecibido=None, codigoMsg="098", descripcionMsg="JSON no conforme")
        error = HTTPError(SANDBOX_BASE, 400, "Bad Request", {}, BytesIO(json.dumps(rejected).encode()))
        client, opener = self.client(self.auth(), error)
        result = client.send(payload(), jws(payload()), 1)
        self.assertEqual(classify_receipt(result, payload()), "rejected")
        self.assertEqual(result["codigoMsg"], "098")
        self.assertEqual(len(opener.requests), 2)

    def test_http_error_with_no_final_receipt_keeps_send_ambiguous(self):
        error = HTTPError(SANDBOX_BASE, 503, "Unavailable", {}, BytesIO(b'{"message":"synthetic-password"}'))
        client, opener = self.client(self.auth(), error)
        with self.assertRaises(TransportError) as caught:
            client.send(payload(), jws(payload()), 1)
        self.assertTrue(caught.exception.ambiguous)
        self.assertIsNone(caught.exception.receipt)
        self.assertNotIn("synthetic-password", str(caught.exception))
        self.assertEqual(len(opener.requests), 2)

    def test_query_uses_tdte_and_root_receipt_and_never_sends_again(self):
        client, opener = self.client(self.auth(), receipt(codigoMsg="002", observaciones=["Advertencia sintética"]))
        result = client.consult(payload())
        self.assertEqual(classify_receipt(result, payload()), "accepted")
        self.assertEqual(result["observaciones"], ["Advertencia sintética"])
        request, _ = opener.requests[1]
        self.assertEqual(request.full_url, SANDBOX_BASE + "/fesv/recepcion/consultadte")
        self.assertEqual(json.loads(request.data), {"nitEmisor": "06140000000000", "tdte": "01", "codigoGeneracion": GENERATION})
        self.assertEqual(len(opener.requests), 2)

    def test_query_failure_is_not_ambiguous_and_missing_record_is_not_acceptance(self):
        client, opener = self.client(self.auth(), URLError("synthetic-private-key-password"))
        with self.assertRaises(TransportError) as caught:
            client.consult(payload())
        self.assertFalse(caught.exception.ambiguous)
        self.assertNotIn("synthetic-private-key-password", str(caught.exception))
        self.assertEqual(classify_receipt({"estado": "RECHAZADO", "codigoMsg": "014"}, payload()), "unknown")

    def test_receipt_requires_matching_generation_environment_and_nonempty_seal(self):
        self.assertEqual(classify_receipt(receipt(codigoMsg="002"), payload()), "accepted")
        for result in ({"status": "OK"}, {"body": receipt()}, receipt(selloRecibido="  "),
                       receipt(selloRecibido=None), receipt(ambiente="01"),
                       receipt(codigoGeneracion="4D6C14C2-B775-4C15-900A-D62629EA0FC4")):
            self.assertEqual(classify_receipt(result, payload()), "unknown", result)

    def test_unsupported_version_wrong_uuid_and_production_refused_before_network(self):
        for field, value in (("ambiente", "01"), ("version", 1), ("version", True), ("version", 2.0),
                             ("codigoGeneracion", GENERATION.lower()),
                             ("codigoGeneracion", "391E6EA4-9727-116F-A38A-08270F94B0B6")):
            document = payload()
            document["identificacion"][field] = value
            client, opener = self.client()
            with self.assertRaises(TransportError):
                client.send(document, jws(document), 1)
            self.assertFalse(opener.requests)
        with self.assertRaises(TransportError):
            self.client(DTE_ENVIRONMENT="01")

    def test_invalid_id_or_missing_credentials_do_not_connect(self):
        for identifier in (True, "1", 0, -1):
            client, opener = self.client()
            with self.assertRaises(TransportError):
                client.send(payload(), jws(payload()), identifier)
            self.assertFalse(opener.requests)
        client, opener = self.client(DTE_API_PASSWORD="", DTE_SIGNER_PASSWORD="")
        for operation in (client.authenticate, lambda: client.sign(payload())):
            with self.assertRaises(TransportError):
                operation()
        self.assertFalse(opener.requests)

    def test_signer_url_rejects_credentials_metadata_and_redirects_use_custom_handler(self):
        for url in ("http://user:secret@localhost:8113/firmardocumento/", "http://169.254.169.254/latest/meta-data/",
                    "http://[::ffff:169.254.169.254]/latest/meta-data/",
                    "http://[fe80::1]/firmardocumento/", "http://metadata.google.internal/", "file:///tmp/signer",
                    "http://localhost:8113/firmardocumento/?password=secret", "http://localhost:bad/sign"):
            with self.assertRaises(TransportError):
                self.client(DTE_SIGNER_URL=url)
        with patch("app.dte_transport.build_opener", return_value=FakeOpener([])) as builder:
            HaciendaClient(self.config)
        handler = builder.call_args.args[0]
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://unexpected.example"))

    def test_oversized_or_invalid_send_response_stays_ambiguous(self):
        for body in (b"x" * (MAX_RESPONSE_BYTES + 1), b"not-json", b'{"estado":"PROCESADO","estado":"RECHAZADO"}'):
            _TOKEN_CACHE.clear()
            client, opener = self.client(self.auth(), body)
            with self.assertRaises(TransportError) as caught:
                client.send(payload(), jws(payload()), 1)
            self.assertTrue(caught.exception.ambiguous)
            self.assertEqual(len(opener.requests), 2)

    def test_qr_contract_uses_original_issue_date_and_test_environment(self):
        parsed = urlsplit(qr_url(payload()))
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "admin.factura.gob.sv")
        self.assertEqual(parsed.path, "/consultaPublica")
        self.assertEqual(parse_qs(parsed.query), {"ambiente": ["00"], "codGen": [GENERATION], "fechaEmi": ["2026-10-09"]})
        document = payload()
        document["identificacion"]["fecEmi"] = "2026-02-29"
        with self.assertRaises(TransportError):
            qr_url(document)


if __name__ == "__main__":
    unittest.main()
