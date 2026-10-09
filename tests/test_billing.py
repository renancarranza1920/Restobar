"""Fiscal preparation tests use synthetic data and an isolated SQLite database.

The official schemas are bundled and verified offline.
The suite never connects to Hacienda or the configured application database.
"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app
from app.billing import BillingError, PROFILE_KEY, prepare_document, verified_payload, validate_current_payload, decimal_json, load_schema
from app.config import Config
from app.extensions import db
from app.models import Categoria, DocumentoFiscal, Mesa, Orden, OrdenItem, Pago, PreferenciaSistema, Producto, Rol, SesionCaja, Usuario


ROOT = Path(__file__).resolve().parent.parent
TEST_PROFILE = {
    "nit": "06140000000000", "nrc": "1234567", "nombre": "EMISOR SINTÉTICO DE PRUEBA",
    "nombreComercial": "Restaurante de prueba", "codActividad": "56101", "descActividad": "Actividad de prueba",
    "tipoEstablecimiento": "02", "departamento": "06", "municipio": "23", "distrito": "14",
    "complemento": "Dirección sintética, solo para pruebas", "telefono": "00000000", "correo": "fiscal@example.invalid",
    "codEstable": "M001", "codPuntoVenta": "P001", "codEstableMH": "", "codPuntoVentaMH": "",
    "precios_iva_incluido": True,
}


class BillingFixture(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix="restobar-billing-tests-")
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        with patch.multiple(Config, SQLALCHEMY_DATABASE_URI=f"sqlite:///{root / 'billing.sqlite3'}",
                            SECRET_KEY="isolated-billing-test-session", DEFAULT_ADMIN_NICKNAME="billing-test-admin",
                            DEFAULT_ADMIN_PASSWORD="billing-test-password", PRODUCT_UPLOAD_DIR=root / "products",
                            BRANDING_UPLOAD_DIR=root / "branding",
                            DTE_SCHEMA_PATH=None):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.addCleanup(self.close_database)
        with self.app.app_context():
            db.session.add(PreferenciaSistema(clave=PROFILE_KEY, valor=json.dumps(TEST_PROFILE)))
            user = Usuario.query.filter_by(nickname="billing-test-admin").one()
            self.user_id = user.id
            category = Categoria(nombre="Productos sintéticos")
            product = Producto(nombre="Pizza sintética de prueba", categoria=category, precio_venta=Decimal("11.30"))
            table = Mesa.query.filter_by(numero=999).one()
            cash = SesionCaja(usuario=user, monto_apertura=Decimal("0.00"), estado="cerrada")
            order = Orden(mesa=table, sesion_caja=cash, usuario=user, total=Decimal("22.60"), estado="pagada")
            order.items.append(OrdenItem(producto=product, cantidad=2, precio_unitario=Decimal("11.30"),
                                         estado="entregado", pagado=True))
            order.pagos.append(Pago(metodo="efectivo", monto=Decimal("22.60"), propina=Decimal("0.00")))
            db.session.add(order)
            db.session.commit()
            self.order_id = order.id
            self.product_id = product.id

    def close_database(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def login(self, nickname="billing-test-admin"):
        return self.client.post("/login", data={"nickname": nickname, "password": "billing-test-password"})

    def recipient(self, **extra):
        form = {"nombre": "Cliente sintético", "operacion_estandar": "1"}
        form.update(extra)
        return form

    def csrf(self):
        self.client.get(f"/facturacion/orden/{self.order_id}/preparar")
        with self.client.session_transaction() as stored:
            return stored["billing_csrf"]

    def prepare(self, **extra):
        return self.client.post(f"/facturacion/orden/{self.order_id}/preparar",
                                data=self.recipient(billing_csrf=self.csrf(), **extra))


class BillingWorkflowTests(BillingFixture):
    def test_paid_order_exports_valid_decimal_json_as_unsigned_test_draft(self):
        self.login()
        self.assertEqual(self.client.get("/facturacion/").status_code, 200)
        result = self.prepare()
        self.assertEqual(result.status_code, 302)
        with self.app.app_context():
            document = DocumentoFiscal.query.one()
            document_id = document.id
            payload = verified_payload(document)
            self.assertEqual(document.estado, "BORRADOR")
            self.assertEqual(payload["identificacion"]["ambiente"], "00")
            self.assertEqual(payload["identificacion"]["version"], 2)
            self.assertEqual(payload["resumen"]["totalPagar"], Decimal("22.60"))
            self.assertEqual(payload["resumen"]["totalIva"], Decimal("2.60"))
            self.assertEqual(payload["resumen"]["pagos"][0]["codigo"], "01")
            self.assertNotIn("selloRecibido", payload)
            self.assertNotIn("firma", payload)
            self.assertEqual(hashlib.sha256(document.documento_json.encode()).hexdigest(), document.documento_sha256)
        detail = self.client.get(result.location)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"BORRADOR SIN VALIDEZ TRIBUTARIA", detail.data)
        downloaded = self.client.get(f"/facturacion/{document_id}/borrador.json")
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("BORRADOR", downloaded.headers["Content-Disposition"])
        self.assertEqual(downloaded.headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(downloaded.data, parse_float=Decimal)["resumen"]["totalPagar"], Decimal("22.60"))

    def test_document_is_idempotent_and_snapshot_survives_product_changes(self):
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            first, created = prepare_document(order, self.recipient(), self.user_id)
            encoded = first.documento_json
            db.session.get(Producto, self.product_id).nombre = "Nombre posterior, nunca debe reemplazar el snapshot"
            db.session.commit()
            second, created_again = prepare_document(order, self.recipient(nombre="Otro cliente"), self.user_id)
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(first.id, second.id)
            self.assertEqual(encoded, second.documento_json)
            self.assertEqual(DocumentoFiscal.query.count(), 1)
            self.assertEqual(verified_payload(second)["cuerpoDocumento"][0]["descripcion"], "Pizza sintética de prueba")
            second.documento_json = "{}"
            with self.assertRaises(BillingError):
                db.session.commit()
            db.session.rollback()

    def test_csrf_and_fiscal_permissions_protect_posts_and_downloads(self):
        self.assertEqual(self.client.get("/facturacion/").status_code, 302)
        self.login()
        self.assertEqual(self.client.post(f"/facturacion/orden/{self.order_id}/preparar", data=self.recipient()).status_code, 400)
        self.assertEqual(self.client.post("/facturacion/perfil", data=TEST_PROFILE).status_code, 400)
        self.prepare()
        with self.app.app_context():
            document_id = DocumentoFiscal.query.one().id
            role = Rol(codigo="billing-test-limited", nombre="Solo sala")
            role.permisos = {"mesas.view"}
            user = Usuario(nickname="billing-test-limited", nombre="Usuario", apellido="Sintético", rol=role.codigo)
            user.set_password("billing-test-password")
            db.session.add_all([role, user])
            db.session.commit()
        self.client.post("/logout")
        self.login("billing-test-limited")
        for path in ("/facturacion/", "/facturacion/perfil", f"/facturacion/orden/{self.order_id}/preparar",
                     f"/facturacion/{document_id}", f"/facturacion/{document_id}/borrador.json"):
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_fe2_uses_current_recipient_policy_without_unverified_200_threshold(self):
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            order.total = Decimal("226.00")
            order.items[0].cantidad = 20
            order.pagos[0].monto = Decimal("226.00")
            db.session.commit()
            with self.assertRaises(BillingError):
                prepare_document(order, self.recipient(tipoDocumento="13", numDocumento="123"), self.user_id)
            db.session.rollback()
            doc, _ = prepare_document(order, self.recipient(), self.user_id)
            recipient = verified_payload(doc)["receptor"]
            self.assertIsNone(recipient["numDocumento"])
            self.assertEqual(set(recipient), set(load_schema()["properties"]["receptor"]["required"]))

    def test_incomplete_issuer_tip_unpaid_and_reconciliation_block_document(self):
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            stored = db.session.get(PreferenciaSistema, PROFILE_KEY)
            stored.valor = json.dumps({**TEST_PROFILE, "nit": ""})
            db.session.commit()
            with self.assertRaisesRegex(BillingError, "emisor"):
                prepare_document(order, self.recipient(), self.user_id)
            stored.valor = json.dumps(TEST_PROFILE)
            db.session.commit()
            for attribute, bad_value, expected in [("estado", "abierta", "pagadas"), ("total", Decimal("30.00"), "pagos")]:
                original = getattr(order, attribute)
                setattr(order, attribute, bad_value)
                with self.assertRaisesRegex(BillingError, expected):
                    prepare_document(order, self.recipient(), self.user_id)
                setattr(order, attribute, original)
            order.pagos[0].propina = Decimal("1.00")
            with self.assertRaisesRegex(BillingError, "propina"):
                prepare_document(order, self.recipient(), self.user_id)
            self.assertEqual(DocumentoFiscal.query.count(), 0)
            db.session.rollback()

    def test_cancelled_items_are_excluded_and_rounding_preserves_charged_total(self):
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            order.items.append(OrdenItem(producto_id=self.product_id, cantidad=1, precio_unitario=Decimal("5.00"), estado="cancelado", pagado=False))
            order.items.append(OrdenItem(producto_id=self.product_id, cantidad=1, precio_unitario=Decimal("0.05"), estado="entregado", pagado=True))
            order.total = Decimal("22.65")
            order.pagos[0].monto = Decimal("22.65")
            db.session.commit()
            doc, _ = prepare_document(order, self.recipient(), self.user_id)
            payload = verified_payload(doc)
            self.assertEqual(len(payload["cuerpoDocumento"]), 2)
            self.assertEqual(payload["resumen"]["totalIva"], Decimal("2.61"))
            self.assertEqual(payload["resumen"]["totalPagar"], Decimal("22.65"))
            self.assertEqual(sum(line["ventaGravada"] for line in payload["cuerpoDocumento"]), Decimal("22.65"))

    def test_current_schemas_allow_short_product_names_such_as_tea(self):
        with self.app.app_context():
            product = db.session.get(Producto, self.product_id)
            product.nombre = "Té"
            db.session.commit()
            document, _ = prepare_document(db.session.get(Orden, self.order_id), self.recipient(), self.user_id)
            self.assertEqual(verified_payload(document)["cuerpoDocumento"][0]["descripcion"], "Té")

    def test_generic_card_payment_requires_explicit_fiscal_subtype(self):
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            payment = order.pagos[0]
            payment.metodo = "tarjeta"
            db.session.commit()
            with self.assertRaisesRegex(BillingError, "tarjeta"):
                prepare_document(order, self.recipient(), self.user_id)
            doc, _ = prepare_document(order, self.recipient(**{f"tarjeta_codigo_{payment.id}": "02"}), self.user_id)
            self.assertEqual(verified_payload(doc)["resumen"]["pagos"][0]["codigo"], "02")
            self.assertEqual(json.loads(doc.snapshot_json)["payments"][0]["fiscal_payment_code"], "02")

    def test_missing_or_modified_reference_cannot_create_or_export(self):
        self.login()
        self.prepare()
        with self.app.app_context():
            document_id = DocumentoFiscal.query.one().id
        self.app.config["DTE_SCHEMA_PATH"] = "/tmp/restobar-schema-does-not-exist.json"
        self.assertEqual(self.client.get(f"/facturacion/{document_id}/borrador.json").status_code, 409)
        with TemporaryDirectory(prefix="restobar-schema-tests-") as directory:
            modified = Path(directory) / "schema.json"
            modified.write_text("{}")
            self.app.config["DTE_SCHEMA_PATH"] = str(modified)
            self.assertEqual(self.client.get(f"/facturacion/{document_id}/borrador.json").status_code, 409)

    def ccf_recipient(self, **extra):
        return self.recipient(tipo_dte="03", nit="06140000000000", nrc="7654321",
                              codActividad="56101", descActividad="Restaurantes de prueba",
                              departamento="06", municipio="23", distrito="14",
                              complemento="Dirección sintética del cliente", **extra)

    def test_ccf4_separates_net_base_and_vat_and_preserves_paid_total(self):
        self.login()
        with self.app.app_context():
            doc, _ = prepare_document(db.session.get(Orden, self.order_id), self.ccf_recipient(), self.user_id)
            payload = verified_payload(doc)
            validate_current_payload(payload)
            self.assertEqual(doc.tipo_dte, "03")
            self.assertEqual(payload["identificacion"]["version"], 4)
            self.assertTrue(payload["identificacion"]["numeroControl"].startswith("DTE-03-"))
            self.assertNotIn("totalIva", payload["resumen"])
            self.assertNotIn("ivaItem", payload["cuerpoDocumento"][0])
            self.assertEqual(payload["cuerpoDocumento"][0]["tributos"], ["20"])
            self.assertEqual(payload["cuerpoDocumento"][0]["precioUni"], Decimal("10.00000000"))
            self.assertEqual(payload["resumen"]["totalGravada"], Decimal("20.00"))
            self.assertEqual(payload["resumen"]["tributos"][0]["valor"], Decimal("2.60"))
            self.assertEqual(payload["resumen"]["totalPagar"], Decimal("22.60"))
            self.assertEqual(doc.iva, Decimal("2.60"))
            document_id = doc.id
        detail = self.client.get(f"/facturacion/{document_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Comprobante de Crédito Fiscal".encode(), detail.data)
        download = self.client.get(f"/facturacion/{document_id}/borrador.json")
        self.assertIn("DTE-03", download.headers["Content-Disposition"])

    def test_ccf_requires_tax_identity_and_complete_address(self):
        with self.app.app_context():
            order = db.session.get(Orden, self.order_id)
            for removed in ("nit", "nrc", "codActividad", "complemento", "distrito"):
                form = self.ccf_recipient()
                form[removed] = ""
                with self.subTest(field=removed), self.assertRaises(BillingError):
                    prepare_document(order, form, self.user_id)
                db.session.rollback()
            self.assertEqual(DocumentoFiscal.query.count(), 0)

    def test_legacy_snapshots_remain_viewable_downloadable_and_never_rewritten(self):
        self.login()
        with self.app.app_context():
            doc, _ = prepare_document(db.session.get(Orden, self.order_id), self.recipient(), self.user_id)
            payload = verified_payload(doc)
            payload["identificacion"]["version"] = 1
            encoded = decimal_json(payload)
            # Simulate an already stored legacy record; ORM updates remain forbidden.
            db.session.execute(db.text("UPDATE documentos_fiscales SET documento_json=:content, documento_sha256=:sha WHERE id=:id"),
                               {"content": encoded, "sha": hashlib.sha256(encoded.encode()).hexdigest(), "id": doc.id})
            db.session.commit()
            document_id = doc.id
            db.session.expire_all()
            legacy = db.session.get(DocumentoFiscal, document_id)
            with self.assertRaisesRegex(BillingError, "anterior"):
                validate_current_payload(verified_payload(legacy))
        detail = self.client.get(f"/facturacion/{document_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Snapshot legado", detail.data)
        download = self.client.get(f"/facturacion/{document_id}/borrador.json")
        self.assertEqual(download.status_code, 200)
        self.assertIn("LEGADO", download.headers["Content-Disposition"])
        self.assertEqual(download.data.decode().rstrip("\n"), encoded)

    def test_official_schemas_are_available_without_network_or_local_installation(self):
        with self.app.app_context():
            for kind, version in (("01", 2), ("03", 4), ("invalidacion", 3), ("contingencia", 4)):
                self.assertIsInstance(load_schema(kind), dict)
            with self.assertRaisesRegex(BillingError, "anterior"):
                load_schema("01", 1)

    def test_creator_with_only_fiscal_history_cannot_be_deleted(self):
        with self.app.app_context():
            creator = Usuario(nickname="billing-snapshot-creator", nombre="Creador", apellido="Sintético", rol="cajero")
            creator.set_password("billing-test-password")
            db.session.add(creator)
            db.session.commit()
            creator_id = creator.id
            document, _ = prepare_document(db.session.get(Orden, self.order_id), self.recipient(), creator_id)
            document_id = document.id
            self.assertFalse(creator.sesiones_caja)
            self.assertFalse(creator.ordenes)
            self.assertFalse(creator.movimientos_inventario)
        self.login()
        result = self.client.post(f"/usuarios/{creator_id}/eliminar")
        self.assertEqual(result.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Usuario, creator_id))
            self.assertEqual(db.session.get(DocumentoFiscal, document_id).usuario_id, creator_id)


if __name__ == "__main__":
    unittest.main()
