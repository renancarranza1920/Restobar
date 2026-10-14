"""Repeat counter scenarios against a DISPOSABLE local MySQL database.

Only accepts restobar_test on 127.0.0.1. Drops test tables after each scenario.
RESTOBAR_MYSQL_TEST_URL=mysql+pymysql://user:password@127.0.0.1/restobar_test
python tests/mysql_runner.py
"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from test_fast_service import FastServiceTests
from app import create_app
from app.config import Config
from app.extensions import db

test_url = os.environ.get("RESTOBAR_MYSQL_TEST_URL", "")
if not test_url:
    raise SystemExit("Define RESTOBAR_MYSQL_TEST_URL para una base de prueba desechable.")
parsed = make_url(test_url)
if parsed.host != "127.0.0.1" or parsed.database != "restobar_test" or parsed.drivername != "mysql+pymysql":
    raise SystemExit("Solo se permite mysql+pymysql en 127.0.0.1 con base restobar_test.")
check_engine = create_engine(test_url)
if inspect(check_engine).get_table_names():
    check_engine.dispose()
    raise SystemExit("La base restobar_test debe estar vacía antes de ejecutar el runner.")
check_engine.dispose()


class MySQLFastTests(FastServiceTests):
    def setUp(self):
        with patch.multiple(Config, SQLALCHEMY_DATABASE_URI=test_url,
            DEFAULT_ADMIN_NICKNAME=self.admin_name, DEFAULT_ADMIN_PASSWORD=self.admin_password,
            PRODUCT_UPLOAD_DIR=Path('/tmp/restobar-mysql-products'),
            BRANDING_UPLOAD_DIR=Path('/tmp/restobar-mysql-branding')):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.addCleanup(self.cleanup_mysql)

    def cleanup_mysql(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    @unittest.skip('Conservación desde esquema previo comprobada con SQLite y fingerprint de despliegue')
    def test_additive_startup_preserves_legacy_fiscal_evidence(self):
        pass


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MySQLFastTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
