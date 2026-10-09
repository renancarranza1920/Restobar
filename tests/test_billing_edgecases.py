"""Fiscal boundary and concurrency regressions on disposable local databases.

Install the pinned reference with scripts/install_dte_reference.py before running
these tests. Its bytes are copied to a temporary location; no network requests or
production database connections are made by this suite.
"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from app import create_app
from app.billing import (
    BillingError,
    PROFILE_KEY,
    amount,
    issuer_from_profile,
    load_schema,
    prepare_document,
    recipient_from_form,
)
from app.config import Config
from app.extensions import db
from app.models import (
    Categoria,
    DocumentoFiscal,
    Orden,
    OrdenItem,
    Pago,
    PreferenciaSistema,
    Producto,
    Rol,
    SecuenciaBorradorDTE,
    SesionCaja,
    Usuario,
)


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "instance/dte-schemas/dte-fe-v1.json"


class FiscalBoundaryTests(unittest.TestCase):
    def setUp(self):
        if not REFERENCE_PATH.is_file():
            self.skipTest("Install the pinned DTE reference with scripts/install_dte_reference.py.")
        self.scratch = TemporaryDirectory(prefix="restobar-fiscal-boundaries-")
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.schema_path = root / "reference.json"
        self.schema_path.write_bytes(REFERENCE_PATH.read_bytes())
        with patch.multiple(
            Config,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{root / 'restaurant.sqlite3'}",
            SECRET_KEY="fiscal-boundary-test-session-only",
            DEFAULT_ADMIN_NICKNAME="boundary-admin",
            DEFAULT_ADMIN_PASSWORD="boundary-test-password",
            PRODUCT_UPLOAD_DIR=root / "products",
            BRANDING_UPLOAD_DIR=root / "branding",
            DTE_SCHEMA_PATH=str(self.schema_path),
        ):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.addCleanup(self.dispose_database)
        self.profile = {
            "nit": "06141212121012", "nrc": "1234567", "nombre": "RESTAURANTE DE PRUEBA",
            "nombreComercial": "Restobar Pruebas", "codActividad": "56101",
            "descActividad": "Restaurantes de prueba", "departamento": "06", "municipio": "14",
            "complemento": "Dirección de prueba local", "telefono": "22223333",
            "correo": "pruebas@example.com", "codEstable": "M001", "codPuntoVenta": "P001",
            "codEstableMH": "", "codPuntoVentaMH": "", "tipoEstablecimiento": "02",
            "precios_iva_incluido": True,
        }
        with self.app.app_context():
            admin = Usuario.query.filter_by(nickname="boundary-admin").one()
            self.admin_id = admin.id
            category = Categoria(nombre="Carta de prueba", envia_a_cocina=True)
            product = Producto(nombre="Pizza de prueba", categoria=category, precio_venta=Decimal("12.50"))
            cash = SesionCaja(usuario_id=admin.id, monto_apertura=Decimal("0.00"))
            db.session.add_all([
                product, cash,
                PreferenciaSistema(clave=PROFILE_KEY, valor=json.dumps(self.profile)),
            ])
            db.session.commit()
            self.product_id = product.id
            self.cash_id = cash.id

    def dispose_database(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def paid_order(self):
        with self.app.app_context():
            order = Orden(
                mesa_id=self.app.config["TAKEOUT_TABLE_ID"], sesion_caja_id=self.cash_id,
                usuario_id=self.admin_id, estado="pagada", total=Decimal("12.50"),
            )
            order.items.append(OrdenItem(
                producto_id=self.product_id, cantidad=1, precio_unitario=Decimal("12.50"),
                estado="entregado", pagado=True,
            ))
            order.pagos.append(Pago(metodo="efectivo", monto=Decimal("12.50"), propina=Decimal("0.00")))
            db.session.add(order)
            db.session.commit()
            return order.id

    def prepare(self, order_id):
        with self.app.app_context():
            document, created = prepare_document(
                db.session.get(Orden, order_id),
                {"nombre": "Cliente de prueba", "operacion_estandar": "1"}, self.admin_id,
            )
            return document.id, created

    def concurrently_prepare(self, order_ids):
        barrier = Barrier(len(order_ids))

        def worker(order_id):
            with self.app.app_context():
                order = db.session.get(Orden, order_id)
                # Both requests have read the order before attempting preparation.
                barrier.wait(timeout=10)
                try:
                    document, created = prepare_document(
                        order, {"nombre": "Cliente de prueba", "operacion_estandar": "1"}, self.admin_id,
                    )
                    return document.id, document.numero_control, created
                finally:
                    db.session.remove()

        with ThreadPoolExecutor(max_workers=len(order_ids)) as executor:
            return list(executor.map(worker, order_ids))

    def test_nonfinite_or_invalid_amounts_are_rejected_without_decimal_exceptions(self):
        for value in ("Infinity", "-Infinity", "NaN", "sNaN", "invalid", None, "1e999999"):
            with self.subTest(value=value), self.assertRaises(BillingError):
                amount(value)
        self.assertEqual(amount("1.005"), Decimal("1.01"))

    def test_address_codes_are_checked_beyond_the_reference_regex(self):
        with self.app.app_context():
            issuer_from_profile(self.profile)
            for department in ("invalid14", "01suffix", "00", "15"):
                with self.subTest(department=department), self.assertRaises(BillingError):
                    issuer_from_profile({**self.profile, "departamento": department})
                with self.subTest(recipient_department=department), self.assertRaises(BillingError):
                    recipient_from_form({
                        "nombre": "Cliente", "departamento": department,
                        "municipio": "01", "complemento": "Dirección de prueba",
                    }, Decimal("12.50"))

    def test_modified_reference_fails_integrity_after_initial_validation(self):
        with self.app.app_context():
            load_schema()
            initial_mtime = self.schema_path.stat().st_mtime_ns
            self.schema_path.write_bytes(self.schema_path.read_bytes() + b"\n")
            os.utime(self.schema_path, ns=(initial_mtime + 1_000_000, initial_mtime + 1_000_000))
            with self.assertRaisesRegex(BillingError, "checksum"):
                load_schema()

    def test_download_denies_guests_and_roles_without_fiscal_view(self):
        document_id, _created = self.prepare(self.paid_order())
        path = f"/facturacion/{document_id}/borrador.json"
        guest = self.app.test_client()
        self.assertEqual(guest.get(path).status_code, 302)
        with self.app.app_context():
            role = Rol(codigo="boundary_reader", nombre="Solo consulta de carta")
            role.permisos = {"productos.view"}
            user = Usuario(nickname="boundary-reader", nombre="Test", apellido="Reader", rol=role.codigo)
            user.set_password("boundary-test-password")
            db.session.add_all([role, user])
            db.session.commit()
        limited = self.app.test_client()
        limited.post("/login", data={"nickname": "boundary-reader", "password": "boundary-test-password"})
        response = limited.get(path)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"codigoGeneracion", response.data)
        self.assertNotIn(b"06141212121012", response.data)

    def test_simultaneous_requests_for_one_order_create_only_one_draft(self):
        order_id = self.paid_order()
        results = self.concurrently_prepare([order_id, order_id])
        self.assertEqual(len({entry[0] for entry in results}), 1)
        self.assertEqual(sum(entry[2] for entry in results), 1)
        with self.app.app_context():
            self.assertEqual(DocumentoFiscal.query.count(), 1)
            self.assertEqual(SecuenciaBorradorDTE.query.one().siguiente, 1)

    def test_simultaneous_orders_receive_distinct_local_control_numbers(self):
        results = self.concurrently_prepare([self.paid_order(), self.paid_order()])
        self.assertEqual(len({entry[1] for entry in results}), 2)
        self.assertTrue(all(entry[2] for entry in results))
        with self.app.app_context():
            self.assertEqual(DocumentoFiscal.query.count(), 2)
            self.assertEqual(SecuenciaBorradorDTE.query.one().siguiente, 2)
