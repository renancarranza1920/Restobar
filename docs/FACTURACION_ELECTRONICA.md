# Facturación electrónica de El Salvador

Restobar prepara **Factura electrónica, tipo 01 versión 2**, y **Comprobante de Crédito Fiscal, tipo 03 versión 4**, utilizando los esquemas aportados por el usuario desde factura.gob.sv. Incluye 33 catálogos con 1,681 registros del libro de Hacienda y un adaptador para firmar, enviar y consultar documentos en el **ambiente de pruebas `00`**.

**La transmisión está desactivada por defecto. Esta implementación no habilita emisión de producción ni sustituye la autorización de Hacienda.** Preparar un JSON, superar pruebas locales y recibir un sello del ambiente de pruebas son resultados distintos. El estado `ACEPTADO_PRUEBA` solo se registra al comprobar una respuesta real de pruebas con identidad, ambiente y sello concordantes; no acredita al contribuyente para emitir a sus clientes.

## Referencias incluidas y procedencia

Los esquemas se incluyen con sus **bytes originales** del ZIP compartido. Se comprueba su SHA-256 antes de usarlos; no se descargan de un espejo comunitario durante el arranque.

| Documento | Archivo incluido | SHA-256 |
| --- | --- | --- |
| Factura 01 v2 | `app/schemas/official/fe-f-v2.json` | `2887ff3ccf5594eb1f49dcec1ce8bba134a86462f900069de1365d18ff997aff` |
| CCF 03 v4 | `app/schemas/official/fe-ccf-v4.json` | `2c2db8b3f6144bdd0d128ec2babecd38f277f8493458a06cf1b2be7b816fba32` |
| Invalidación v3 | `app/schemas/official/invalidacion-schema-v3.json` | `1ce117cb01b59da309dcbb237cc011e0c4539b3effe9cdd3c2b7794ea631693a` |
| Contingencia v4 | `app/schemas/official/contingencia-schema-v4.json` | `03fc357397dc7aaa4a8b44f887497dd1ead3a04eb71ec043bb2c0cda485bb149` |

La procedencia del ZIP, sus rutas originales y sus hashes están en [app/schemas/dte-reference.json](../app/schemas/dte-reference.json). El ZIP `svfe-json-schemas (1).zip` tiene SHA-256 `8587a7d679b22f875d1fb37be7a218c6b9ca499caa80a646e6894a4d6116ab64`.

Los catálogos se extrajeron de **Catálogos - Facturación Electrónica.xlsx**, título V1.1, SHA-256 `e86d7edc503d876564cd2bf9b251fb100f838199330c0c513048f4075669b2c6`. El resultado, [mh-catalogs.json](../app/schemas/mh-catalogs.json), conserva códigos como texto, ceros iniciales, agrupaciones y filas de origen. [mh-catalogs-provenance.json](../app/schemas/mh-catalogs-provenance.json) fija el hash del resultado y los metadatos. La modificación del libro, 29 de junio de 2026, **es un metadato de archivo, no una fecha de vigencia normativa**.

