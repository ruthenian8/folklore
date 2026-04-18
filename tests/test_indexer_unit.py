"""Unit tests for mysql_indexer optimizations and the admin reindex view."""

import os
import re
import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest

_REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir)


def _normalize(text):
    lowered = (text or "").lower().replace("\u0451", "\u0435")
    cleaned = re.sub(r"[^\w\s-]", " ", lowered, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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

        # First execute call should be the TRUNCATE
        first_call = fake_db.session.execute.call_args_list[0]
        sql_arg = first_call[0][0]
        assert "TRUNCATE" in str(sql_arg)

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

        execute_call = fake_db.session.execute.call_args_list[0]
        sql_arg = str(execute_call[0][0])
        assert "ON DUPLICATE KEY UPDATE" in sql_arg

    def test_chunked_inserts(self, indexer, fake_db):
        """When many rows are produced, they should be inserted in chunks."""
        text = MagicMock()
        text.id = 1
        # Create a text with many sentences
        text.raw_text = ". ".join(f"Sentence {i}" for i in range(600))
        text.year = 2020
        text.geo = None

        indexer._index_texts([text], chunk_size=100)

        # Should have multiple execute calls (one per chunk) + one commit
        execute_calls = [
            c for c in fake_db.session.execute.call_args_list
        ]
        assert len(execute_calls) >= 2  # at least 2 chunks for 600 sentences


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
