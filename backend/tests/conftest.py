import importlib.util
import sqlite3

import pytest

from app.config import REPO_ROOT
from app.db.catalog import SchemaCatalog
from app.db.connection import readonly_connection


def _load_init_db():
    spec = importlib.util.spec_from_file_location("init_db", REPO_ROOT / "database" / "init_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.init_db


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    return _load_init_db()(tmp_path_factory.mktemp("db") / "sample.db")


@pytest.fixture(scope="session")
def catalog(db_path):
    with sqlite3.connect(db_path) as conn:
        return SchemaCatalog.from_connection(conn)


@pytest.fixture
def conn(db_path):
    with readonly_connection(db_path) as c:
        yield c