Los dos manuales compartidos declaran versión 2.0, actualización de mayo de 2026 en su historial. Las referencias de este documento corresponden a esos archivos; no se verificó de forma independiente que sean la publicación más reciente ni que Hacienda haya habilitado esas versiones para este contribuyente. Debe confirmarse antes de emisión real en el [portal oficial](https://factura.gob.sv/).

## Instalación y actualización local

Desde la raíz del repositorio, con el entorno virtual activo:

```bash
python -m pip install -r requirements.txt
python scripts/install_dte_reference.py
```

El segundo comando verifica los cuatro esquemas incluidos sin red ni credenciales. `--destination /ruta/local` permite copiarlos, manteniendo sus bytes y sin reemplazar archivos distintos. `DTE_SCHEMA_PATH`, si ya estaba configurada, solo puede apuntar a los mismos bytes de **FE v2**: una antigua ruta FE v1 impedirá preparar documentos nuevos hasta corregirla o retirar esa configuración.

Las tablas fiscales se crean de forma aditiva mediante la fábrica de la aplicación y `db.create_all()`. Los documentos guardan su JSON y snapshot originales; los envíos, el JWS y las respuestas se mantienen por separado en `FiscalEnvio`. No se borra el historial al instalar los esquemas. Antes de actualizar un servidor existente, respalda su base y verifica el arranque en una copia. Las pruebas automatizadas usan SQLite local; un servidor MySQL real requiere su propia validación.

### Direcciones: municipio y distrito son campos distintos

CAT-012 contiene departamentos; CAT-013 contiene **44 municipios** y CAT-008 **262 distritos**, además de la entrada para extranjeros `00`. Los códigos territoriales deben validarse junto a su departamento porque se repiten entre departamentos.

El perfil fiscal y los formularios incluyen departamento, municipio, distrito y complemento. La aplicación filtra municipios y distritos por departamento y valida sus códigos completos. **El libro proporcionado no declara la relación entre cada municipio y sus distritos.** No se deduce esa relación por igualdad de códigos; el usuario debe comprobar que ambos corresponden a la dirección de su inscripción. Una selección que supera las validaciones locales no demuestra por sí sola esa pertenencia.

Los perfiles anteriores deben revisarse y completar el distrito. No conviertas automáticamente el antiguo código de municipio en un distrito ni copies una dirección de ejemplo como dato real.

## Preparar una Factura o un CCF

1. En **Facturación → Perfil fiscal**, completa NIT, NRC, razón social, actividad económica, dirección, contacto y códigos de establecimiento y punto de venta según tu inscripción. Selecciona actividades y territorios de los catálogos incluidos. El formato válido no demuestra que los códigos estén asignados a tu negocio.
2. Confirma que los precios de venta **incluyen IVA del 13 %**. El preparador extrae el impuesto y conserva el importe cobrado.
3. Selecciona una orden completamente pagada y el tipo de documento. Restobar requiere nombre del cliente para todo borrador. En FE la identidad puede quedar vacía; si se ingresa, tipo y número deben completarse juntos. En CCF requiere NIT, NRC, actividad económica y dirección completa del receptor.
4. Si existen pagos registrados como «tarjeta», identifica el subtipo de cada pago: CAT-017 `02`, débito; `03`, crédito. `01` corresponde a billetes y monedas. El dato suplementario se conserva en el snapshot; no se inventa a partir de «tarjeta».
5. Confirma que toda la orden corresponde a IVA estándar, sin impuestos especiales, exenciones ni retenciones.
6. Guarda el borrador y revisa sus datos y JSON antes de cualquier prueba de envío.

Se prepara un documento por orden completa. Los pagos deben coincidir exactamente con los productos cobrados. No se prepara un documento distinto por comensal o división de cuenta. Repetir la preparación devuelve el mismo registro: no reemplaza un snapshot ya guardado. Las preparaciones y los documentos históricos no se editan ni eliminan desde este módulo.

La antigua afirmación de un umbral obligatorio de **$200** procedía del esquema FE v1 usado antes. Se retiró: los archivos proporcionados no permiten confirmar ese umbral como regla de la normativa V2. Que FE v2 admita campos nulos no elimina obligaciones legales de identificación. Los umbrales y condiciones deben verificarse en la **Normativa de Cumplimiento V2, anexo II**, antes de habilitar emisión a clientes. El nombre obligatorio y los campos adicionales requeridos en CCF son controles del preparador, no una declaración exhaustiva de esas obligaciones.

### Importes y numeración

Los cálculos usan `Decimal` y `ROUND_HALF_UP`, y los importes se serializan como números JSON exactos. En FE, la venta gravada incluye IVA y `ivaItem` extrae `ventaGravada × 0.13 / 1.13` con ocho decimales; `totalIva` se redondea después de sumar los impuestos de las líneas. CCF usa base y precio unitario sin IVA con hasta ocho decimales; calcula el tributo `20` desde las bases de las partidas antes de redondear el resumen a centavos. Ambos conservan el total pagado. Si cantidades o importes no permiten conciliar la aritmética dentro de la precisión admitida, se bloquea la preparación sin modificar el cobro.

El Manual Funcional, páginas impresas 52–54 —PDF 55–57—, establece hasta ocho decimales en el cuerpo, dos en el resumen y redondeo hacia arriba cuando el primer decimal descartado es cinco o mayor. La holgura de un centavo no se utiliza para aumentar el importe del cliente.

El número local sigue `DTE-{tipo}-{establecimiento}{puntoVenta}-{secuencia de 15 dígitos}`. El establecimiento usa `M/B/S/P` y tres números; el punto de venta, `P` y tres números, por ejemplo `M001/P001`. El contador se separa por NIT, ambiente, tipo, año de El Salvador, establecimiento y punto de venta, y se asigna transaccionalmente. El Manual Funcional, impresas 28–29 —PDF 31–32—, prohíbe repetir un número durante un año calendario. Este contador de preparación no reserva correlativos de producción ante MH.

### Operaciones que siguen fuera del preparador

Se admiten órdenes de $0.01 a $999,999.99 con IVA estándar y pago inmediato mediante efectivo o tarjeta. Se bloquean propinas y operaciones que requieren tratamiento adicional. Siguen pendientes documentos relacionados, exenciones, ventas no sujetas, retenciones, impuestos especiales, descuentos fiscales, crédito, exportaciones y ventas por cuenta de terceros.

El Manual Funcional explica cargos que no afectan la base imponible en impresas 29–30 —PDF 32–33—, pero no clasifica fiscalmente las propinas. Esa clasificación debe acordarse con el contador antes de incorporarlas. Los tributos informativos de alcohol, descritos en impresas 35–37 —PDF 38–40—, no deben sumarse automáticamente al total del restaurante; el propio manual indica que no afectan los valores del documento.

## Firma y envío en pruebas

El adaptador conecta el **firmador oficial instalado por separado** con la API de pruebas de Hacienda. El firmador, su distribución oficial, certificado y contraseña **no están incluidos ni se instalaron** con este cambio. El Manual Técnico, PDF 7–14 —impresas 4–11—, describe el servicio; Hacienda debe proporcionar o confirmar el paquete soportado y la habilitación del contribuyente.

Configura los requisitos en el almacenamiento seguro del entorno o del servidor, fuera de Git. No pegues certificados, claves privadas, contraseñas ni tokens en chat, en el perfil fiscal o en capturas.

| Variable | Uso |
| --- | --- |
| `DTE_TRANSMISSION_ENABLED` | Habilitación explícita del transporte de pruebas; desactivado por defecto. |
| `DTE_API_USER` | Usuario de aplicación del contribuyente para pruebas MH. |
| `DTE_API_PASSWORD` | Contraseña de aplicación MH, almacenada como secreto. |
| `DTE_SIGNER_URL` | Servicio de firma; por defecto `http://127.0.0.1:8113/firmardocumento/`. |
| `DTE_SIGNER_PASSWORD` | Contraseña de la clave privada utilizada por el firmador, como secreto. |

El plazo de espera se fija en ocho segundos mediante `DTE_TIMEOUT_SECONDS`; no requiere otra variable de entorno. El servicio local HTTP debe permanecer en una red privada de confianza; una instalación remota debe usar transporte seguro. No desactives verificación TLS para autenticar o enviar a Hacienda. La API MH queda fijada a `https://apitest.dtes.mh.gob.sv`, ambiente `00`; no se habilita producción cambiando el perfil o los datos de un borrador.

El envío requiere el permiso administrativo `facturacion.send_test` y un formulario con protección CSRF. Habilitar variables no envía automáticamente las órdenes: el envío es una acción manual desde el detalle fiscal. Los permisos de consulta, preparación y perfil continúan separados en `facturacion.view`, `facturacion.create` y `facturacion.configure`.

### Contratos del adaptador

Las siguientes rutas proceden del Manual Técnico suministrado. Las páginas indicadas son **páginas físicas del PDF**; en el cuerpo, la impresa equivale a PDF menos tres.

| Acción | Método y ruta | Referencia |
| --- | --- | --- |
| Autenticación MH | `POST /seguridad/auth` | PDF 19–21 |
| Recepción individual | `POST /fesv/recepciondte` | PDF 21–23 |
| Consulta de un DTE | `POST /fesv/recepcion/consultadte` | PDF 26–27 |
| Firma local | `POST /firmardocumento/` | PDF 14 |

La autenticación usa formulario `user`/`pwd`; el token devuelto puede incluir ya el prefijo `Bearer`, que se normaliza una sola vez. El firmador recibe el objeto DTE en `dteJson`, NIT, `activo` y `passwordPri`, y devuelve un JWS. La recepción MH utiliza ambiente, `idEnvio`, versión y tipo del documento, ese JWS y su código de generación. La consulta utiliza `nitEmisor`, **`tdte`** y el mismo código de generación. No se incluyen secretos en el JSON de la venta.

El snapshot sin firma permanece inmutable. El JWS y las respuestas pertenecen al registro de envío. Antes de registrar aceptación se exige una respuesta `PROCESADO`, sello no vacío y concordancia de ambiente y código de generación. Un HTTP 200 sin esos datos, una respuesta malformada o una llamada que vence no demuestran aceptación. Los rechazos y las observaciones reales deben conservarse para revisión.

| Estado del envío | Significado |
| --- | --- |
| `NUEVO` | Todavía no se ha iniciado el envío. |
| `EN_PROCESO` | Una operación adquirió el registro para evitar acciones simultáneas. |
| `ENVIANDO` | El intento se registró antes de llamar al servicio de recepción. |
| `ERROR_LOCAL` | Fallo previo al envío; puede corregirse y reintentarse manualmente. |
| `ENVIO_INCIERTO` | Se desconoce el resultado; la siguiente acción solo consulta. |
| `RECHAZADO` | Rechazo registrado; puede consultarse, pero no reenviarse el mismo snapshot inmutable. |
| `ACEPTADO_PRUEBA` | Identidad y sello de pruebas comprobados. |

Si vence el envío o no puede procesarse su respuesta, primero se consulta su estado con la misma identidad, como exige la política del Manual Técnico, PDF 17–18. Si la consulta falla o su resultado es incierto, **no se reenvía automáticamente**. No se sustituye el documento por un UUID nuevo ni se interpreta cualquier error de consulta como «no recibido». Este adaptador no efectúa reenvíos automáticos, no implementa toda la política de reintentos ni convierte una interrupción en un evento de contingencia.

### JSON de entrega y consulta pública

Después de una aceptación de pruebas comprobada, el JSON de entrega agrega `firmaElectronica` —el JWS— y `selloRecibido` —la respuesta de MH— al objeto original, conforme al Manual Técnico, PDF 34–35. El objeto enriquecido es una descarga separada; no reemplaza el snapshot ni se vuelve a enviar como objeto a firmar. **Conserva también las advertencias de borrador del objeto original firmado**: no se borran ni se reescriben tras recibir un sello de pruebas.

El enlace de consulta utiliza la URL indicada para el QR en PDF 33:

```text
https://admin.factura.gob.sv/consultaPublica?ambiente=00&codGen={codigoGeneracion}&fechaEmi={YYYY-MM-DD}
```

Los valores proceden del documento aceptado. Se conservan las mayúsculas de `consultaPublica`, `codGen` y `fechaEmi`; no se inventa un sello de producción. Esta versión muestra el enlace; la imagen QR y la representación gráfica completa quedan pendientes. La interfaz y las descargas siguen indicando el ambiente de pruebas. El preview de Restobar **no constituye una representación gráfica legal completa**: sus requisitos de campos dependen de la Normativa, anexos II/IV. Tampoco se entrega una factura legal de cliente a partir de un borrador sin firma y sello.

## Documentos anteriores y conservación

Los snapshots FE v1 existentes siguen disponibles para lectura y descarga con sus bytes y checksum originales. **No se reescriben como FE v2, no se firman ni se transmiten mediante el adaptador actual.** El detalle identifica su versión para evitar confundir el historial con una preparación nueva.

La actualización tampoco corrige datos de un documento ya aceptado mediante edición local. Es necesario un flujo fiscal explícito de reemplazo, invalidación y conservación; borrar la venta o cambiar un estado local no invalida un documento ante Hacienda.

## Pendientes para emisión real

1. **Normativa y registro.** Obtener la Normativa de Cumplimiento V2 y anexos II/IV; confirmar con Hacienda vigencia, versiones autorizadas, inscripción, obligaciones y códigos reales del emisor. Revisar con el contador identificación de receptores, clasificación de productos, propinas, impuestos y retenciones.
2. **Firmador y secretos.** Obtener el paquete oficial soportado, certificado y habilitación para pruebas. Instalar y comprobar el firmador de forma segura; verificar las vinculaciones ya disponibles antes de añadir requisitos que falten. Los valores se proporcionan mediante configuración segura, nunca en chat o Git.
3. **Pruebas con Hacienda.** Ejecutar transmisiones reales de pruebas y el procedimiento de acreditación. Las pruebas locales y las respuestas simuladas no satisfacen esos requisitos.
4. **Ciclo fiscal.** Implementar y validar contingencia, lotes, invalidaciones, correcciones, documentos adicionales, representación gráfica, entrega y conservación legal, con auditoría y recuperación de fallos.
5. **Producción.** Completar autorización y validación del despliegue, respaldos, permisos y secretos. La API de producción requiere un cambio revisado y separado; este código solo permite pruebas.

Los esquemas de eventos incluidos permiten preparar ese trabajo futuro, pero **los flujos de contingencia e invalidación todavía no están implementados**. El Manual Funcional, impresas 18–20 —PDF 21–23—, exige transmitir el evento de contingencia dentro de 24 horas del cese de la causa y los documentos informados dentro de 72 horas del sello del evento. La emisión en contingencia sigue requiriendo firma.

Para invalidación, el mismo manual, impresas 11–13 —PDF 14–16—, diferencia plazos de FE y CCF y exige, salvo excepciones, recibir primero el documento de reemplazo cuando hay corrección. La tabla fija para CCF el décimo día hábil del mes siguiente, pero un párrafo de la página impresa 12 describe un plazo distinto. Esta inconsistencia debe resolverse con la normativa antes de automatizar un calendario; no se presenta el flujo como terminado.

### Acreditación: transmisiones mínimas

El Manual Funcional, impresa 76 —PDF 79—, enumera estas **transmisiones satisfactorias en el sistema de Hacienda**:

| Documento o evento | Cantidad |
| --- | ---: |
| Factura | 90 |
| Comprobante de Crédito Fiscal | 75 |
| Nota de Remisión / Nota de Crédito | 50 por tipo |
| Nota de Débito | 25 |
| Comprobante de Retención | 50 |
| Comprobante de Liquidación | 75 |
| Documento Contable de Liquidación | 50 |
| Factura de Exportación | 90 |
| Factura de Sujeto Excluido / Comprobante de Donación | 25 por tipo |
| Invalidación / Contingencia / Retorno / Operaciones Especiales | 5 por evento |

La autorización y los tipos aplicables al contribuyente se tramitan con Hacienda. Esta tabla no significa que Restobar soporte ya todos esos documentos o eventos.

## Validación reproducible

```bash
python scripts/install_dte_reference.py
python -m unittest discover -s tests -p 'test_billing*.py' -v
python -m unittest discover -s tests -p 'test_fiscal_catalogs.py' -v
python -m unittest discover -s tests -p 'test_dte_transport.py' -v
python -m unittest discover -s tests -p 'test_fiscal_submission.py' -v
```

Las pruebas utilizan datos sintéticos y bases locales desechables. Verifican esquemas, precisión decimal, catálogos, snapshots, protección CSRF, permisos, tarjetas, integridad y concurrencia. Las pruebas del transporte usan servicios simulados para firma, autenticación, aceptación, rechazo y resultados inciertos; **no se contactó a Hacienda ni se ejecutó acreditación con esas pruebas**. Un resultado satisfactorio local no verifica credenciales, certificado, disponibilidad del firmador, registro fiscal ni producción.
