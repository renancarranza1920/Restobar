# Restobar

Sistema de operación para restaurantes: mesas, comandas, cocina, caja, inventario y preparación de facturas electrónicas de El Salvador.

La nueva interfaz usa crema, terracota y verde profundo; organiza el trabajo por áreas y mantiene los flujos existentes. Incluye carta visual, accesos rápidos, búsqueda de secciones con `Ctrl/Cmd + K`, modo oscuro, navegación móvil y notificaciones. En **Preferencias** puedes cambiar nombre, logo, paleta, movimiento y formatos de fecha y hora. Los roles de servicio, cocina y caja tienen permisos separados; los roles ya configurados se conservan al reiniciar.

## Desarrollo local

Requiere Python 3.12. Desde la raíz del repositorio:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/install_dte_reference.py
export DATABASE_URL="sqlite:///$PWD/instance/restobar.sqlite3"
python -m flask --app run run --debug
```

La aplicación crea las tablas al arrancar y conserva la base en `instance/`, un directorio ignorado por Git. No ejecutes la migración inicial de Alembic sobre una base que ya creó `create_app()`. Para desarrollo existe la cuenta inicial definida en `app/config.py`; cambia su contraseña antes de usar datos reales.

También se admite MySQL mediante `DATABASE_URL` o `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`. No subas `.env`, bases de datos, certificados ni contraseñas a Git. Configura `SECRET_KEY` y una contraseña inicial del administrador en el entorno antes del primer arranque en un servidor.

Arranque con Gunicorn:

```bash
gunicorn --no-control-socket --workers 1 --bind 127.0.0.1:5000 run:app
```

Un worker evita carreras entre los pasos de inicialización de esquema al arrancar. Aumenta los workers solo después de separar y verificar esa inicialización. El despliegue existente de Oracle se adaptará cuando se confirmen su Compose, proxy y rutas; no se añaden aquí comandos que supongan su configuración.

## Facturación electrónica

**Preparación de DTE ≠ emisión fiscal autorizada.** El módulo configura al emisor y prepara Factura 01 versión 2 o Comprobante de Crédito Fiscal 03 versión 4 desde órdenes pagadas. Valida esquemas y catálogos oficiales de los documentos compartidos por el usuario; conserva los importes y snapshots originales, incluidos los anteriores en versión 1. El verificador de esquemas funciona sin red.

Incluye un adaptador de firma, autenticación, recepción y consulta en el ambiente de pruebas `00`, desactivado por defecto. Necesita el firmador oficial, certificado y credenciales configurados de forma segura. Conserva firma y respuesta por separado; ante una recepción incierta consulta el mismo documento sin reenviarlo automáticamente. Las pruebas locales simulan los servicios: no se hicieron transmisiones a Hacienda.

La emisión en producción permanece bloqueada. La habilitación del contribuyente, acreditación, normativa completa, representación gráfica legal, contingencias e invalidaciones siguen pendientes. Los esquemas de ambos eventos están incluidos para el trabajo posterior.

Consulta [el alcance y los requisitos fiscales](docs/FACTURACION_ELECTRONICA.md).

## Verificación

```bash
python -m pip check
python -m unittest discover -s tests -v
```

Las pruebas usan bases SQLite temporales. Verifican el flujo de restaurante, permisos, personalización, cálculo de IVA, catálogos y preparación fiscal. El transporte simulado verifica aceptación, rechazos, resultados inciertos y prevención de envíos duplicados. La compatibilidad operativa con MySQL, el firmador y los servicios reales de Hacienda requieren pruebas separadas.

## Capturas de la nueva interfaz

Las capturas usan datos locales de demostración, sin información del restaurante ni credenciales reales.

- [Acceso del equipo](docs/capturas/01-acceso.png)
- [Inicio del restaurante](docs/capturas/02-inicio.png)
- [Carta visual](docs/capturas/03-carta.png)
- [Mesas y servicio](docs/capturas/04-mesas.png)
- [Cocina](docs/capturas/05-cocina.png)
- [Facturación electrónica](docs/capturas/06-facturacion.png)
- [Vista móvil](docs/capturas/07-movil.png)
- [Modo oscuro](docs/capturas/08-oscuro.png)
- [Borrador DTE con datos sintéticos](docs/capturas/09-borrador-dte.png)
- [Personalización del restaurante](docs/capturas/10-personalizacion.png)
- [Perfil fiscal con catálogos oficiales](docs/capturas/11-perfil-fiscal.png)
- [Preparación de Crédito Fiscal v4](docs/capturas/12-credito-fiscal-formulario.png)
- [Crédito Fiscal e integración de pruebas](docs/capturas/13-credito-fiscal-pruebas.png)

Los recursos gráficos son locales; no hacen falta CDN para navegar, mostrar iconos o cargar el diseño.
