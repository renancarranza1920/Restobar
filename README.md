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

**Preparación de DTE ≠ emisión fiscal autorizada.** El módulo permite configurar al emisor, preparar una Factura tipo 01 desde una orden pagada, validar un esquema de referencia y descargar su JSON como borrador. Conserva una instantánea de importes y evita preparar dos documentos para la misma orden.

La firma electrónica, transmisión, recepción del sello, contingencias, invalidaciones y homologación con Hacienda quedan pendientes. No se inventan sellos ni se presentan tickets internos como DTE válidos. El esquema de referencia instalado debe contrastarse con la versión vigente de Hacienda antes de una integración real.

Consulta [el alcance y los requisitos fiscales](docs/FACTURACION_ELECTRONICA.md).

## Verificación

```bash
python -m pip check
python -m unittest discover -s tests -v
```

Las pruebas usan bases SQLite temporales. Verifican autenticación, permisos, personalización, conservación de roles, un flujo de caja a cobro y preparación de borradores fiscales. La compatibilidad operativa con MySQL y la emisión real requieren pruebas separadas en sus respectivos entornos.

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

Los recursos gráficos son locales; no hacen falta CDN para navegar, mostrar iconos o cargar el diseño.
