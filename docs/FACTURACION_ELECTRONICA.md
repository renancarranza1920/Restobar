# Facturación electrónica de El Salvador

Restobar prepara **borradores de Factura de consumidor final, tipo 01, versión 1 de referencia** a partir de órdenes completamente pagadas. Genera JSON, separa el IVA incluido en los precios, comprueba una referencia de esquema JSON y conserva un snapshot inmutable de la venta, el emisor, el receptor y los pagos.

**Este módulo no emite un DTE con validez tributaria.** No firma, no autentica ante Hacienda, no transmite documentos y no genera ni inventa sellos de recepción. Todos los documentos usan ambiente `00` de pruebas, observaciones de borrador y un número de control **local provisional**. No existe una opción para activar producción simplemente cambiando una variable.

## Instalar la referencia local

Desde la raíz del repositorio y dentro del entorno virtual:

```bash
python -m pip install -r requirements.txt
python scripts/install_dte_reference.py
```

El instalador descarga exclusivamente una referencia pública del esquema a `instance/dte-schemas/dte-fe-v1.json`, ruta ignorada por Git. Comprueba SHA-256 y mantiene la verificación TLS y la configuración de proxy existente. No transmite datos fiscales ni credenciales. No sobrescribe una referencia existente con un checksum distinto. La configuración opcional `DTE_SCHEMA_PATH` permite seleccionar otra ruta local, pero sus bytes deben seguir coincidiendo con la referencia fijada; no sirve para saltarse la verificación.

El acceso de descarga requiere `raw.githubusercontent.com`. Para investigar la fuente y preparar una futura integración se necesita acceso a `factura.gob.sv` y a los dominios oficiales que Hacienda confirme; no debe reemplazarse una lista de red existente ni desactivarse TLS. En el entorno de trabajo se intentó consultar el sitio oficial y el proxy respondió `403`; los dominios oficiales siguen pendientes de acceso efectivo.

Los modelos `documentos_fiscales` y `secuencias_borrador_dte` son tablas nuevas y aditivas. La fábrica actual de la aplicación las crea mediante `db.create_all()`. No se borran tablas ni se cambia el historial existente. En MySQL, los snapshots utilizan `LONGTEXT` para admitir los tamaños permitidos por la referencia. Haz respaldo y valida este arranque en una copia del servidor antes del despliegue.

## Usar el preparador

1. En **Facturación → Perfil fiscal**, ingresa la razón social, NIT, NRC, actividad económica, dirección, contacto y códigos del establecimiento y punto de venta. Obtén los códigos de tu inscripción y de los catálogos oficiales; el formato válido no garantiza que pertenezcan a tu registro. Los identificadores asignados por MH son opcionales en esta referencia y no se deducen de los códigos internos.
2. Confirma que los precios registrados **ya incluyen IVA del 13 %**. El preparador extrae el IVA y conserva el importe cobrado; no aumenta el precio.
3. Selecciona una orden pagada sin borrador. Ingresa el nombre del cliente y, cuando aplique, su identidad, contacto y dirección. La referencia v1 requiere tipo y número de documento al llegar a `montoTotalOperacion >= 200`; esta regla procede del esquema de referencia, no de una verificación independiente de la normativa vigente. DUI conserva el guion; NIT se ingresa sin guiones.
4. Si hay pagos registrados como «tarjeta», confirma el subtipo de **cada pago**: `02` crédito o `03` débito, según el catálogo comunitario consultado. Verifica CAT-017 con Hacienda antes de implementar emisión. La aplicación conserva ese dato suplementario en el snapshot y no lo inventa a partir de «tarjeta».
5. Confirma que todos los productos corresponden a IVA estándar, sin impuestos especiales, exenciones ni retenciones. La aplicación no conoce la clasificación fiscal de tus productos; esa revisión es necesaria.
6. Guarda el borrador y descarga su JSON. La descarga conserva la estructura de la referencia e incluye la advertencia de borrador dentro de `extension.observaciones` y `apendice`; no incluye firmas ni un `selloRecibido` ficticio.

Se admite una factura por orden completa. Si la cuenta se dividió, los pagos deben sumar exactamente el total de productos de la orden; todavía no se emite una factura independiente por división o comensal. Una petición repetida devuelve el mismo borrador y nunca reemplaza datos ya preparados. Los borradores no se pueden editar ni eliminar desde este módulo. Es una protección del historial, no un mecanismo de corrección fiscal: antes de emisión se debe implementar un flujo revisado para corregir preparaciones y gestionar documentos transmitidos conforme a MH.

## Qué se valida y qué queda pendiente

El preparador exige:

- Autenticación y permisos `facturacion.view`, `facturacion.create` y `facturacion.configure`; los formularios fiscales tienen protección CSRF propia.
- Orden pagada, importe positivo, productos activos cobrados, pagos coincidentes y ningún producto cancelado en el snapshot. El rango actual es $0.01 a $999,999.99.
- Perfil completo, identidad del receptor compatible con la referencia y códigos de dirección con formato estricto en el servidor.
- Matemática con `Decimal`: `ivaItem = ventaGravada × 0.13 / 1.13`, redondeado a centavos con `ROUND_HALF_UP`. `totalIva` suma los IVA de las líneas; por eso puede diferir en centavos de redondear el IVA de todo el total una sola vez. La base que muestra la pantalla es `total - totalIva`.
- Esquema JSON Draft 7, incluidos sus campos requeridos, límites, patrones, condiciones y formatos. Los decimales se guardan como números JSON exactos.
- Integridad SHA-256 del JSON al visualizar y descargar. Restricción única por orden, código de generación único y contador transaccional protegido ante peticiones simultáneas.

