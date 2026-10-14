# Restobar para comida rápida y bebidas

La operación diaria empieza en **Vender** (`/venta`). El cajero selecciona productos, elige para llevar o comer aquí y cobra en la misma pantalla. El nombre del cliente es opcional. Los precios son finales; no se añade propina obligatoria.

1. Toca los productos y ajusta cantidades. Las indicaciones a cocina son opcionales por producto.
2. Elige efectivo o tarjeta. En efectivo, introduce lo recibido o pulsa **Exacto**; se calcula el cambio.
3. Pulsa **Cobrar**. Se guardan orden, pago, inventario y comanda en una sola transacción. El ticket queda disponible inmediatamente.

La cocina recibe automáticamente los productos de las categorías configuradas para preparación. Una venta puede estar **pagada y en cocina**. Cocina marca cada producto listo; cuando todo está listo, mostrador registra **Entregar**. Los pedidos pagados permanecen visibles en cocina incluso después del cierre de caja. Las bebidas de entrega directa se registran como entregadas al cobrarse.

## Inventario que sigue la operación

En **Recetas e insumos** (`/recetas`), registra compras, reposiciones o mermas con cantidad y costo total. Para bebidas envasadas puedes reponer directamente las unidades de venta, sin crear y transferir otro producto de bodega. Las compras tradicionales por paquetes y sus movimientos PEPS siguen disponibles en **Inventario**.

Una receta indica el consumo para **una porción**. Ejemplo: una hamburguesa consume 125 g de carne y 1 pan. Se admiten cantidades enteras en gramos, mililitros y unidades; 1 kg se registra como 1000 g. La unidad base se conserva. Al cobrar, se descuentan los ingredientes y se guarda el consumo y costo del pedido, independientemente de cambios posteriores en la receta. La receta sustituye el descuento del producto final; no se cobra inventario dos veces.

Las recetas y equivalencias no se inventan ni se aplican a ventas históricas. Configura los insumos reales de cada producto preparado. Los productos de cocina que todavía no tienen receta mantienen el comportamiento anterior, identificado en la pantalla. No se puede modificar una receta mientras existan pedidos de ese producto pendientes de cobro.

Las cantidades disponibles consideran pedidos anteriores sin pagar. El servidor vuelve a validar stock, precio y turno antes de cobrar. Si faltan insumos o cambia el precio, se rechaza toda la operación. Una venta fallida no deja pagos, comandas ni descuentos parciales.

## Caja por turno

**Caja por turno** necesita solo el fondo inicial para abrir. El sistema registra quién abrió y a qué hora. Las entradas y salidas manuales requieren motivo y monto.

Para cerrar, cuenta el efectivo real. El corte guarda ventas, cobros con tarjeta, efectivo esperado, efectivo contado y diferencia. Si hay diferencia, se exige una nota. Las cuentas antiguas abiertas deben cobrarse o cancelarse antes del cierre; los pedidos ya pagados pueden seguir preparándose. Un turno cerrado conserva su corte y no recibe nuevos cobros.

## Cobros e historial

Un reintento del mismo cobro recupera la venta confirmada sin duplicarla. Si se pierde la respuesta del servidor, se bloquean cambios al carrito y se ofrece reintentar el mismo pedido. En ese caso, comprueba el resultado antes de empezar otro pedido o recargar.

Los pedidos, pagos, roles y cierres anteriores siguen disponibles. No se cambian permisos existentes: **Vender** requiere `caja.charge`; recetas e insumos requieren los permisos de inventario. El formulario de producto se reduce a nombre, categoría, precio y disponibilidad; la foto es opcional.

Los documentos fiscales, versiones previas, firmas, sellos, respuestas e intentos se conservan. Preparar DTE sigue siendo una acción separada con sus validaciones originales. **La transmisión a Hacienda continúa desactivada** y el despliegue fija `DTE_TRANSMISSION_ENABLED=0`, `DTE_ENVIRONMENT=00`.

## Capturas

Todas las capturas utilizan una base local de demostración y datos sintéticos.

- [Venta y cobro](capturas/venta-rapida/01-venta-y-cobro.png)
- [Venta confirmada](capturas/venta-rapida/02-pedido-cobrado.png)
- [Comandas automáticas](capturas/venta-rapida/03-cocina-automatica.png)
- [Recetas, insumos y reposición de unidades](capturas/venta-rapida/04-recetas-e-insumos.png)
- [Formulario de producto](capturas/venta-rapida/05-producto-simple.png)
- [Caja por turno](capturas/venta-rapida/06-caja-por-turno.png)
- [Cierre conservado](capturas/venta-rapida/07-cierre-conservado.png)
- [Venta móvil](capturas/venta-rapida/08-venta-movil.png)
- [Modo oscuro](capturas/venta-rapida/09-venta-oscura.png)
