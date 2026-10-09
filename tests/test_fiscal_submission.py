"""Sandbox submission workflow with synthetic data and zero external requests.

Every HaciendaClient construction is intercepted. The signer JWS fixture has a
synthetic signature; transport-level identity verification is tested separately.
"""

import base64
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from unittest.mock import Mock, patch
from uuid import uuid4

from sqlalchemy import update

from app.billing import BillingError, decimal_json, prepare_document, verified_payload
from app.config import Config
from app.dte_transport import HaciendaClient, TransportError
from app.extensions import db
from app.fiscal import ACCEPTED
from app.models import DocumentoFiscal, FiscalEnvio, FiscalIntento, Orden, Rol, Usuario
from app.services import bootstrap_roles_permissions
from test_billing import BillingFixture


TEST_TRANSPORT_CONFIG = {
    "DTE_TRANSMISSION_ENABLED": False,
    "DTE_ENVIRONMENT": "00",
    "DTE_API_USER": "synthetic-sandbox-user",
    "DTE_API_PASSWORD": "synthetic-sandbox-password",
    "DTE_SIGNER_PASSWORD": "synthetic-signer-password",
    "DTE_SIGNER_URL": "http://127.0.0.1:8113/firmardocumento/",
}


def synthetic_jws(payload):
    def encoded(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    return ".".join((encoded(b'{"alg":"RS256"}'),
                     encoded(decimal_json(payload).encode("utf-8")),
                     encoded(b"synthetic-signature-for-offline-tests")))


class FiscalSubmissionWorkflowTests(BillingFixture):
    def setUp(self):
        with patch.multiple(Config, **TEST_TRANSPORT_CONFIG):
            super().setUp()
        self.app.config.update(TEST_TRANSPORT_CONFIG)
        self.app.config["DTE_TRANSMISSION_ENABLED"] = True
        self.remote = Mock(spec=HaciendaClient)
        patcher = patch("app.fiscal.HaciendaClient", return_value=self.remote)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            document, _ = prepare_document(order, self.recipient(), self.user_id)
            self.document_id = document.id
            self.original_bytes = document.documento_json
            self.original_hash = document.documento_sha256
            self.payload = verified_payload(document)
        self.signature = synthetic_jws(self.payload)
        self.remote.sign.return_value = self.signature
        self.remote.authenticate.return_value = "Bearer synthetic-offline-token"
        self.remote.send.return_value = self.receipt()
        self.remote.consult.return_value = self.receipt()
        self.assertEqual(self.login().status_code, 302)
        self.csrf_value = "synthetic-submission-csrf"
        with self.client.session_transaction() as stored:
            stored["billing_csrf"] = self.csrf_value

    def receipt(self, state="PROCESADO", **extra):
        receipt = {
            "version": 2, "ambiente": "00", "estado": state,
            "codigoGeneracion": self.payload["identificacion"]["codigoGeneracion"],
            "selloRecibido": "SYNTHETIC-MH-TEST-SEAL" if state == "PROCESADO" else None,
            "codigoMsg": "001" if state == "PROCESADO" else "021",
            "descripcionMsg": "Respuesta sintética; sin emisión real",
            "observaciones": [],
        }
        receipt.update(extra)
        return receipt

    def transmit(self, **extra):
        form = {"billing_csrf": self.csrf_value, "confirmar_prueba": "1"}
        form.update(extra)
        return self.client.post(f"/facturacion/{self.document_id}/transmitir-prueba", data=form)

    def consult(self):
        return self.client.post(f"/facturacion/{self.document_id}/consultar-prueba",
                                data={"billing_csrf": self.csrf_value})

    def evidence(self, state=None, count=None):
        with self.app.app_context():
            document = db.session.get(DocumentoFiscal, self.document_id)
            self.assertEqual(document.documento_json, self.original_bytes)
            self.assertEqual(document.documento_sha256, self.original_hash)
            self.assertEqual(document.estado, "BORRADOR")
            envio = FiscalEnvio.query.filter_by(documento_id=document.id).one()
            if state is not None:
                self.assertEqual(envio.estado, state)
            if count is not None:
                self.assertEqual(envio.transmisiones, count)
            return {
                "id": envio.id, "state": envio.estado, "count": envio.transmisiones,
                "signature": envio.firma, "seal": envio.sello, "receipt": envio.respuesta_json,
                "lease": envio.ocupado_hasta,
                "attempts": [(attempt.etapa, attempt.resultado) for attempt in
                             FiscalIntento.query.filter_by(envio_id=envio.id).order_by(FiscalIntento.id).all()],
            }

    def seed_evidence(self, state, count, lease):
        with self.app.app_context():
            db.session.add(FiscalEnvio(documento_id=self.document_id, estado=state,
                                      transmisiones=count, firma=self.signature,
                                      ocupado_hasta=lease))
            db.session.commit()

    def test_default_disabled_and_missing_configuration_never_construct_a_client(self):
        self.app.config["DTE_TRANSMISSION_ENABLED"] = False
        self.assertEqual(self.transmit().status_code, 302)
        self.factory.assert_not_called()
        with self.app.app_context():
            self.assertEqual(FiscalEnvio.query.count(), 0)
        self.app.config["DTE_TRANSMISSION_ENABLED"] = True
        self.app.config["DTE_API_PASSWORD"] = ""
        self.assertEqual(self.transmit().status_code, 302)
        self.factory.assert_not_called()
        with self.app.app_context():
            self.assertEqual(FiscalEnvio.query.count(), 0)

    def test_bootstrap_adds_transmission_to_admin_and_keeps_cashier_restricted(self):
        with self.app.app_context():
            admin = db.session.get(Rol, "administrador")
            admin.permisos = admin.permisos - {"facturacion.send_test"}
            db.session.commit()
            bootstrap_roles_permissions()
            self.assertIn("facturacion.send_test", admin.permisos)
            self.assertNotIn("facturacion.send_test", db.session.get(Rol, "cajero").permisos)

    def test_post_requires_csrf_confirmation_fresh_login_and_transmission_permission(self):
        path = f"/facturacion/{self.document_id}/transmitir-prueba"
        self.assertEqual(self.client.post(path, data={"confirmar_prueba": "1"}).status_code, 400)
        self.assertEqual(self.client.post(path, data={"billing_csrf": self.csrf_value}).status_code, 400)
        self.assertEqual(self.transmit(billing_csrf="wrong-token").status_code, 400)
        with self.client.session_transaction() as stored:
            stored["_fresh"] = False
        stale = self.transmit()
        self.assertEqual(stale.status_code, 302)
        self.assertIn("/login?next=", stale.location)
        self.factory.assert_not_called()
        self.client.post("/logout")
        with self.app.app_context():
            user = Usuario(nickname="submission-test-cashier", nombre="Caja", apellido="Sintética", rol="cajero")
            user.set_password("billing-test-password")
            db.session.add(user)
            db.session.commit()
        self.login("submission-test-cashier")
        self.assertEqual(self.transmit().status_code, 403)
        self.assertEqual(self.consult().status_code, 403)
        self.factory.assert_not_called()

    def test_matching_sealed_acceptance_exports_evidence_without_changing_draft(self):
        download = f"/facturacion/{self.document_id}/recepcion-prueba.json"
        self.assertEqual(self.client.get(download).status_code, 409)
        self.remote.send.return_value = self.receipt(token="synthetic-unexpected-secret", password="synthetic-unexpected-password")
        self.assertEqual(self.transmit().status_code, 302)
        evidence = self.evidence(ACCEPTED, 1)
        self.assertNotIn("token", json.loads(evidence["receipt"]))
        self.assertNotIn("password", json.loads(evidence["receipt"]))
        self.assertEqual(evidence["signature"], self.signature)
        self.assertEqual(evidence["seal"], "SYNTHETIC-MH-TEST-SEAL")
        self.assertIsNone(evidence["lease"])
        self.remote.sign.assert_called_once_with(self.payload)
        self.remote.authenticate.assert_called_once_with()
        self.remote.send.assert_called_once_with(self.payload, self.signature, evidence["id"])
        self.remote.consult.assert_not_called()
        result = self.client.get(download)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertIn("DTE-PRUEBA", result.headers["Content-Disposition"])
        exported = json.loads(result.data, parse_float=Decimal)
        self.assertEqual(exported.pop("firmaElectronica"), self.signature)
        self.assertEqual(exported.pop("selloRecibido"), evidence["seal"])
        self.assertEqual(exported, self.payload)
        self.evidence(ACCEPTED, 1)

    def test_repeated_accepted_clicks_never_sign_send_or_query_again(self):
        self.assertEqual(self.transmit().status_code, 302)
        self.assertEqual(self.transmit().status_code, 302)
        self.assertEqual(self.consult().status_code, 302)
        self.evidence(ACCEPTED, 1)
        self.factory.assert_called_once()
        self.remote.sign.assert_called_once()
        self.remote.send.assert_called_once()
        self.remote.consult.assert_not_called()

    def test_rejected_document_is_preserved_and_later_actions_only_query(self):
        rejected = self.receipt("RECHAZADO", observaciones=["Dato sintético rechazado"])
        self.remote.send.return_value = rejected
        self.remote.consult.return_value = rejected
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence("RECHAZADO", 1)
        self.assertEqual(self.client.get(f"/facturacion/{self.document_id}/recepcion-prueba.json").status_code, 409)
        self.assertEqual(self.transmit().status_code, 302)
        evidence = self.evidence("RECHAZADO", 1)
        self.assertEqual(json.loads(evidence["receipt"])["observaciones"], rejected["observaciones"])
        self.remote.sign.assert_called_once()
        self.remote.send.assert_called_once()
        self.remote.consult.assert_called_once_with(self.payload)

    def test_send_timeout_reconciles_by_query_without_automatic_resend(self):
        self.remote.send.side_effect = TransportError("Timeout sintético", ambiguous=True)
        self.assertEqual(self.transmit().status_code, 302)
        evidence = self.evidence(ACCEPTED, 1)
        self.assertIn(("envio", "ENVIO_INCIERTO"), evidence["attempts"])
        self.assertIn(("consulta", ACCEPTED), evidence["attempts"])
        self.remote.send.assert_called_once()
        self.remote.consult.assert_called_once_with(self.payload)
        self.assertEqual(self.transmit().status_code, 302)
        self.remote.send.assert_called_once()
        self.remote.consult.assert_called_once()

    def test_unknown_response_and_later_transmit_click_only_consult(self):
        self.remote.send.return_value = {"estado": "PROCESADO"}
        self.remote.consult.side_effect = [{}, self.receipt()]
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence("ENVIO_INCIERTO", 1)
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence(ACCEPTED, 1)
        self.remote.sign.assert_called_once()
        self.remote.send.assert_called_once()
        self.assertEqual(self.remote.consult.call_count, 2)

    def test_query_timeout_retains_uncertain_state_and_next_click_still_only_queries(self):
        self.remote.send.side_effect = TransportError("Recepción sin respuesta", ambiguous=True)
        self.remote.consult.side_effect = [TransportError("Consulta sin respuesta"), self.receipt()]
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence("ENVIO_INCIERTO", 1)
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence(ACCEPTED, 1)
        self.remote.send.assert_called_once()
        self.assertEqual(self.remote.consult.call_count, 2)

    def test_expired_sending_lease_recovers_by_query_without_resigning_or_resending(self):
        self.seed_evidence("ENVIANDO", 1, datetime.utcnow() - timedelta(seconds=1))
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence(ACCEPTED, 1)
        self.remote.sign.assert_not_called()
        self.remote.authenticate.assert_not_called()
        self.remote.send.assert_not_called()
        self.remote.consult.assert_called_once_with(self.payload)

    def test_active_lease_prevents_a_parallel_action_before_client_construction(self):
        lease = datetime.utcnow() + timedelta(seconds=120)
        self.seed_evidence("ENVIANDO", 1, lease)
        self.assertEqual(self.transmit().status_code, 302)
        evidence = self.evidence("ENVIANDO", 1)
        self.assertEqual(evidence["lease"], lease)
        self.factory.assert_not_called()
        self.assertEqual(self.consult().status_code, 302)
        self.factory.assert_not_called()

    def test_auth_failure_is_local_and_explicit_retry_reuses_the_original_signature(self):
        self.remote.authenticate.side_effect = [TransportError("Autenticación sintética fallida"), "Bearer synthetic-offline-token"]
        self.assertEqual(self.transmit().status_code, 302)
        evidence = self.evidence("ERROR_LOCAL", 0)
        self.assertEqual(evidence["signature"], self.signature)
        self.remote.send.assert_not_called()
        self.remote.consult.assert_not_called()
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence(ACCEPTED, 1)
        self.remote.sign.assert_called_once_with(self.payload)
        self.assertEqual(self.remote.authenticate.call_count, 2)
        self.remote.send.assert_called_once()
        self.remote.consult.assert_not_called()

    def test_client_configuration_failure_releases_lease_and_can_be_retried_explicitly(self):
        self.factory.side_effect = TransportError("URL del firmador sintética inválida")
        self.assertEqual(self.transmit().status_code, 302)
        evidence = self.evidence("ERROR_LOCAL", 0)
        self.assertIsNone(evidence["lease"])
        self.assertIsNone(evidence["signature"])
        self.assertIn(("configuracion", "ERROR_LOCAL"), evidence["attempts"])
        self.remote.sign.assert_not_called()
        self.remote.send.assert_not_called()
        self.remote.consult.assert_not_called()
        self.factory.side_effect = None
        self.assertEqual(self.transmit().status_code, 302)
        self.evidence(ACCEPTED, 1)
        self.remote.sign.assert_called_once()
        self.remote.send.assert_called_once()

    def test_confirmed_seal_and_transmission_evidence_cannot_be_changed_or_deleted(self):
        self.assertEqual(self.transmit().status_code, 302)
        with self.app.app_context():
            envio = FiscalEnvio.query.filter_by(documento_id=self.document_id).one()
            envio.sello = "ALTERED-SYNTHETIC-SEAL"
            with self.assertRaises(BillingError):
                db.session.commit()
            db.session.rollback()
            envio = FiscalEnvio.query.filter_by(documento_id=self.document_id).one()
            self.assertEqual(envio.sello, "SYNTHETIC-MH-TEST-SEAL")
            db.session.delete(envio)
            with self.assertRaises(BillingError):
                db.session.commit()
            db.session.rollback()
        self.evidence(ACCEPTED, 1)

    def test_receipt_must_match_generation_environment_and_include_a_seal(self):
        variants = [self.receipt(codigoGeneracion=str(uuid4()).upper()),
                    self.receipt(ambiente="01"), self.receipt(selloRecibido="")]
        for receipt in variants:
            with self.subTest(receipt=receipt):
                with self.app.app_context():
                    # Isolate each variant as a fresh operation on the same
                    # immutable document; evidence cleanup is limited to the
                    # synthetic test database, never the actual application.
                    FiscalIntento.query.delete()
                    FiscalEnvio.query.delete()
                    db.session.commit()
                self.remote.reset_mock()
                self.remote.send.return_value = receipt
                self.remote.consult.return_value = receipt
                self.assertEqual(self.transmit().status_code, 302)
                self.evidence("ENVIO_INCIERTO", 1)
                self.assertEqual(self.client.get(f"/facturacion/{self.document_id}/recepcion-prueba.json").status_code, 409)
                self.remote.send.assert_called_once()
                self.remote.consult.assert_called_once()

    def test_production_legacy_and_corrupted_snapshots_are_blocked_before_signing(self):
        for variant in ("production_config", "production_document", "legacy", "corruption"):
            with self.subTest(variant=variant):
                self.app.config["DTE_ENVIRONMENT"] = "01" if variant == "production_config" else "00"
                changed = self.original_bytes
                digest = self.original_hash
                if variant == "legacy":
                    payload = json.loads(changed, parse_float=Decimal)
                    payload["identificacion"]["version"] = 1
                    changed = decimal_json(payload)
                    digest = hashlib.sha256(changed.encode("utf-8")).hexdigest()
                elif variant == "corruption":
                    changed += " "  # Same parsed JSON, failed integrity hash.
                with self.app.app_context():
                    db.session.execute(update(DocumentoFiscal).where(DocumentoFiscal.id == self.document_id).values(
                        ambiente="01" if variant == "production_document" else "00",
                        documento_json=changed, documento_sha256=digest))
                    db.session.commit()
                self.assertEqual(self.transmit().status_code, 302)
                self.factory.assert_not_called()
                with self.app.app_context():
                    self.assertEqual(FiscalEnvio.query.count(), 0)
        self.remote.sign.assert_not_called()
        self.remote.send.assert_not_called()

    def test_attempt_history_cannot_be_rewritten_after_acceptance(self):
        self.assertEqual(self.transmit().status_code, 302)
        with self.app.app_context():
            attempt = FiscalIntento.query.first()
            attempt.mensaje = "Mensaje alterado"
            with self.assertRaises(BillingError):
                db.session.commit()
            db.session.rollback()
            attempt = FiscalIntento.query.first()
            db.session.delete(attempt)
            with self.assertRaises(BillingError):
                db.session.commit()
            db.session.rollback()
        self.evidence(ACCEPTED, 1)
