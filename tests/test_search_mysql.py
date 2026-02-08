import importlib.util
import os

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError


if importlib.util.find_spec("folklore_app.settings") is None:
    pytest.skip("folklore_app.settings is missing; skipping MySQL tests.", allow_module_level=True)

if not os.getenv("RUN_MYSQL_SEARCH_TESTS"):
    pytest.skip("Set RUN_MYSQL_SEARCH_TESTS=1 to run MySQL search tests.", allow_module_level=True)

os.environ["SEARCH_BACKEND"] = "mysql"

from folklore_app import main_app  # noqa: E402
from folklore_app.models import db, Texts  # noqa: E402
from folklore_app.search_backends import mysql_indexer  # noqa: E402
import folklore_app.tsakorpus_search  # noqa: E402,F401


@pytest.fixture()
def client():
    app = main_app.application
    with app.test_client() as client:
        with app.app_context():
            yield client


def _ensure_search_schema():
    try:
        db.session.execute(sql_text("SELECT 1 FROM texts_sentences LIMIT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"texts_sentences table missing or inaccessible: {exc}")

    proc_exists = db.session.execute(
        sql_text(
            """
            SELECT COUNT(*) AS total
            FROM information_schema.ROUTINES
            WHERE ROUTINE_NAME = 'sp_texts_sentences_delete_for_text'
              AND ROUTINE_TYPE = 'PROCEDURE'
            """
        )
    ).scalar()
    if not proc_exists:
        pytest.skip("Stored procedures for search indexing are missing.")


def test_search_sent_mysql(client):
    _ensure_search_schema()
    text = Texts(raw_text="First sentence. Second sentence.")
    db.session.add(text)
    db.session.commit()
    try:
        mysql_indexer.index_text(text.id)
        response = client.get("/search_sent", query_string={"txt": "Second"})
        assert response.status_code == 200
        assert "Second sentence" in response.get_data(as_text=True)
    finally:
        db.session.execute(
            sql_text("DELETE FROM texts_sentences WHERE text_id = :text_id"),
            {"text_id": text.id},
        )
        db.session.delete(text)
        db.session.commit()
