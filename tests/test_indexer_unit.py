"""Unit tests for mysql_indexer optimizations and the admin reindex view."""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir)


@pytest.fixture(autouse=True)
def _stub_modules(monkeypatch):
    """Stub folklore_app so the indexer module can be imported in isolation."""
    fake_models = types.ModuleType("folklore_app.models")
    fake_db = MagicMock()
    fake_models.db = fake_db
    fake_texts_cls = MagicMock()
    fake_models.Texts = fake_texts_cls

    fake_folklore = types.ModuleType("folklore_app")
    fake_folklore.__path__ = [os.path.join(_REPO_ROOT, "folklore_app")]
    fake_folklore.models = fake_models

    fake_backends_pkg = types.ModuleType("folklore_app.search_backends")
    fake_backends_pkg.__path__ = [
        os.path.join(_REPO_ROOT, "folklore_app", "search_backends")
    ]

    monkeypatch.setitem(sys.modules, "folklore_app", fake_folklore)
    monkeypatch.setitem(sys.modules, "folklore_app.models", fake_models)
    monkeypatch.setitem(sys.modules, "folklore_app.search_backends", fake_backends_pkg)
    # Remove cached indexer so it re-imports fresh
    monkeypatch.delitem(
        sys.modules, "folklore_app.search_backends.mysql_indexer", raising=False
    )

    yield fake_models


@pytest.fixture(autouse=True)
def _patch_sent_tokenize(monkeypatch):
    """Replace sent_tokenize with a simple split to avoid NLTK data dependency."""
    import nltk.tokenize as _nltk_tok

    def _simple_split(text):
        # Split on ". " for a rough sentence boundary; keep trailing period.
        parts = text.split(". ")
        result = []
        for i, part in enumerate(parts):
            if i < len(parts) - 1:
                result.append(part + ".")
            else:
                if part:
                    result.append(part)
        return result

    monkeypatch.setattr(_nltk_tok, "sent_tokenize", _simple_split)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def indexer(_stub_modules):
    """Import the real mysql_indexer with stubbed dependencies."""
    from folklore_app.search_backends import mysql_indexer

    # Reset schema-ensured flag so each test starts fresh.
    mysql_indexer._schema_ensured = False
    return mysql_indexer


@pytest.fixture()
def fake_db(_stub_modules):
    return _stub_modules.db


@pytest.fixture()
def fake_texts_cls(_stub_modules):
    return _stub_modules.Texts


# ---------------------------------------------------------------------------
# Test: rebuild_index returns stats
# ---------------------------------------------------------------------------


class TestRebuildIndex:
    def test_returns_total_and_indexed(self, indexer, fake_db, fake_texts_cls):
        """rebuild_index should return a dict with total and indexed counts."""
        query_mock = fake_texts_cls.query.order_by.return_value
        query_mock.count.return_value = 0

        result = indexer.rebuild_index(truncate_first=False)
        assert result == {"total": 0, "indexed": 0}

    def test_truncate_executes_truncate_sql(self, indexer, fake_db, fake_texts_cls):
        query_mock = fake_texts_cls.query.order_by.return_value
        query_mock.count.return_value = 0

        indexer.rebuild_index(truncate_first=True)

        # One of the execute calls should be the TRUNCATE
        sql_stmts = [str(c[0][0]) for c in fake_db.session.execute.call_args_list]
        assert any("TRUNCATE" in s for s in sql_stmts)

    def test_batching(self, indexer, fake_db, fake_texts_cls):
        """rebuild_index should process texts in batches."""
        text1 = MagicMock()
        text1.id = 1
        text1.raw_text = "Hello."
        text1.year = 2020
        text1.geo = None

        text2 = MagicMock()
        text2.id = 2
        text2.raw_text = "World."
        text2.year = 2021
        text2.geo = None

        query_mock = fake_texts_cls.query.order_by.return_value
        query_mock.count.return_value = 2
        query_mock.offset.return_value.limit.return_value.all.side_effect = [
            [text1, text2],
            [],
        ]

        result = indexer.rebuild_index(truncate_first=False, batch_size=5)
        assert result["total"] == 2
        assert result["indexed"] == 2


# ---------------------------------------------------------------------------
# Test: _index_texts uses UPSERT SQL
# ---------------------------------------------------------------------------


