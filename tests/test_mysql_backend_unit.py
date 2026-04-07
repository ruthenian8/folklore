"""Unit tests for MySQLSearchBackend.

These tests mock the database layer so they run without a live MySQL
instance and without ``folklore_app.settings`` being present.
"""

import os
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir)


def _normalize(text):
    lowered = (text or "").lower().replace("\u0451", "\u0435")
    cleaned = re.sub(r"[^\w\s-]", " ", lowered, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@pytest.fixture(autouse=True)
def _stub_modules(monkeypatch):
    """Temporarily stub folklore_app and its submodules in sys.modules.

    Uses monkeypatch so original entries are restored after every test,
    preventing interference with other test modules.
    """
    fake_models = types.ModuleType("folklore_app.models")
    fake_models.db = MagicMock()
    fake_models.Texts = MagicMock()

    fake_folklore = types.ModuleType("folklore_app")
    fake_folklore.__path__ = [os.path.join(_REPO_ROOT, "folklore_app")]
    fake_folklore.models = fake_models

    fake_indexer = types.ModuleType("folklore_app.search_backends.mysql_indexer")
    fake_indexer.normalize = _normalize

    fake_backends_pkg = types.ModuleType("folklore_app.search_backends")
    fake_backends_pkg.__path__ = [
        os.path.join(_REPO_ROOT, "folklore_app", "search_backends")
    ]
    fake_backends_pkg.mysql_indexer = fake_indexer

    monkeypatch.setitem(sys.modules, "folklore_app", fake_folklore)
    monkeypatch.setitem(sys.modules, "folklore_app.models", fake_models)
    monkeypatch.setitem(sys.modules, "folklore_app.search_backends", fake_backends_pkg)
    monkeypatch.setitem(
        sys.modules, "folklore_app.search_backends.mysql_indexer", fake_indexer
    )

    # Remove any cached mysql_backend module so it re-imports with the stubs.
    monkeypatch.delitem(
        sys.modules, "folklore_app.search_backends.mysql_backend", raising=False
    )

    yield fake_models


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend(_stub_modules):
    from folklore_app.search_backends.mysql_backend import MySQLSearchBackend

    return MySQLSearchBackend(
        max_page_size=50,
        settings={
            "languages": ["russian"],
            "media": True,
            "max_context_expand": 3,
        },
    )


@pytest.fixture()
def backend_defaults(_stub_modules):
    """Backend created without settings (backwards-compatible mode)."""
    from folklore_app.search_backends.mysql_backend import MySQLSearchBackend

    return MySQLSearchBackend(max_page_size=100)


# ---------------------------------------------------------------------------
# Constructor / settings propagation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_settings_propagated(self, backend):
        assert backend._languages == ["russian"]
        assert backend._media is True
        assert backend._max_context_expand == 3

    def test_defaults_without_settings(self, backend_defaults):
        assert backend_defaults._languages == ["default"]
        assert backend_defaults._media is False
        assert backend_defaults._max_context_expand == 6


# ---------------------------------------------------------------------------
# _build_meta_filter
# ---------------------------------------------------------------------------


class TestBuildMetaFilter:
    def test_no_filters(self, backend):
        clause, params = backend._build_meta_filter({})
        assert clause == ""
        assert params == {}

    def test_year_from(self, backend):
        clause, params = backend._build_meta_filter({"year_from": "1990"})
        assert ":year_from" in clause
        assert params["year_from"] == 1990

    def test_year_to(self, backend):
        clause, params = backend._build_meta_filter({"year_to": "2020"})
        assert ":year_to" in clause
        assert params["year_to"] == 2020

    def test_year_range(self, backend):
        clause, params = backend._build_meta_filter(
            {"year_from": "1990", "year_to": "2020"}
        )
        assert "year_from" in params
        assert "year_to" in params
        assert "year >= :year_from" in clause
        assert "year <= :year_to" in clause

    def test_geo(self, backend):
        clause, params = backend._build_meta_filter({"geo": "Moscow"})
        assert "geo = :geo" in clause
        assert params["geo"] == "Moscow"

    def test_combined(self, backend):
        clause, params = backend._build_meta_filter(
            {"year_from": "1990", "geo": "Moscow"}
        )
        assert "year_from" in params
        assert "geo" in params

    def test_invalid_year_ignored(self, backend):
        clause, params = backend._build_meta_filter({"year_from": "abc"})
        assert clause == ""
        assert params == {}


# ---------------------------------------------------------------------------
# _empty_results uses settings
# ---------------------------------------------------------------------------


class TestEmptyResults:
    def test_uses_settings_languages(self, backend):
        r = backend._empty_results(1, 10)
        assert r["languages"] == ["russian"]
        assert r["media"] is True
        assert r["message"] == "Nothing found."
        assert r["too_many_hits"] is False

    def test_defaults_without_settings(self, backend_defaults):
        r = backend_defaults._empty_results(1, 10)
        assert r["languages"] == ["default"]
        assert r["media"] is False


# ---------------------------------------------------------------------------
# _build_context uses settings language
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_uses_settings_lang_key(self, backend):
        row = types.MappingProxyType(
            {"text_id": 1, "sent_no": 0, "content": "hello",
             "content_norm": "hello"}
        )
        ctx = backend._build_context(row, ["hello"])
        assert "russian" in ctx["languages"]
        assert "default" not in ctx["languages"]

    def test_default_lang_key(self, backend_defaults):
        row = types.MappingProxyType(
            {"text_id": 1, "sent_no": 0, "content": "hello",
             "content_norm": "hello"}
        )
        ctx = backend_defaults._build_context(row, ["hello"])
        assert "default" in ctx["languages"]


# ---------------------------------------------------------------------------
# search_sentences — empty query
# ---------------------------------------------------------------------------


class TestSearchSentencesEmptyQuery:
    def test_empty_query_returns_nothing_found(self, backend):
        session = {}
        result = backend.search_sentences({"txt": ""}, 1, session)
        assert result["data"]["message"] == "Nothing found."
        assert result["data"]["n_sentences"] == 0
        assert result["data"]["languages"] == ["russian"]
        assert result["max_page_number"] == 1


# ---------------------------------------------------------------------------
# search_sentences — with results
# ---------------------------------------------------------------------------


class TestSearchSentencesWithResults:
    @staticmethod
    def _setup_db(fake_models, total_rows, total_docs, rows):
        mock_db = fake_models.db
        count_result1 = MagicMock()
        count_result1.scalar.return_value = total_rows
        count_result2 = MagicMock()
        count_result2.scalar.return_value = total_docs
        select_result = MagicMock()
        select_result.mappings.return_value = rows
        mock_db.session.execute.side_effect = [
            count_result1, count_result2, select_result,
        ]

    def test_result_structure(self, backend, _stub_modules):
        rows = [
            {"id": 1, "text_id": 10, "sent_no": 0, "content": "Hello world",
             "content_norm": "hello world", "score": 1.0},
        ]
        self._setup_db(_stub_modules, 1, 1, rows)

        session = {}
        result = backend.search_sentences({"txt": "hello"}, 1, session)
        data = result["data"]

        assert "contexts" in data
        assert data["n_sentences"] == 1
        assert data["n_docs"] == 1
        assert data["page"] == 1
        assert data["timeout"] is False
        assert data["message"] == ""
        assert data["languages"] == ["russian"]
        assert data["media"] is True
        assert data["too_many_hits"] is False
        assert result["max_page_number"] >= 1

    def test_session_populated(self, backend, _stub_modules):
        rows = [
            {"id": 1, "text_id": 10, "sent_no": 0, "content": "Test",
             "content_norm": "test", "score": 1.0},
        ]
        self._setup_db(_stub_modules, 1, 1, rows)

        session = {}
        backend.search_sentences({"txt": "test"}, 1, session)

        assert "mysql_hit_ids" in session
        assert "mysql_last_terms" in session
        assert "mysql_times_expanded" in session
        assert len(session["mysql_times_expanded"]) == 1
        assert session["mysql_times_expanded"][0] == 0

    def test_subcorpus_enabled_when_meta_filter(self, backend, _stub_modules):
        rows = [
            {"id": 1, "text_id": 10, "sent_no": 0, "content": "Test",
             "content_norm": "test", "score": 1.0},
        ]
        self._setup_db(_stub_modules, 1, 1, rows)

        session = {}
        result = backend.search_sentences(
            {"txt": "test", "year_from": "2000"}, 1, session
        )
        assert result["data"]["subcorpus_enabled"] is True


# ---------------------------------------------------------------------------
# get_sentence_context — expansion limiting and outward expansion
# ---------------------------------------------------------------------------


class TestGetSentenceContext:
    def test_returns_empty_for_invalid_index(self, backend):
        session = {"mysql_hit_ids": [], "mysql_times_expanded": []}
        assert backend.get_sentence_context(-1, session) == {}
        assert backend.get_sentence_context(0, session) == {}

    def test_context_expansion_limit(self, backend, _stub_modules):
        session = {
            "mysql_hit_ids": [{"text_id": 1, "sent_no": 5}],
            "mysql_last_terms": ["word"],
            "mysql_times_expanded": [0],
        }
        mock_db = _stub_modules.db
        mock_db.session.execute.return_value.scalar.return_value = (
            "some sentence"
        )

        # Expand up to max_context_expand (3 for this backend)
        for _ in range(3):
            result = backend.get_sentence_context(0, session)
            assert result != {}
            assert "languages" in result
            assert "russian" in result["languages"]

        # 4th expansion should be blocked
        result = backend.get_sentence_context(0, session)
        assert result == {}

    def test_expands_outward(self, backend, _stub_modules):
        """Each expansion should fetch further neighbors, not the same ones."""
        session = {
            "mysql_hit_ids": [{"text_id": 1, "sent_no": 10}],
            "mysql_last_terms": [],
            "mysql_times_expanded": [0],
        }
        mock_db = _stub_modules.db
        mock_db.session.execute.return_value.scalar.return_value = "ctx"

        backend.get_sentence_context(0, session)
        # After 1st expansion (times_expanded becomes 1), offset should be 1
        calls = mock_db.session.execute.call_args_list
        first_prev_params = calls[0][0][1]
        first_next_params = calls[1][0][1]
        assert first_prev_params["sent_no"] == 9   # 10 - 1
        assert first_next_params["sent_no"] == 11   # 10 + 1

        mock_db.session.execute.reset_mock()
        backend.get_sentence_context(0, session)
        # After 2nd expansion (times_expanded becomes 2), offset should be 2
        calls = mock_db.session.execute.call_args_list
        second_prev_params = calls[0][0][1]
        second_next_params = calls[1][0][1]
        assert second_prev_params["sent_no"] == 8   # 10 - 2
        assert second_next_params["sent_no"] == 12   # 10 + 2

    def test_uses_settings_lang_key(self, backend, _stub_modules):
        session = {
            "mysql_hit_ids": [{"text_id": 1, "sent_no": 5}],
            "mysql_last_terms": ["word"],
            "mysql_times_expanded": [0],
        }
        mock_db = _stub_modules.db
        mock_db.session.execute.return_value.scalar.return_value = "context"

        result = backend.get_sentence_context(0, session)
        assert "russian" in result["languages"]
        assert "default" not in result["languages"]

    def test_returns_highlighted_context(self, backend, _stub_modules):
        session = {
            "mysql_hit_ids": [{"text_id": 1, "sent_no": 5}],
            "mysql_last_terms": ["word"],
            "mysql_times_expanded": [0],
        }
        mock_db = _stub_modules.db
        mock_db.session.execute.return_value.scalar.return_value = (
            "a word here"
        )

        result = backend.get_sentence_context(0, session)
        lang_data = result["languages"]["russian"]
        assert "w_highlighted" in lang_data["prev"]
        assert "w_highlighted" in lang_data["next"]

    def test_src_alignment_always_present(self, backend, _stub_modules):
        session = {
            "mysql_hit_ids": [{"text_id": 1, "sent_no": 5}],
            "mysql_last_terms": [],
            "mysql_times_expanded": [0],
        }
        mock_db = _stub_modules.db
        mock_db.session.execute.return_value.scalar.return_value = None

        result = backend.get_sentence_context(0, session)
        assert result["src_alignment"] == {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_highlight_escapes_html(self, backend):
        result = backend._highlight("<b>bold</b>", ["bold"])
        assert "<b>" not in result
        assert "&lt;b&gt;" in result
        assert "w_highlighted" in result

    def test_build_boolean_query(self, backend):
        assert backend._build_boolean_query(["hello", "world"]) == (
            "+hello* +world*"
        )
        assert backend._build_boolean_query([]) == ""

    def test_build_phrase_query(self, backend):
        assert backend._build_phrase_query("hello world") == '"hello world"'
        assert backend._build_phrase_query("") == ""

    def test_normalize_page(self, backend):
        assert backend._normalize_page(-1) == 1
        assert backend._normalize_page(0) == 1
        assert backend._normalize_page(1) == 1
        assert backend._normalize_page(5) == 5

    def test_get_page_size_clamped(self, backend):
        assert backend._get_page_size({"page_size": "200"}) == 50
        assert backend._get_page_size({"page_size": "0"}) == 1
        assert backend._get_page_size({"page_size": "invalid"}) == 10

    def test_build_query_text_priority(self, backend):
        assert backend._build_query_text({"txt": "hello"}) == "hello"
        assert backend._build_query_text({"wf1": "a", "lex1": "b"}) == "a b"
        assert backend._build_query_text({"wf1": "a"}) == "a"
        assert backend._build_query_text({}) == ""
