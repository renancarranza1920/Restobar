"""Additive operations tables. Existing orders and fiscal snapshots stay intact."""
from datetime import datetime
from .extensions import db


class GuardiaOperacion(db.Model):
    __tablename__ = "guardias_operacion"
    clave = db.Column(db.String(40), primary_key=True)
    revision = db.Column(db.Integer, default=0, nullable=False)


class UnidadInsumo(db.Model):
    __tablename__ = "unidades_insumo"
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), primary_key=True)
    unidad = db.Column(db.String(10), nullable=False)


class RecetaIngrediente(db.Model):
    __tablename__ = "recetas_ingredientes"
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    __table_args__ = (
        db.UniqueConstraint("producto_id", "insumo_id"),
        db.CheckConstraint("cantidad > 0", name="receta_cantidad_positiva"),
    )
    insumo = db.relationship("Producto", foreign_keys=[insumo_id])


class ConsumoVenta(db.Model):
    """Snapshot independent of later recipe edits; never recomputed for paid items."""
    __tablename__ = "consumos_venta"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("orden_items.id"), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    unidad = db.Column(db.String(10), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    costo = db.Column(db.Numeric(14, 2), nullable=False)
    __table_args__ = (db.UniqueConstraint("item_id", "insumo_id"),)


class VentaRapida(db.Model):
    __tablename__ = "ventas_rapidas"
    orden_id = db.Column(db.Integer, db.ForeignKey("ordenes.id"), primary_key=True)
    clave = db.Column(db.String(36), unique=True, nullable=False)
    canal = db.Column(db.String(20), nullable=False)
    recibido = db.Column(db.Numeric(10, 2), nullable=False)
    cambio = db.Column(db.Numeric(10, 2), nullable=False)
    orden = db.relationship("Orden", backref=db.backref("venta_rapida", uselist=False))


class CierreTurno(db.Model):
    __tablename__ = "cierres_turno"
    sesion_id = db.Column(db.Integer, db.ForeignKey("sesiones_caja.id"), primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    esperado = db.Column(db.Numeric(14, 2), nullable=False)
    contado = db.Column(db.Numeric(14, 2), nullable=False)
    diferencia = db.Column(db.Numeric(14, 2), nullable=False)
    ventas = db.Column(db.Numeric(14, 2), nullable=False)
    tarjetas = db.Column(db.Numeric(14, 2), nullable=False)
    notas = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sesion = db.relationship("SesionCaja", backref=db.backref("corte", uselist=False))
