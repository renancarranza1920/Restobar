# Restobar

Sistema base para operar un bar o restobar con Flask y MySQL.

## Que incluye hoy

- Login con roles
- Panel de usuarios
- Mesas y ordenes
- Cocina y entregas
- Caja
- Inventario
- Tema claro y tema oscuro
- Division de cuenta por persona

## Estructura

```text
app/
  __init__.py
  config.py
  extensions.py
  models.py
  routes.py
run.py
requirements.txt
.env.example
```

## Como pensar este proyecto

- Flask sirve las vistas y maneja rutas
- Flask-Login controla sesiones y permisos por usuario
- SQLAlchemy nos deja trabajar con tablas como clases de Python
- `create_app()` arma la aplicacion completa
- Los modelos representan las tablas y los servicios guardan reglas del negocio

## Preparar el entorno

Tu carpeta ya tenia un `venv`, pero no esta completo porque le falta `pip`. Mi recomendacion es trabajar con un entorno nuevo llamado `.venv`.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Configurar variables de entorno

1. Copia `.env.example` como `.env`
2. Ajusta usuario, password y nombre de la base de datos si hace falta

## Crear o actualizar tablas en MySQL

Si vas desde cero, importa `database/schema.sql`.

Si ya tenias una base anterior creada con la primera version, ejecuta `database/update_v2.sql` para agregar:

- Estado `entregado` en los items
- Tablas para dividir cuentas

## Ejecutar el proyecto

```powershell
python -m flask --app run run
```

Luego abre:

- `http://127.0.0.1:5000/login`
- `http://127.0.0.1:5000/dashboard`
- `http://127.0.0.1:5000/api/health`

## Acceso inicial

- Usuario: `admin`
- Contrasena: `admin123`

Entra con ese usuario y cambiale la contrasena desde `Usuarios`.

## Recomendacion

Como siguiente paso natural, lo mejor es que despues agreguemos:

- reportes
- impresion de tickets
- permisos mas finos por accion
- cierre de caja con diferencias
