# Actualización preparada para Oracle

Objetivo: actualizar **únicamente el servicio `app` del proyecto `restobar-preview`** que ya funciona con MySQL 8.4. El servidor es Ubuntu sobre ARM64.

| Recurso | Configuración existente que se conserva |
| --- | --- |
| Código | `/home/ubuntu/proyectos/restobar-preview` |
| Compose y `.env` privado | `/home/ubuntu/proyectos/restobar-deploy` |
| Proyecto Docker | `restobar-preview` |
| Aplicación | `restobar-preview-app-1`, `127.0.0.1:8004 → 8000` |
| Base | `restobar-preview-db-1`, MySQL 8.4, sin puerto público |
| Volúmenes | `restobar-preview_database`, `restobar-preview_products`, `restobar-preview_branding` |
| Proxy | Fragmento existente de Caddy hacia `127.0.0.1:8004` |
| Fiscal | Transmisión desactivada, ambiente `00` |

El archivo [preview.override.yml](../deploy/preview.override.yml) se combina con el Compose real obtenido de las etiquetas del contenedor activo. Cambia la imagen y construcción de `app` y fija Hacienda desactivada. Conserva credenciales, puertos, red, base y volúmenes. El [Dockerfile](../deploy/Dockerfile) ejecuta con UID 10001, un worker y dos threads, como el despliegue actual; admite una CA temporal de build si el entorno utiliza proxy.

## Inspección sin aplicar cambios

Después de conectar al servidor con tu clave SSH habitual:

```bash
cd /home/ubuntu/proyectos/restobar-preview
git fetch origin rework/restobar-fast-service
release=$(git rev-parse FETCH_HEAD)
git show "$release":deploy/update-preview.sh | bash -s -- --check
```

La inspección comprueba proyecto, archivo Compose, volúmenes exclusivos, puerto local, MySQL persistente y transmisión desactivada. No modifica Docker, Caddy ni la base de datos.

## Aplicación de la versión verificada

Usa el SHA completo de la versión publicada. El script comprueba que la rama remota corresponde exactamente a ese commit y que desciende de `56a6453`.

```bash
cd /home/ubuntu/proyectos/restobar-preview
git fetch origin rework/restobar-fast-service
release=$(git rev-parse FETCH_HEAD)
git show "$release":deploy/update-preview.sh | bash -s -- --apply "$release"
```

El script:

1. Conserva el commit e imagen anteriores y copia la configuración a un directorio privado de respaldos.
2. Construye la nueva imagen mientras la aplicación anterior sigue atendiendo.
3. Pausa solo `app`, genera y verifica un dump lógico de MySQL, y respalda fotos, marca y `instance/`.
4. Compara hashes y cantidades de todas las tablas anteriores antes y después de inicializar el esquema nuevo, incluidos documentos fiscales, firmas, sellos, respuestas, intentos, auditoría y permisos. Solo se añaden las seis tablas operativas nuevas.
5. Arranca únicamente `app`, comprueba su salud y verifica que los otros contenedores conservan sus IDs y horas de arranque.

Hay una pausa breve de Restobar durante el respaldo y la comprobación. Oncosavi, Analytics e Importadora continúan funcionando. El script no reinicia sus servicios, no modifica Caddy, no ejecuta `down -v` ni limpia imágenes o volúmenes.

Si una comprobación falla después de la pausa, recupera únicamente la imagen anterior de `app` y conserva el respaldo. No restaura ni borra automáticamente la base. Una restauración SQL reemplaza datos: revísala aparte si llegara a ser necesaria. El respaldo privado queda en `/home/ubuntu/proyectos/restobar-deploy/backups/FECHA-COMMIT/` y contiene el dump, archivos, configuración y evidencias de comparación; no debe subirse a GitHub.

## Validación realizada y pendiente

Se construyó la imagen local y se verificó MySQL 8.4, transacciones concurrentes, consumo de stock y conservación del historial desde código del commit `56a6453`. También se verificó sintaxis del script y combinación del overlay con un Compose equivalente.

La ejecución en Oracle y el build nativo ARM64 quedan preparados para el servidor. Esta sesión no aplicó cambios al servidor remoto. El flujo de GitHub existente que despliega `main` permanece aparte; esta versión se publica en `rework/restobar-fast-service` y no se mezcla con `main` automáticamente.
