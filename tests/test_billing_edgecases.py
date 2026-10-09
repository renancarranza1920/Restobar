"""Fiscal boundary and concurrency regressions on disposable local databases.

Bundled official schema bytes are copied to a temporary location; no network requests or
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
    verified_payload,
    validate_current_payload,
    build_payload,
    _validate_standard_arithmetic,
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


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "app/schemas/official/fe-f-v2.json"


class FiscalBoundaryTests(unittest.TestCase):
    def setUp(self):
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
            "descActividad": "Restaurantes de prueba", "departamento": "06", "municipio": "23", "distrito": "14",
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
                        "municipio": "23", "distrito": "14", "complemento": "Dirección de prueba",
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


    def test_municipality_and_district_are_official_and_department_coupled(self):
        with self.app.app_context():
            for update in ({"municipio": "14"}, {"municipio": "99"}, {"distrito": "99"}, {"departamento": "01"}):
                with self.subTest(update=update), self.assertRaises(BillingError):
                    issuer_from_profile({**self.profile, **update})

    def test_ccf_rounding_retains_body_precision_and_reconciles_aggregate_tax(self):
        order_id = self.paid_order()
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            order.items[0].precio_unitario = Decimal("11.30")
            order.items[0].cantidad = 2
            order.items.append(OrdenItem(producto_id=self.product_id, cantidad=1,
                                       precio_unitario=Decimal("0.05"), estado="entregado", pagado=True))
            order.total = Decimal("22.65")
            order.pagos[0].monto = Decimal("22.65")
            db.session.commit()
            form = {"nombre": "Cliente CCF", "tipo_dte": "03", "operacion_estandar": "1",
                    "nit": "06141212121012", "nrc": "1234567", "codActividad": "56101",
                    "descActividad": "Restaurantes de prueba", "departamento": "06", "municipio": "23",
                    "distrito": "14", "complemento": "Dirección de prueba"}
            document, _ = prepare_document(order, form, self.admin_id)
            payload = verified_payload(document)
            validate_current_payload(payload)
            base = sum(line["ventaGravada"] for line in payload["cuerpoDocumento"])
            iva = payload["resumen"]["tributos"][0]["valor"]
            self.assertEqual(base, Decimal("20.04424779"))
            self.assertEqual(payload["resumen"]["totalGravada"], Decimal("20.04"))
            self.assertEqual(iva, amount(base * Decimal("0.13")))
            self.assertEqual(amount(base) + iva, Decimal("22.65"))
            self.assertEqual(payload["resumen"]["totalPagar"], Decimal("22.65"))
            for line in payload["cuerpoDocumento"]:
                self.assertLessEqual(abs(line["precioUni"] * line["cantidad"] - line["ventaGravada"]), Decimal("0.01"))

    def test_ccf_four_cent_total_is_valid_with_unrounded_item_base(self):
        order_id = self.paid_order()
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            order.items[0].precio_unitario = order.total = order.pagos[0].monto = Decimal("0.04")
            db.session.commit()
            form = {"nombre": "Cliente CCF", "tipo_dte": "03", "operacion_estandar": "1",
                    "nit": "06141212121012", "nrc": "1234567", "codActividad": "56101",
                    "descActividad": "Restaurantes de prueba", "departamento": "06", "municipio": "23",
                    "distrito": "14", "complemento": "Dirección de prueba"}
            document, _ = prepare_document(order, form, self.admin_id)
            payload = verified_payload(document)
            validate_current_payload(payload)
            self.assertEqual(payload["cuerpoDocumento"][0]["ventaGravada"], Decimal("0.03539823"))
            self.assertEqual(payload["resumen"]["totalGravada"], Decimal("0.04"))
            self.assertEqual(payload["resumen"]["tributos"][0]["valor"], Decimal("0.00"))
            self.assertEqual(payload["resumen"]["totalPagar"], Decimal("0.04"))
            self.assertEqual(db.session.get(Orden, order_id).total, Decimal("0.04"))


    def test_fe_preserves_eight_decimal_item_vat_before_rounding_summary(self):
        for gross_unit, expected_vat in ((Decimal("0.04"), Decimal("0.09")), (Decimal("0.10"), Decimal("0.23"))):
            order_id = self.paid_order()
            with self.subTest(gross_unit=gross_unit), self.app.app_context():
                order = db.session.get(Orden, order_id)
                order.items[0].precio_unitario = gross_unit
                for _ in range(19):
                    order.items.append(OrdenItem(producto_id=self.product_id, cantidad=1,
                                               precio_unitario=gross_unit, estado="entregado", pagado=True))
                order.total = order.pagos[0].monto = gross_unit * 20
                db.session.commit()
                document, _ = prepare_document(order, {"nombre": "Cliente", "operacion_estandar": "1"}, self.admin_id)
                payload = verified_payload(document)
                validate_current_payload(payload)
                vat_items = [line["ivaItem"] for line in payload["cuerpoDocumento"]]
                self.assertEqual(len(vat_items), 20)
                self.assertTrue(all(value.as_tuple().exponent == -8 for value in vat_items))
                self.assertEqual(payload["resumen"]["totalIva"], expected_vat)
                self.assertEqual(document.iva, expected_vat)
                self.assertEqual(payload["resumen"]["totalIva"], amount(sum(vat_items)))
                self.assertEqual(payload["resumen"]["totalPagar"], gross_unit * 20)


    def test_ccf_large_quantity_cannot_exceed_one_cent_line_arithmetic_tolerance(self):
        order_id = self.paid_order()
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            order.items[0].precio_unitario = Decimal("0.01")
            order.items[0].cantidad = 99_999_999
            order.total = order.pagos[0].monto = Decimal("999999.99")
            db.session.commit()
            form = {"nombre": "Cliente CCF", "tipo_dte": "03", "operacion_estandar": "1",
                    "nit": "06141212121012", "nrc": "1234567", "codActividad": "56101",
                    "descActividad": "Restaurantes de prueba", "departamento": "06", "municipio": "23",
                    "distrito": "14", "complemento": "Dirección de prueba"}
            with self.assertRaisesRegex(BillingError, "ocho decimales"):
                prepare_document(order, form, self.admin_id)
            db.session.rollback()
            self.assertEqual(db.session.get(Orden, order_id).total, Decimal("999999.99"))
            self.assertEqual(DocumentoFiscal.query.count(), 0)

    def test_schema_valid_but_incorrect_fe_vat_cannot_be_signed(self):
        order_id = self.paid_order()
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            order.items[0].precio_unitario = order.total = order.pagos[0].monto = Decimal("0.10")
            db.session.commit()
            document, _ = prepare_document(order, {"nombre": "Cliente", "operacion_estandar": "1"}, self.admin_id)
            payload = verified_payload(document)
            payload["cuerpoDocumento"][0]["ivaItem"] = Decimal("0.01")
            payload["resumen"]["totalIva"] = Decimal("0.01")
            # Both numbers remain allowed by the official schema; fiscal math
            # provides a separate check before any signing or transmission.
            from app.billing import validate_schema
            validate_schema(payload)
            with self.assertRaisesRegex(BillingError, "cálculos"):
                validate_current_payload(payload)


    def test_fractional_order_quantities_are_rejected_by_the_integer_product_workflow(self):
        order_id = self.paid_order()
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            order.items[0].cantidad = 1.5
            order.total = order.pagos[0].monto = Decimal("18.75")
            db.session.commit()
            for kind in ("01", "03"):
                with self.subTest(kind=kind), self.assertRaisesRegex(BillingError, "cantidades enteras"):
                    prepare_document(order, {"nombre": "Cliente", "operacion_estandar": "1", "tipo_dte": kind}, self.admin_id)
                db.session.rollback()
            self.assertEqual(DocumentoFiscal.query.count(), 0)


    def test_ccf_cent_totals_and_multiline_splits_reconcile_from_one_cent_to_100_dollars(self):
        from datetime import datetime
        from uuid import uuid4
        issued_at = datetime(2026, 10, 9, 12, 0, 0)
        generation_code = str(uuid4()).upper()
        with self.app.app_context():
            issuer = issuer_from_profile(self.profile, "03")
            recipient = recipient_from_form({
                "nombre": "Cliente CCF", "nit": "06141212121012", "nrc": "1234567",
                "codActividad": "56101", "descActividad": "Restaurantes de prueba",
                "departamento": "06", "municipio": "23", "distrito": "14",
                "complemento": "Dirección de prueba",
            }, Decimal("1.00"), "03")
            for cents in range(1, 10_001):
                gross = Decimal(cents) / 100
                for parts in ([cents], [cents // 3, cents // 3, cents - 2 * (cents // 3)]):
                    lines = [{"product_id": self.product_id, "description": "Producto de prueba", "quantity": 1,
                              "unit_price": Decimal(part) / 100, "total": Decimal(part) / 100}
                             for part in parts if part]
                    snapshot = {"total": gross, "lines": lines,
                                "payments": [{"fiscal_payment_code": "01", "amount": gross}]}
                    payload = build_payload(snapshot, issuer, recipient, cents, generation_code, issued_at, "03")
                    _validate_standard_arithmetic(payload)
                    summary = payload["resumen"]
                    self.assertEqual(summary["totalGravada"] + summary["tributos"][0]["valor"], gross,
                                     f"cents={cents}, parts={parts}")
                    self.assertEqual(summary["totalPagar"], gross)
                    self.assertEqual(summary["totalGravada"], amount(sum(line["ventaGravada"] for line in payload["cuerpoDocumento"])))
                    for line in payload["cuerpoDocumento"]:
                        self.assertLessEqual(abs(line["precioUni"] * line["cantidad"] - line["ventaGravada"]), Decimal("0.01"))
                    if cents in {1, 4, 100, 10_000}:
                        validate_current_payload(payload)
            self.assertEqual(summary["totalPagar"], Decimal("100.00"))
