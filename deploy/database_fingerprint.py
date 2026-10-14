"""Read-only database evidence. Prints hashes/counts, never rows or secrets.

Run inside the app container with stdin: python - [--initialize]
--initialize applies the application's additive bootstrap before collecting.
"""
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, inspect, MetaData, Table, select
from app.config import Config


def canonical(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


if Config.DTE_TRANSMISSION_ENABLED:
    raise SystemExit("Hacienda debe permanecer desactivada. No se inicializó la aplicación.")

if "--initialize" in sys.argv:
    from app import create_app
    from app.extensions import db
    app = create_app()
    with app.app_context():
        db.session.remove()
        db.engine.dispose()

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
tables = {}
with engine.connect() as connection:
    for name in sorted(inspect(connection).get_table_names()):
        table = Table(name, MetaData(), autoload_with=connection)
        columns = sorted(table.columns, key=lambda c: c.name)
        query = select(*columns)
        primary = list(table.primary_key.columns)
        if primary:
            query = query.order_by(*primary)
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(query):
            encoded = json.dumps([canonical(v) for v in row], ensure_ascii=False, separators=(",", ":"))
            digest.update(encoded.encode("utf-8")); digest.update(b"\n"); count += 1
        tables[name] = {"count": count, "sha256": digest.hexdigest(), "columns": [c.name for c in columns]}
engine.dispose()
print(json.dumps({"tables": tables, "dte_transmission_enabled": False}, sort_keys=True))
