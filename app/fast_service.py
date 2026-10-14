"""Fast-food counter: one transaction for payment, stock and kitchen ticket."""
import hmac
import secrets
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from flask import Blueprint, current_app, jsonify, render_template, request, session, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .extensions import db
from .models import Categoria, Producto, Orden, OrdenItem, OrdenMesa, Pago, MovimientoInventario
from .fast_models import VentaRapida, RecetaIngrediente, UnidadInsumo
from .fast_inventory import lock_operations, demand_errors, consume_item, portions_available, reservations, unit_for
from .services import feature_required, get_active_cash_session, get_productos, money, audit_event, user_can

counter_bp = Blueprint("counter", __name__)


def csrf_token():
    if "counter_csrf" not in session:
        session["counter_csrf"] = secrets.token_hex(32)
    return session["counter_csrf"]


def valid_csrf(value):
    return bool(value and session.get("counter_csrf") and
        hmac.compare_digest(str(value), session["counter_csrf"]))


def amount_value(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value < 0 or value > Decimal("99999999.99") or value != money(value):
            raise ValueError()
        return money(value)
    except (ValueError, InvalidOperation):
        raise ValueError("Ingresa un monto válido con hasta dos decimales.") from None


def positive_units(value):
    try:
        result = int(str(value))
        if result <= 0 or result > 100000000:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError("La cantidad debe ser un número entero mayor que cero en la unidad base.") from None


def recent_counter_orders():
    active_ids = db.select(OrdenItem.orden_id).where(
        OrdenItem.estado.in_(["pendiente", "listo"]))
    active = VentaRapida.query.filter(VentaRapida.orden_id.in_(active_ids)).order_by(VentaRapida.orden_id).all()
    ids = {s.orden_id for s in active}
    delivered = VentaRapida.query.order_by(VentaRapida.orden_id.desc()).limit(6).all()
    return active + [s for s in delivered if s.orden_id not in ids]


@counter_bp.get("/venta")
@feature_required("caja.charge")
def sale():
    products = get_productos(disponibles_only=True)
    reserved = reservations()
    cards = []
    for product in products:
        cards.append({"id": product.id, "name": product.nombre,
            "price": str(money(product.precio_venta)), "category": product.categoria.nombre,
            "kitchen": product.requiere_cocina, "image": product.imagen_url,
            "available": portions_available(product, reserved),
            "recipe": bool(RecetaIngrediente.query.filter_by(producto_id=product.id).first())})
    recent = recent_counter_orders()
    return render_template("sale.html", page_title="Venta y cobro", products=cards,
        sale_key=str(uuid4()), csrf=csrf_token(), recent=recent,
        session_open=get_active_cash_session())


@counter_bp.get("/venta/estado")
@feature_required("caja.charge")
def live_status():
    reserved = reservations()
    shift = get_active_cash_session()
    return jsonify(shift_id=shift.id if shift else None,
        html=render_template("partials/counter_orders.html", recent=recent_counter_orders(), csrf=csrf_token()),
        stocks={p.id: portions_available(p, reserved) for p in get_productos(disponibles_only=True)})


def sale_result(sale, replay=False):
    order = sale.orden
    return {"order_id": order.id, "total": str(money(order.total)),
        "change": str(money(sale.cambio)), "replay": replay,
        "kitchen": any(i.requiere_cocina and i.estado == "pendiente" for i in order.items),
        "ticket_url": url_for("web.ticket_orden", order_id=order.id),
        "billing_url": url_for("billing.new", order_id=order.id) if user_can(current_user, "facturacion.create") else None,
        "key": str(uuid4())}


@counter_bp.post("/venta/cobrar")
@feature_required("caja.charge")
def checkout():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not valid_csrf(request.headers.get("X-CSRF-Token")):
        return jsonify(error="La sesión venció. Recarga la pantalla antes de cobrar."), 400
    try:
        key = str(UUID(str(data.get("key", ""))))
    except ValueError:
        return jsonify(error="Recarga la pantalla para iniciar una venta."), 400
    try:
        lock_operations()
        existing = VentaRapida.query.filter_by(clave=key).first()
        if existing:
            if existing.orden.usuario_id != current_user.id:
                raise ValueError("Esta venta pertenece a otro usuario.")
            result = sale_result(existing, replay=True)
            db.session.rollback()
            return jsonify(result)
        shift = get_active_cash_session()
        if not shift:
            raise ValueError("Abre un turno de caja antes de vender.")
        if data.get("shift_id") != shift.id:
            raise ValueError("El turno cambió. Recarga la pantalla antes de cobrar.")
        channel = data.get("channel", "llevar")
        if channel not in {"llevar", "local"}:
            raise ValueError("Selecciona para llevar o comer aquí.")
        method = data.get("method", "efectivo")
        if method not in {"efectivo", "tarjeta"}:
            raise ValueError("Selecciona efectivo o tarjeta.")
        raw_lines = data.get("lines")
        if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 100:
            raise ValueError("Añade al menos un producto al pedido.")
        lines = []
        for row in raw_lines:
            if not isinstance(row, dict):
                raise ValueError("Revisa los productos del pedido.")
            product = db.session.get(Producto, positive_units(row.get("id")))
            if not product or product.es_inventario or not product.disponible:
                raise ValueError("Uno de los productos ya no está disponible.")
            quantity = positive_units(row.get("quantity"))
            if quantity > 999:
                raise ValueError("Usa hasta 999 unidades por producto.")
            notes = str(row.get("notes") or "").strip()
            if len(notes) > 200:
                raise ValueError("Las indicaciones de cocina admiten hasta 200 caracteres.")
            if money(row.get("price", -1)) != money(product.precio_venta):
                raise ValueError(f"Cambió el precio de {product.nombre}. Recarga antes de cobrar.")
            lines.append({"product": product, "quantity": quantity, "notes": notes})
        errors = demand_errors(lines)
        if errors:
            raise ValueError(errors[0])
        total = money(sum(l["product"].precio_venta * l["quantity"] for l in lines))
        if total <= 0 or total > Decimal("99999999.99"):
            raise ValueError("Revisa el total del pedido.")
        received = amount_value(data.get("received")) if method == "efectivo" else total
        if received < total:
            raise ValueError("El efectivo recibido no alcanza para pagar el pedido.")
        customer = str(data.get("customer") or "").strip()
        if len(customer) > 100:
            raise ValueError("La referencia del pedido admite hasta 100 caracteres.")
        order = Orden(mesa_id=current_app.config["TAKEOUT_TABLE_ID"],
            sesion_caja_id=shift.id, usuario_id=current_user.id,
            nombre_cliente=customer or ("Para llevar" if channel == "llevar" else "Comer aquí"),
            total=total, estado="pagada")
        db.session.add(order)
        db.session.flush()
        db.session.add(OrdenMesa(orden=order, mesa_id=order.mesa_id))
        sale = VentaRapida(orden=order, clave=key, canal=channel, recibido=received, cambio=received-total)
        db.session.add(sale)
        for line in lines:
            product = line["product"]
            item = OrdenItem(orden=order, producto=product, cantidad=line["quantity"],
                precio_unitario=product.precio_venta, costo_unitario=product.precio_costo,
                notas=line["notes"] or None,
                estado="pendiente" if product.requiere_cocina else "entregado")
            db.session.add(item)
            db.session.flush()
            consume_item(item)
        db.session.add(Pago(orden=order, metodo=method, monto=total, propina=0))
        audit_event("venta_rapida", "orden", order.id, f"Venta #{order.id} cobrada y enviada a cocina.",
            {"total": total, "metodo": method, "recibido": received, "cambio": received-total,
             "canal": channel, "turno": shift.id})
        db.session.commit()
        return jsonify(sale_result(sale)), 201
    except (ValueError, InvalidOperation, TypeError) as exc:
        db.session.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "Revisa los importes del pedido."
        return jsonify(error=message), 400
    except (IntegrityError, SQLAlchemyError):
        db.session.rollback()
        current_app.logger.exception("Counter transaction failed")
        return jsonify(error="No se pudo confirmar el cobro. Reintenta el mismo pedido; no se duplicará."), 409


@counter_bp.get("/recetas")
@feature_required("inventario.view")
def recipes():
    products = get_productos()
    recipes = {p.id: RecetaIngrediente.query.filter_by(producto_id=p.id).all() for p in products}
    ingredients = Producto.query.filter_by(es_inventario=True).order_by(Producto.nombre).all()
    unit_products = [p for p in products if p.controla_stock and not recipes[p.id]]
    return render_template("recipes.html", page_title="Recetas e insumos", products=products,
        recipes=recipes, ingredients=ingredients, unit_products=unit_products, unit_for=unit_for, csrf=csrf_token())


@counter_bp.post("/recetas/<int:product_id>")
@feature_required("inventario.create")
def save_recipe(product_id):
    try:
        if not valid_csrf(request.form.get("csrf")):
            raise ValueError("Recarga la pantalla antes de guardar.")
        lock_operations()
        product = db.session.get(Producto, product_id)
        if not product or product.es_inventario:
            raise ValueError("Selecciona un producto de la carta.")
        unpaid = OrdenItem.query.join(Orden).filter(OrdenItem.producto_id == product_id,
            OrdenItem.pagado.is_(False), OrdenItem.estado != "cancelado", Orden.estado != "cancelada").first()
        if unpaid:
            raise ValueError("Cobra o cancela los pedidos pendientes de este producto antes de cambiar su receta.")
        ids = request.form.getlist("ingredient_id")
        quantities = request.form.getlist("quantity")
        if len(ids) != len(quantities) or len(ids) > 100:
            raise ValueError("Revisa los ingredientes de la receta.")
        rows = {}
        for raw_id, raw_quantity in zip(ids, quantities):
            if not raw_id and not raw_quantity:
                continue
            ingredient = db.session.get(Producto, positive_units(raw_id))
            quantity = positive_units(raw_quantity)
            if not ingredient or not ingredient.es_inventario:
                raise ValueError("Usa solo insumos de bodega.")
            if ingredient.id in rows:
                raise ValueError("Cada insumo debe aparecer una sola vez en la receta.")
            rows[ingredient.id] = quantity
        RecetaIngrediente.query.filter_by(producto_id=product_id).delete()
        for ingredient_id, quantity in rows.items():
            db.session.add(RecetaIngrediente(producto_id=product_id, insumo_id=ingredient_id, cantidad=quantity))
        audit_event("receta", "producto", product_id, f"Receta actualizada: {product.nombre}.", rows)
        db.session.commit()
        flash("Receta guardada. Se descuenta automáticamente al cobrar.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("counter.recipes"))


@counter_bp.post("/insumos")
@feature_required("inventario.create")
def receive_ingredient():
    try:
        if not valid_csrf(request.form.get("csrf")):
            raise ValueError("Recarga la pantalla antes de registrar inventario.")
        lock_operations()
        quantity = positive_units(request.form.get("quantity"))
        ingredient_id = request.form.get("ingredient_id")
        kind = request.form.get("kind", "compra")
        if kind not in {"compra", "merma"}:
            raise ValueError("Selecciona compra o merma.")
        if ingredient_id:
            product = db.session.get(Producto, positive_units(ingredient_id))
            if not product or (not product.es_inventario and (not product.controla_stock or
                RecetaIngrediente.query.filter_by(producto_id=product.id).first())):
                raise ValueError("Selecciona un insumo o un producto que se controle por unidades.")
        else:
            name = (request.form.get("name") or "").strip()
            unit = request.form.get("unit", "unidad")
            if not name or len(name) > 100 or unit not in {"unidad", "g", "ml"} or kind != "compra":
                raise ValueError("Indica nombre y unidad del nuevo insumo.")
            category = Categoria.query.filter_by(nombre="Insumos", envia_a_cocina=False).first()
            if not category:
                category = Categoria(nombre="Insumos", envia_a_cocina=False)
                db.session.add(category)
                db.session.flush()
            product = Producto(nombre=name, categoria=category, es_inventario=True,
                precio_venta=0, precio_costo=0, stock_actual=0, maneja_stock=True,
                disponible=False, unidad_compra=unit, unidades_por_paquete=1)
            db.session.add(product)
            db.session.flush()
            db.session.add(UnidadInsumo(producto_id=product.id, unidad=unit))
        notes = (request.form.get("notes") or "").strip()
        if len(notes) > 180:
            raise ValueError("La nota admite hasta 180 caracteres.")
        cost = amount_value(request.form.get("cost", "0")) if kind == "compra" else Decimal("0")
        if kind == "merma":
            if not notes:
                raise ValueError("Escribe el motivo de la merma.")
            available = product.stock_actual - reservations().get(product.id, 0)
            if quantity > available:
                raise ValueError("La merma supera el stock disponible o reservado.")
            product.stock_actual -= quantity
        else:
            product.stock_actual += quantity
        db.session.add(MovimientoInventario(producto_id=product.id,
            tipo="compra" if kind == "compra" else "ajuste", cantidad_unidades=quantity,
            cantidad_paquetes=0, precio_unitario=cost, notas=f"{kind.capitalize()}: {notes}"[:200],
            usuario_id=current_user.id))
        audit_event(kind, "insumo", product.id, f"{kind.capitalize()}: {product.nombre}.",
            {"cantidad": quantity, "unidad": unit_for(product), "costo_total": cost, "motivo": notes})
        db.session.commit()
        flash("Inventario actualizado.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("counter.recipes"))


@counter_bp.post("/venta/<int:order_id>/entregar")
@feature_required("caja.charge")
def handover(order_id):
    if not valid_csrf(request.form.get("csrf")):
        flash("Recarga la pantalla antes de entregar.", "error")
        return redirect(url_for("counter.sale"))
    lock_operations()
    sale = db.session.get(VentaRapida, order_id)
    if not sale or any(i.estado == "pendiente" for i in sale.orden.items_activos):
        db.session.rollback()
        flash("El pedido aún está en cocina.", "error")
    else:
        for item in sale.orden.items_activos:
            item.estado = "entregado"
        audit_event("entregar", "orden", order_id, f"Pedido #{order_id} entregado.")
        db.session.commit()
        flash(f"Pedido #{order_id} entregado.", "success")
    return redirect(url_for("counter.sale"))
