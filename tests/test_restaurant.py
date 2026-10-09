"""Regression coverage for restaurant operations using disposable local databases.

Run from the repository root: python -m unittest discover -s tests -v
No test connects to the configured production database or changes uploaded files.
"""

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (
    AuditLog,
    Categoria,
    Mesa,
    MovimientoInventario,
    Orden,
    OrdenItem,
    Pago,
    PreferenciaSistema,
    Producto,
    Rol,
    SesionCaja,
    Usuario,
    Zona,
)
from app.services import (
    bootstrap_roles_permissions,
    get_system_preferences,
    session_cash_expected,
    session_sales_total,
)


class RestaurantRegressionTests(unittest.TestCase):
    admin_name = "test-administrator"
    admin_password = "test-password-only"

    def setUp(self):
        self.scratch = TemporaryDirectory(prefix="restobar-tests-")
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        # Override configuration before the factory bootstraps its database.
        # This also isolates uploads and the automatically created administrator.
        with patch.multiple(
            Config,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{root / 'restaurant.sqlite3'}",
            SECRET_KEY="isolated-test-session-key",
            DEFAULT_ADMIN_NICKNAME=self.admin_name,
            DEFAULT_ADMIN_PASSWORD=self.admin_password,
            PRODUCT_UPLOAD_DIR=root / "products",
            BRANDING_UPLOAD_DIR=root / "branding",
        ):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.addCleanup(self.dispose_database)

    def dispose_database(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def login(self, nickname=None, password=None, client=None):
        return (client or self.client).post(
            "/login",
            data={
                "nickname": nickname or self.admin_name,
                "password": password or self.admin_password,
            },
        )

    def post(self, path, data):
        response = self.client.post(path, data=data)
        self.assertEqual(response.status_code, 302, path)
        return response

    def preferences_payload(self, **overrides):
        with self.app.app_context():
            payload = get_system_preferences()
        # An unchecked checkbox is omitted by browsers.
        payload.pop("motion_enabled", None)
        payload.update(overrides)
        return payload

    def create_dining_fixture(self):
        """Create a table and a kitchen product through their actual forms."""
        self.post("/zonas", {"nombre": "Salon de prueba"})
        self.post("/categorias", {"nombre": "Pizzas de prueba", "envia_a_cocina": "on"})
        with self.app.app_context():
            zone_id = Zona.query.filter_by(nombre="Salon de prueba").one().id
            category_id = Categoria.query.filter_by(nombre="Pizzas de prueba").one().id
        self.post(
            "/mesas",
            {"numero": "1", "sillas": "4", "zona_id": zone_id, "limpieza_estado": "limpia"},
        )
        self.post(
            "/productos",
            {
                "name": "Pizza de prueba",
                "category_id": category_id,
                "sale_price": "12.50",
                "available": "on",
            },
        )
        with self.app.app_context():
            table_id = Mesa.query.filter_by(numero=1, zona_id=zone_id).one().id
            product_id = Producto.query.filter_by(nombre="Pizza de prueba").one().id
        return table_id, product_id

    def create_order(self, table_id):
        response = self.post("/ordenes", {"mesa_id": table_id})
        self.assertRegex(response.location, r"/ordenes/\d+$")
        return int(response.location.rsplit("/", 1)[1])

    def add_pizza(self, order_id, product_id, quantity=2):
        self.post(
            f"/ordenes/{order_id}/items",
            {"product_id": product_id, "quantity": quantity, "notes": "Sin cebolla"},
        )
        with self.app.app_context():
            return OrdenItem.query.filter_by(orden_id=order_id, producto_id=product_id).one().id

    def test_authentication_and_safe_login_redirect(self):
        for path in ("/dashboard", "/mesas", "/caja", "/preferencias", "/api/me", "/api/service-alerts"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.location)

        response = self.login(password="incorrect-test-password")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/api/me").status_code, 302)

        response = self.client.post(
            "/login",
            data={"nickname": self.admin_name, "password": self.admin_password, "next": "https://example.org/"},
        )
        self.assertEqual(response.location, "/dashboard")
        profile = self.client.get("/api/me").get_json()
        self.assertEqual(profile["nickname"], self.admin_name)
        self.assertNotIn("password_hash", profile)
        self.assertEqual(self.client.post("/logout").status_code, 302)
        self.assertEqual(self.client.get("/api/me").status_code, 302)

    def test_limited_role_cannot_mutate_cash_or_preferences(self):
        with self.app.app_context():
            role = Rol(codigo="test_read_only", nombre="Consulta de mesas")
            role.permisos = {"mesas.view"}
            user = Usuario(nickname="test-waiter", nombre="Test", apellido="Waiter", rol=role.codigo)
            user.set_password(self.admin_password)
            db.session.add_all([role, user])
            db.session.commit()

        response = self.login(nickname="test-waiter")
        self.assertEqual(response.location, "/mesas")
        self.assertEqual(self.client.get("/mesas").status_code, 200)
        self.assertEqual(self.client.get("/api/mesas").status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 403)
        for path, form in (
            ("/caja/abrir", {"opening_amount": "50.00"}),
            ("/preferencias", self.preferences_payload(business_name="Unauthorized change")),
        ):
            with self.subTest(path=path):
                response = self.post(path, form)
                self.assertEqual(response.location, "/mesas")
        with self.app.app_context():
            self.assertEqual(SesionCaja.query.count(), 0)
            self.assertEqual(get_system_preferences()["business_name"], "Restobar")

    def test_startup_preserves_configured_staff_roles_and_users(self):
        with self.app.app_context():
            role = db.session.get(Rol, "cajero")
            role.permisos = {"caja.view", "caja.charge"}
            user = Usuario(nickname="existing-cashier", nombre="Test", apellido="Cashier", rol="cajero")
            user.set_password(self.admin_password)
            db.session.add(user)
            db.session.commit()
            user_id = user.id
            bootstrap_roles_permissions()
            db.session.expire_all()
            self.assertEqual(db.session.get(Rol, "cajero").permisos, {"caja.view", "caja.charge"})
            self.assertEqual(db.session.get(Usuario, user_id).rol, "cajero")
            self.assertIsNotNone(db.session.get(Rol, "mesero"))
            self.assertIsNotNone(db.session.get(Rol, "cocina"))
        response = self.login(nickname="existing-cashier")
        self.assertEqual(response.location, "/caja")
        self.assertEqual(self.client.get("/caja").status_code, 200)
        self.assertEqual(self.client.get("/preferencias").status_code, 302)

    def test_service_alerts_follow_real_state_and_role_permissions(self):
        self.login()
        alerts = self.client.get("/api/service-alerts").get_json()["alerts"]
        self.assertEqual([alert["kind"] for alert in alerts], ["cash"])
        table_id, product_id = self.create_dining_fixture()
        self.post("/caja/abrir", {"opening_amount": "0.00"})
        order_id = self.create_order(table_id)
        item_id = self.add_pizza(order_id, product_id, quantity=1)
        alerts = self.client.get("/api/service-alerts").get_json()["alerts"]
        self.assertEqual([alert["kind"] for alert in alerts], ["kitchen"])
        self.assertEqual(alerts[0]["count"], 1)
        self.assertEqual(alerts[0]["url"], "/cocina")

        with self.app.app_context():
            role = Rol(codigo="test_catalog_reader", nombre="Consulta de carta")
            role.permisos = {"productos.view"}
            user = Usuario(nickname="catalog-reader", nombre="Test", apellido="Reader", rol=role.codigo)
            user.set_password(self.admin_password)
            db.session.add_all([role, user])
            db.session.commit()
        limited_client = self.app.test_client()
        self.login(nickname="catalog-reader", client=limited_client)
        self.assertEqual(limited_client.get("/api/service-alerts").get_json(), {"alerts": []})
        self.post(f"/items/{item_id}/preparar", {})
        self.assertEqual(self.client.get("/api/service-alerts").get_json(), {"alerts": []})

    def test_admin_pages_render_with_an_empty_database(self):
        self.login()
        for path in (
            "/dashboard", "/mesas", "/ordenes", "/cocina", "/productos", "/caja",
            "/inventario", "/reportes", "/usuarios", "/roles", "/preferencias", "/auditoria",
            "/zonas/nueva", "/categorias/nueva", "/productos/nuevo", "/mesas/nueva",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Restobar", response.data)

    def test_dashboard_occupancy_excludes_the_system_takeout_table(self):
        self.login()
        metrics = self.client.get("/api/dashboard").get_json()
        self.assertEqual(metrics["mesas_total"], 0)
        self.assertEqual(metrics["mesas_ocupadas"], 0)
        table_id, _ = self.create_dining_fixture()
        metrics = self.client.get("/api/dashboard").get_json()
        self.assertEqual(metrics["mesas_total"], 1)
        self.assertEqual(metrics["mesas_ocupadas"], 0)
        self.post("/caja/abrir", {"opening_amount": "0.00"})
        self.create_order(table_id)
        metrics = self.client.get("/api/dashboard").get_json()
        self.assertEqual(metrics["mesas_total"], 1)
        self.assertEqual(metrics["mesas_ocupadas"], 1)

    def test_brand_preferences_persist_and_motion_can_be_disabled(self):
        self.login()
        self.post(
            "/preferencias",
            self.preferences_payload(
                business_name="Restobar Pruebas",
                business_tagline="De la cocina a la mesa",
                brand_accent="olive",
                default_theme="dark",
            ),
        )
        with self.app.app_context():
            preferences = get_system_preferences()
            self.assertEqual(preferences["business_name"], "Restobar Pruebas")
            self.assertEqual(preferences["brand_accent"], "olive")
            self.assertEqual(preferences["motion_enabled"], "0")
            self.assertEqual(db.session.get(PreferenciaSistema, "brand_accent").valor, "olive")
            self.assertEqual(db.session.get(PreferenciaSistema, "motion_enabled").valor, "0")
        fresh_client = self.app.test_client()
        self.login(client=fresh_client)
        page = fresh_client.get("/dashboard").data
        self.assertIn(b"Restobar Pruebas", page)
        self.assertTrue(b'data-brand-accent="olive"' in page, "Saved palette must reach the page")
        self.assertTrue(b'data-motion="reduced"' in page, "Disabled motion must reach the page")
        self.post(
            "/preferencias",
            self.preferences_payload(brand_accent="terracotta", motion_enabled="on"),
        )
        with self.app.app_context():
            self.assertEqual(get_system_preferences()["motion_enabled"], "1")

    def test_invalid_preferences_do_not_overwrite_saved_identity(self):
        self.login()
        with self.app.app_context():
            original = get_system_preferences()
        for invalid in (
            {"brand_accent": "purple"},
            {"timezone": "Unknown/Timezone"},
            {"business_logo_url": "javascript:alert(1)"},
        ):
            with self.subTest(invalid=invalid):
                self.post(
                    "/preferencias",
                    self.preferences_payload(business_name="Must not be saved", **invalid),
                )
                with self.app.app_context():
                    self.assertEqual(get_system_preferences(), original)

    def test_order_requires_cash_and_clean_table(self):
        self.login()
        table_id, _ = self.create_dining_fixture()
        response = self.post("/ordenes", {"mesa_id": table_id})
        self.assertEqual(response.location, "/caja")
        self.post("/caja/abrir", {"opening_amount": "-1"})
        with self.app.app_context():
            self.assertEqual(SesionCaja.query.count(), 0)
        self.post("/caja/abrir", {"opening_amount": "40.00"})
        self.post("/caja/abrir", {"opening_amount": "40.00"})
        with self.app.app_context():
            self.assertEqual(SesionCaja.query.count(), 1)
            table = db.session.get(Mesa, table_id)
            table.limpieza_estado = "sucia"
            db.session.commit()
        self.post("/ordenes", {"mesa_id": table_id})
        with self.app.app_context():
            self.assertEqual(Orden.query.count(), 0)

    def test_nonfinite_monetary_inputs_cannot_create_invalid_payments(self):
        self.login()
        table_id, product_id = self.create_dining_fixture()
        self.post("/caja/abrir", {"opening_amount": "NaN"})
        with self.app.app_context():
            self.assertEqual(SesionCaja.query.one().monto_apertura, Decimal("0.00"))
        order_id = self.create_order(table_id)
        item_id = self.add_pizza(order_id, product_id, quantity=1)
        self.post(f"/items/{item_id}/preparar", {})
        for invalid in ("NaN", "sNaN", "Infinity", "-Infinity"):
            with self.subTest(amount=invalid):
                self.post(f"/ordenes/{order_id}/pagar", {"method": "efectivo", "amount": invalid})
                with self.app.app_context():
                    self.assertEqual(Pago.query.count(), 0)
                    self.assertEqual(db.session.get(Orden, order_id).total, Decimal("12.50"))
                    self.assertEqual(db.session.get(Orden, order_id).estado, "abierta")

    def test_restaurant_order_kitchen_payment_and_ticket_end_to_end(self):
        self.login()
        table_id, product_id = self.create_dining_fixture()
        self.post("/caja/abrir", {"opening_amount": "40.00"})
        order_id = self.create_order(table_id)
        item_id = self.add_pizza(order_id, product_id)
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            self.assertEqual(order.total, Decimal("25.00"))
            self.assertEqual(order.mesa.estado, "ocupada")
            self.assertEqual(db.session.get(OrdenItem, item_id).estado, "pendiente")
        kitchen = self.client.get("/api/cocina/pending").get_json()
        self.assertEqual(kitchen["count"], 1)

        self.post(f"/items/{item_id}/entregar", {})
        with self.app.app_context():
            self.assertEqual(db.session.get(OrdenItem, item_id).estado, "pendiente")
        # A pending dish cannot be charged, even via a direct HTTP request.
        self.post(f"/ordenes/{order_id}/pagar", {"method": "efectivo", "amount": "25.00"})
        with self.app.app_context():
            self.assertEqual(Pago.query.count(), 0)
        self.post(f"/items/{item_id}/preparar", {})
        self.assertEqual(self.client.get("/api/cocina/pending").get_json()["count"], 0)
        self.assertEqual(self.client.get(f"/ordenes/{order_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/ordenes/{order_id}/estado").status_code, 200)
        self.post(
            f"/ordenes/{order_id}/pagar",
            {"method": "efectivo", "amount": "25.00", "tip_percent": "10", "tendered_amount": "30.00"},
        )
        with self.app.app_context():
            order = db.session.get(Orden, order_id)
            self.assertEqual(order.estado, "pagada")
            self.assertEqual(order.saldo_pendiente, Decimal("0.00"))
            self.assertTrue(all(item.pagado for item in order.items))
            self.assertEqual(order.mesa.estado, "disponible")
            self.assertEqual(order.mesa.limpieza_estado, "sucia")
            payment = Pago.query.one()
            self.assertEqual(payment.propina, Decimal("2.50"))
            self.assertEqual(session_cash_expected(order.sesion_caja), Decimal("67.50"))
            self.assertEqual(session_sales_total(order.sesion_caja), Decimal("27.50"))
            self.assertGreater(AuditLog.query.filter_by(accion="cobrar").count(), 0)
        ticket = self.client.get(f"/ordenes/{order_id}/ticket")
        self.assertEqual(ticket.status_code, 200)
        self.assertIn(b"Pizza de prueba", ticket.data)
        self.post(f"/ordenes/{order_id}/pagar", {"method": "efectivo", "amount": "25.00"})
        with self.app.app_context():
            self.assertEqual(Pago.query.count(), 1)

    def test_stock_is_reserved_and_consumed_once_after_full_payment(self):
        self.login()
        table_id, _ = self.create_dining_fixture()
        # Existing stock is a fixture only in this disposable database; catalog
        # creation correctly requires subsequent inventory operations for stock.
        with self.app.app_context():
            category = Categoria(nombre="Bebidas de prueba", envia_a_cocina=False)
            drink = Producto(
                nombre="Bebida de prueba", categoria=category,
                precio_venta=Decimal("2.00"), stock_actual=3, maneja_stock=True,
            )
            db.session.add(drink)
            db.session.commit()
            product_id = drink.id
        self.post("/caja/abrir", {"opening_amount": "0.00"})
        order_id = self.create_order(table_id)
        self.post(f"/ordenes/{order_id}/items", {"product_id": product_id, "quantity": "4"})
        with self.app.app_context():
            self.assertEqual(OrdenItem.query.count(), 0)
        self.post(f"/ordenes/{order_id}/items", {"product_id": product_id, "quantity": "2"})
        competing_order_id = self.create_order(table_id)
        self.post(f"/ordenes/{competing_order_id}/items", {"product_id": product_id, "quantity": "2"})
        with self.app.app_context():
            self.assertEqual(db.session.get(Orden, competing_order_id).items, [])
        self.post(f"/ordenes/{order_id}/pagar", {"method": "tarjeta", "amount": "5.00"})
        with self.app.app_context():
            self.assertEqual(Pago.query.count(), 0)
        self.post(f"/ordenes/{order_id}/pagar", {"method": "tarjeta", "amount": "2.00"})
        with self.app.app_context():
            self.assertEqual(db.session.get(Orden, order_id).estado, "abierta")
            self.assertEqual(db.session.get(Producto, product_id).stock_actual, 3)
        self.post(f"/ordenes/{order_id}/pagar", {"method": "tarjeta", "amount": "2.00"})
        self.post(f"/ordenes/{order_id}/pagar", {"method": "tarjeta", "amount": "2.00"})
        with self.app.app_context():
            self.assertEqual(db.session.get(Orden, order_id).estado, "pagada")
            self.assertEqual(db.session.get(Producto, product_id).stock_actual, 1)
            self.assertEqual(MovimientoInventario.query.filter_by(tipo="venta").count(), 1)
            self.assertEqual(Pago.query.count(), 2)

    def test_takeout_requires_a_customer_name(self):
        self.login()
        self.post("/caja/abrir", {"opening_amount": "0.00"})
        takeout_id = self.app.config["TAKEOUT_TABLE_ID"]
        self.post("/ordenes", {"mesa_id_llevar": takeout_id})
        with self.app.app_context():
            self.assertEqual(Orden.query.count(), 0)
        response = self.post(
            "/ordenes", {"mesa_id_llevar": takeout_id, "nombre_cliente": "Cliente de prueba"},
        )
        self.assertRegex(response.location, r"/ordenes/\d+$")
        with self.app.app_context():
            self.assertEqual(Orden.query.one().nombre_cliente, "Cliente de prueba")
            self.assertEqual(db.session.get(Mesa, takeout_id).estado, "disponible")


if __name__ == "__main__":
    unittest.main()
