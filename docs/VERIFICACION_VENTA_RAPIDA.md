# Verificación de la versión de mostrador

Fecha: 14 de octubre de 2026. Base: `56a64533eb12ad9c34152d4a0907ae2552e74799`.

## Pruebas de aplicación

- 104 pruebas con bases SQLite temporales: las 88 regresiones anteriores y 16 escenarios de mostrador, recetas, caja y conservación.
- 15 escenarios adicionales ejecutados contra MySQL 8.4 dentro de Docker. El caso de migración de archivo SQLite se omite en ese runner; la migración MySQL se comprueba por separado desde el código anterior.
- Concurrencia: dos solicitudes del mismo cobro generan un solo pago; dos ventas del último producto disponible confirman una sola venta y rechazan la otra.
- Fallos: stock insuficiente, precio cambiado, turno cambiado, efectivo insuficiente, montos no finitos, CSRF y permisos. Una falla después del consumo parcial revierte orden, inventario y pago.
- Cocina: una orden pagada se mantiene pendiente de preparación; marcar listo y consultar el historial no modifica el pago ni la entrega. La entrega es explícita en mostrador.
- Recetas: consumo y costo por porción, gramos/ml, ingredientes compartidos, reservas de pedidos anteriores, reposición directa de unidades y merma con motivo.
- Caja: tarjeta y efectivo por turno, cierres con diferencia, bloqueo de cuentas sin cobrar y recuperación de un cobro confirmado incluso después de cerrar el turno.
- Reinicio: todas las filas anteriores de una venta de mostrador permanecen iguales al volver a crear la aplicación.

Comando principal:

```bash
python -m unittest discover -s tests -v
```

El runner de MySQL requiere una base **vacía y desechable** llamada `restobar_test` en `127.0.0.1`; elimina sus tablas al terminar cada escenario. Rechaza otros nombres o destinos. La integración continua incluye ambos conjuntos de pruebas.

## Conservación desde el commit anterior

Se construyó una imagen con el código exacto de `56a6453` y se inicializó una base MySQL 8.4 desechable. Se añadieron órdenes pagadas, pagos, movimientos, auditoría, permisos modificados y evidencia fiscal sintética: JSON de versión anterior, firma, sello, respuesta e intento de consulta.

Se calcularon cantidades, columnas y hashes SHA-256 de cada tabla, se inició la versión nueva y se repitió la comparación. **Las 22 tablas anteriores conservaron exactamente su contenido.** Se crearon únicamente `guardias_operacion`, `unidades_insumo`, `recetas_ingredientes`, `consumos_venta`, `ventas_rapidas` y `cierres_turno`.

También se compararon todas las filas de la base local original contra su copia previa al trabajo: permanecen iguales. Los datos de demostración y pruebas se crearon en bases aparte.

## Navegador y capturas

Chromium con Playwright, escritorio 1440×1080 y móvil 390×844:

- Hamburguesa, papas y bebida por $9.25; efectivo recibido $10.00 y cambio $0.75.
- Cobro confirmado y dos comandas automáticas con indicaciones de cocina.
- Preparación, retiro, descuento visible de insumos y cierre de caja por $59.25.
- Formulario simple de producto, historial del corte y modo oscuro.
- Sin errores de JavaScript ni desplazamiento horizontal en móvil. El acceso móvil a cobro permite llegar al pedido sin recorrer nuevamente la carta.

Las nueve [capturas](VENTA_RAPIDA.md#capturas) utilizan exclusivamente datos sintéticos.

## Docker y preparación de Oracle

- Imagen construida con Python 3.12, dependencias verificadas y usuario UID 10001.
- MySQL 8.4 probado con aislamiento `READ COMMITTED` y serialización de cobro/turno/inventario.
- `bash -n deploy/update-preview.sh` y compilación del script de comparación correctos.
- Overlay combinado con un Compose equivalente: preserva base, red, puertos, volúmenes y configuración privada. Cambia solo imagen/construcción de app y fija Hacienda desactivada.
- El paquete registra imagen y commit anteriores, realiza respaldo, comprueba conservación y recupera app si falla una comprobación.

No hubo transmisiones reales a Hacienda ni cambios al servidor Oracle. El build local corresponde a la arquitectura del entorno de validación; la construcción nativa ARM64 se hará al ejecutar la preparación en Oracle.
