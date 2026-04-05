import importlib.util
import os

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError


if importlib.util.find_spec("folklore_app.settings") is None:
    pytest.skip("folklore_app.settings is missing; skipping MySQL tests.", allow_module_level=True)

if not os.getenv("RUN_MYSQL_SEARCH_TESTS"):
    pytest.skip("Set RUN_MYSQL_SEARCH_TESTS=1 to run MySQL search tests.", allow_module_level=True)

main_app = None
db = None
Texts = None
mysql_indexer = None
tsakorpus_search = None


@pytest.fixture()
def client(monkeypatch):
    global main_app, db, Texts, mysql_indexer, tsakorpus_search

    monkeypatch.setenv("SEARCH_BACKEND", "mysql")

    from folklore_app import main_app as _main_app  # noqa: E402
    from folklore_app.models import db as _db, Texts as _Texts  # noqa: E402
    from folklore_app.search_backends import mysql_indexer as _mysql_indexer  # noqa: E402
    from folklore_app import tsakorpus_search as _tsakorpus_search  # noqa: E402,F401

    main_app = _main_app
    db = _db
    Texts = _Texts
    mysql_indexer = _mysql_indexer
    tsakorpus_search = _tsakorpus_search

    app = main_app.application
    with app.test_client() as client:
        with app.app_context():
            yield client


def _ensure_search_schema():
    try:
        db.session.execute(sql_text("SELECT 1 FROM texts_sentences LIMIT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"texts_sentences table missing or inaccessible: {exc}")


def test_search_sent_mysql(client):
    _ensure_search_schema()
    text = Texts(raw_text="First sentence. Second sentence.")
    db.session.add(text)
    db.session.commit()
    try:
        mysql_indexer.index_text(text.id)
        response = client.get("/search_sent", query_string={"txt": "Second"})
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Second" in response_text
        assert "sentence" in response_text
    finally:
        db.session.execute(
            sql_text("DELETE FROM texts_sentences WHERE text_id = :text_id"),
            {"text_id": text.id},
        )
        db.session.delete(text)
        db.session.commit()