class TestIndexTextsUpsert:
    def test_upsert_sql_used(self, indexer, fake_db):
        text = MagicMock()
        text.id = 1
        text.raw_text = "Single sentence."
        text.year = 2020
        text.geo = None

        indexer._index_texts([text])

        # First call is the DELETE for stale rows; second is the UPSERT.
        sql_stmts = [str(c[0][0]) for c in fake_db.session.execute.call_args_list]
        assert any("DELETE FROM texts_sentences" in s for s in sql_stmts)
        assert any("ON DUPLICATE KEY UPDATE" in s for s in sql_stmts)

    def test_stale_rows_deleted(self, indexer, fake_db):
        """_index_texts should DELETE existing rows for each text_id before upserting."""
        text = MagicMock()
        text.id = 42
        text.raw_text = "Hello."
        text.year = 2020
        text.geo = None

        indexer._index_texts([text])

        first_call = fake_db.session.execute.call_args_list[0]
        sql_arg = str(first_call[0][0])
        assert "DELETE FROM texts_sentences" in sql_arg
        # Verify the text_id was passed as a bound parameter
        params = first_call[0][1] if len(first_call[0]) > 1 else first_call[1]
        assert 42 in params.values()

    def test_chunked_inserts(self, indexer, fake_db):
        """When many rows are produced, they should be flushed incrementally."""
        text = MagicMock()
        text.id = 1
        # Create a text with many sentences
        text.raw_text = ". ".join(f"Sentence {i}" for i in range(600))
        text.year = 2020
        text.geo = None

        indexer._index_texts([text], chunk_size=100)

        # Expect: 1 DELETE + multiple UPSERT chunks + 1 commit
        upsert_calls = [
            c for c in fake_db.session.execute.call_args_list
            if "ON DUPLICATE KEY UPDATE" in str(c[0][0])
        ]
        assert len(upsert_calls) >= 2  # at least 2 chunks for 600 sentences


# ---------------------------------------------------------------------------
# Test: get_indexed_text_count
# ---------------------------------------------------------------------------


class TestGetIndexedTextCount:
    def test_returns_count(self, indexer, fake_db):
        fake_db.session.execute.return_value.scalar.return_value = 42
        assert indexer.get_indexed_text_count() == 42

    def test_returns_zero_for_none(self, indexer, fake_db):
        fake_db.session.execute.return_value.scalar.return_value = None
        assert indexer.get_indexed_text_count() == 0


# ---------------------------------------------------------------------------
# Test: ensure_schema
# ---------------------------------------------------------------------------


class TestEnsureSchema:
    def _reset_flag(self, indexer):
        """Reset the module-level _schema_ensured flag between tests."""
        indexer._schema_ensured = False

    def test_ensure_schema_executes_create_table(self, indexer, fake_db):
        self._reset_flag(indexer)
        fake_db.session.execute.reset_mock()
        fake_db.session.commit.reset_mock()

        indexer.ensure_schema()

        sql_arg = str(fake_db.session.execute.call_args_list[0][0][0])
        assert "CREATE TABLE IF NOT EXISTS texts_sentences" in sql_arg
        fake_db.session.commit.assert_called()

    def test_ensure_schema_runs_only_once(self, indexer, fake_db):
        self._reset_flag(indexer)
        fake_db.session.execute.reset_mock()
        fake_db.session.commit.reset_mock()

        indexer.ensure_schema()
        indexer.ensure_schema()

        # DDL should have been executed exactly once
        create_calls = [
            c for c in fake_db.session.execute.call_args_list
            if "CREATE TABLE" in str(c[0][0])
        ]
        assert len(create_calls) == 1

    def test_public_functions_call_ensure_schema(self, indexer, fake_db, fake_texts_cls):
        """All public entry points should trigger ensure_schema."""
        self._reset_flag(indexer)
        fake_db.session.execute.reset_mock()

        # get_indexed_text_count
        fake_db.session.execute.return_value.scalar.return_value = 0
        indexer.get_indexed_text_count()

        create_calls = [
            c for c in fake_db.session.execute.call_args_list
            if "CREATE TABLE" in str(c[0][0])
        ]
        assert len(create_calls) == 1

    def test_rebuild_index_calls_ensure_schema(self, indexer, fake_db, fake_texts_cls):
        self._reset_flag(indexer)
        fake_db.session.execute.reset_mock()

        query_mock = fake_texts_cls.query.order_by.return_value
        query_mock.count.return_value = 0

        indexer.rebuild_index()

        create_calls = [
            c for c in fake_db.session.execute.call_args_list
            if "CREATE TABLE" in str(c[0][0])
        ]
        assert len(create_calls) == 1

    def test_index_text_calls_ensure_schema(self, indexer, fake_db, fake_texts_cls):
        self._reset_flag(indexer)
        fake_db.session.execute.reset_mock()

        fake_text = MagicMock()
        fake_text.id = 1
        fake_text.raw_text = "Hello."
        fake_text.year = 2020
        fake_text.geo = None
        fake_texts_cls.query.filter_by.return_value.one_or_none.return_value = fake_text

        indexer.index_text(1)

        create_calls = [
            c for c in fake_db.session.execute.call_args_list
            if "CREATE TABLE" in str(c[0][0])
        ]
        assert len(create_calls) == 1