No se admiten propinas, CCF tipo 03, documentos relacionados, operaciones exentas/no sujetas, retenciones, impuestos especiales o ad valorem, descuentos fiscales, crédito, exportaciones, ventas de terceros, contingencias ni invalidaciones. Las órdenes con propina se bloquean hasta definir y desarrollar su tratamiento fiscal. Bebidas u otros productos con impuestos adicionales deben quedar fuera de este preparador aunque la orden esté pagada.

El contador es propio de los borradores, separado por NIT, año, establecimiento y punto de venta. La numeración no constituye autorización, reserva ni correlativo de producción ante MH. El UUID es un identificador local de preparación. **Validar JSON no equivale a aceptar la operación tributaria**, identificar al contribuyente correctamente, verificar un catálogo actualizado o superar certificación.

## Evidencia y procedencia

La fuente oficial que debe prevalecer es [Ministerio de Hacienda, portal de factura electrónica](https://factura.gob.sv/), apartado de información técnica y funcional y sus esquemas y catálogos. No se pudo verificar directamente su contenido durante esta implementación debido a la restricción de red del entorno.

Para la comprobación estructural se consultó el [repositorio comunitario herson/dte-json-schemas](https://github.com/herson/dte-json-schemas), que declara publicar copias de los esquemas MH. Es independiente y no está afiliado a Hacienda. Se fijó:

| Dato | Valor |
| --- | --- |
| Commit de referencia | `01c62d14dc1126129e45ad282fca5ab18e8e7c6f` |
| Archivo | `DTE-FE-v1.json` |
| SHA-256 | `748673c0f2d45d84e6b13a21d2ba411eb731ce199eb946dc33ca9b995571f0c1` |
| Versión y documento | `identificacion.version = 1`, `tipoDte = "01"` |
| Procedencia registrada | [app/schemas/dte-reference.json](../app/schemas/dte-reference.json) |

La descarga permanece local porque no se encontró una licencia de redistribución en ese espejo; sus bytes no se incluyen en Git. El checksum garantiza que se usa la referencia fijada, **no su autenticidad como publicación actual de MH**. Ese repositorio también incluye versiones FE v2 y CCF v4 y anuncia cambios de normativa. No se confirmó oficialmente su vigencia ni fechas de transición, por lo que no se implementaron ni se presentan fechas como hechos verificados. Antes de emisión debe obtenerse y compararse el paquete vigente de MH y actualizarse código, pruebas y referencia mediante un cambio revisado.

Los nombres de pago crédito/débito se contrastaron con [DIAL-Studio/odoo-l10n-el-salvador, CAT-017](https://github.com/DIAL-Studio/odoo-l10n-el-salvador/blob/7809f5d29b2f71ee4d09951e35afe21eb5304bbe/data/l10n_sv.forma_pago.csv), commit `7809f5d29b2f71ee4d09951e35afe21eb5304bbe`. Se utilizaron los códigos como datos de referencia, sin copiar código de esa implementación. Es otra fuente comunitaria y los catálogos oficiales siguen pendientes de comprobación. Por la misma razón, la pantalla de perfil pide elegir CAT-009 según la inscripción MH y no atribuye nombres a códigos no confirmados.

## Para implementar emisión real

1. **Habilitación:** confirmar con MH tu inscripción, NIT/NRC, obligaciones, actividad, sucursales/puntos y autorización para usar el sistema de transmisión. Obtener documentación y catálogos vigentes y acordar con tu contador los impuestos que corresponden a cada producto, propinas y receptores.
2. **Firma:** obtener certificados y acceso al firmador oficial o a un proveedor habilitado conforme a MH. Certificados, contraseñas y tokens se guardan fuera de Git y se inyectan de forma segura. No pegarlos en chat, en este perfil ni en archivos rastreados.
3. **Pruebas y certificación:** implementar el protocolo oficial de autenticación y recepción en pruebas, validación actual, firma, estados, respuestas reales, reintentos idempotentes, trazabilidad y conservación de documentos. Usar las URL y contratos que MH confirme; esta implementación no inventa endpoints de API.
4. **Ciclo fiscal completo:** cubrir contingencias, invalidaciones y correcciones autorizadas, documentos adicionales necesarios, representación gráfica y consulta/QR conforme a la normativa, entrega al cliente y conservación legal. No fabricar respuestas cuando Hacienda rechace o no esté disponible.
5. **Producción:** completar certificación y habilitación, verificar backup, permisos y secretos; después conectar producción mediante un cambio de código y configuración revisado. El envío debe registrar el sello y estado reales y no convertir automáticamente un borrador en «aceptado».

No se solicitaron certificados ni credenciales para generar los borradores. Cuando se implemente el transporte, comprueba primero las vinculaciones ya disponibles y solicita únicamente lo que aún falte en la configuración segura del servidor.

## Validación reproducible

```bash
python scripts/install_dte_reference.py
python -m unittest discover -s tests -p 'test_billing*.py' -v
```

Las pruebas usan datos sintéticos y bases SQLite desechables, sin conexión a Hacienda ni a la base configurada de producción. Verifican esquema y decimales, snapshots, protección CSRF y permisos, idempotencia, controles fiscales, tarjetas, integridad y concurrencia. La compatibilidad DDL de `LONGTEXT` se prepara para MySQL, pero una base MySQL real y la recepción de MH requieren validación independiente.
