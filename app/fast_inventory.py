"""Inventory requirements shared by counter sales and existing unpaid orders."""
from decimal import Decimal
from .extensions import db
from .models import Orden, OrdenItem, Producto, MovimientoInventario
from .fast_models import RecetaIngrediente, ConsumoVenta, UnidadInsumo, GuardiaOperacion


def lock_operations():
    # UPDATE serializes transactions on SQLite and MySQL, including the no-open-
    # shift case. Every counter sale and shift transition takes this same lock.
    db.session.execute(db.update(GuardiaOperacion).where(
        GuardiaOperacion.clave == "caja").values(revision=GuardiaOperacion.revision + 1))
    db.session.expire_all()


def unit_for(product):
    unit = db.session.get(UnidadInsumo, product.id)
    return unit.unidad if unit else "unidad"


def requirements(product, quantity):
    recipe = RecetaIngrediente.query.filter_by(producto_id=product.id).order_by(
        RecetaIngrediente.insumo_id).all()
    if recipe:
        return [(row.insumo, row.cantidad * quantity) for row in recipe]
    if product.controla_stock:
        return [(product, quantity)]
    return []


def reservations(exclude_order=None):
    query = OrdenItem.query.join(Orden).filter(
        Orden.estado != "cancelada", OrdenItem.estado != "cancelado",
        OrdenItem.pagado.is_(False))
    if exclude_order is not None:
        query = query.filter(OrdenItem.orden_id != exclude_order)
    reserved = {}
    for item in query.all():
        for product, quantity in requirements(item.producto, item.cantidad):
            reserved[product.id] = reserved.get(product.id, 0) + quantity
    return reserved


def demand_errors(lines, exclude_order=None):
    reserved = reservations(exclude_order)
    totals = {}
    for line in lines:
        for product, quantity in requirements(line["product"], line["quantity"]):
            old = totals.get(product.id, (product, 0))
            totals[product.id] = (product, old[1] + quantity)
    errors = []
    for product, quantity in totals.values():
        available = max(product.stock_actual - reserved.get(product.id, 0), 0)
        if quantity > available:
            errors.append(f"{product.nombre}: necesitas {quantity} {unit_for(product)}; quedan {available} disponibles en stock.")
    return errors


def portions_available(product, reserved=None):
    needs = requirements(product, 1)
    if not needs:
        return None
    reserved = reservations() if reserved is None else reserved
    return min(max(p.stock_actual - reserved.get(p.id, 0), 0) // q for p, q in needs)


def consume_item(item):
    from .services import inventory_fifo_consumption, money
    if item.pagado or item.estado == "cancelado":
        return
    total_cost = Decimal("0")
    needs = requirements(item.producto, item.cantidad)
    for product, quantity in needs:
        cost = inventory_fifo_consumption(product, quantity)["cost"]
        changed = db.session.execute(db.update(Producto).where(
            Producto.id == product.id, Producto.stock_actual >= quantity).values(
                stock_actual=Producto.stock_actual - quantity),
            execution_options={"synchronize_session": "fetch"})
        if changed.rowcount != 1:
            raise ValueError(f"Stock insuficiente de {product.nombre}. Revisa el pedido.")
        db.session.add(ConsumoVenta(item_id=item.id, insumo_id=product.id,
            nombre=product.nombre, unidad=unit_for(product), cantidad=quantity, costo=cost))
        db.session.add(MovimientoInventario(producto_id=product.id, tipo="venta",
            cantidad_unidades=quantity, precio_unitario=money(cost / quantity),
            notas=f"Consumo de orden #{item.orden_id}, item #{item.id}",
            usuario_id=item.orden.usuario_id))
        total_cost += cost
    if needs:
        item.costo_unitario = money(total_cost / item.cantidad)
    item.pagado = True
