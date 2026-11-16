import importlib.util
import os
import threading
import uuid

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError


if not os.getenv("RUN_MYSQL_SEARCH_TESTS"):
    pytest.skip("Set RUN_MYSQL_SEARCH_TESTS=1 to run MySQL search tests.", allow_module_level=True)

if importlib.util.find_spec("folklore_app.settings") is None:
    pytest.skip("folklore_app.settings is missing; skipping MySQL tests.", allow_module_level=True)

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


def test_get_sent_context_mysql(client):
    _ensure_search_schema()
    text = Texts(raw_text="First sentence. Second sentence. Third sentence.")
    db.session.add(text)
    db.session.commit()
    try:
        mysql_indexer.index_text(text.id)
        client.get("/search_sent", query_string={"txt": "Second"})
        response = client.get("/get_sent_context/0")
        assert response.status_code == 200
        data = response.get_json()
        assert "languages" in data
        assert "prev" in data["languages"]["default"]
        assert "next" in data["languages"]["default"]
    finally:
        db.session.execute(
            sql_text("DELETE FROM texts_sentences WHERE text_id = :text_id"),
            {"text_id": text.id},
        )
        db.session.delete(text)
        db.session.commit()


def test_search_session_serializes_overlapping_requests(client):
    from folklore_app.models import SearchSession
    from flask import session

    session_id = str(uuid.uuid4())
    locked = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    errors = []

    def request(first):
        try:
            with main_app.application.test_request_context('/search'):
                session['session_id'] = session_id
                if not first:
                    assert locked.wait(5)
                data = tsakorpus_search.get_session_store()
                if first:
                    data['query'] = 'new'
                    locked.set()
                    assert release.wait(5)
                else:
                    assert data['query'] == 'new'
                    finished.set()
                tsakorpus_search.save_search_session(main_app.application.response_class())
        except Exception as exc:
            errors.append(exc)
            finished.set()

    first = threading.Thread(target=request, args=(True,))
    second = threading.Thread(target=request, args=(False,))
    first.start()
    second.start()
    try:
        assert locked.wait(5)
        assert not finished.wait(0.3)
    finally:
        release.set()
        first.join(10)
        second.join(10)
        db.session.query(SearchSession).filter_by(id=session_id).delete()
        db.session.commit()
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert finished.is_set()
