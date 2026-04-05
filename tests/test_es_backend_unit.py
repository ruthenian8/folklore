"""Unit tests for ESSearchBackend.

These tests mock all injected dependencies so they can run without
Elasticsearch.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub the heavy folklore_app import tree.
# ---------------------------------------------------------------------------

_fake_models = types.ModuleType("folklore_app.models")
_fake_models.db = MagicMock()

_fake_folklore = types.ModuleType("folklore_app")
_fake_folklore.models = _fake_models

_fake_backends_pkg = types.ModuleType("folklore_app.search_backends")
_fake_backends_pkg.__path__ = [
    os.path.join(os.path.dirname(__file__), os.pardir,
                 "folklore_app", "search_backends")
]

sys.modules["folklore_app"] = _fake_folklore
sys.modules["folklore_app.models"] = _fake_models
sys.modules["folklore_app.search_backends"] = _fake_backends_pkg

from folklore_app.search_backends.es_backend import ESSearchBackend  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend(**overrides):
    defaults = dict(
        find_sentences_json=MagicMock(return_value=_make_es_hits()),
        add_sent_to_session=MagicMock(),
        sent_viewer=MagicMock(),
        settings={"languages": ["default"], "media": False},
        get_session_data=MagicMock(side_effect=_session_getter()),
        set_session_data=MagicMock(),
        sync_page_data=MagicMock(),
        build_context=MagicMock(return_value={"n": 0, "languages": {},
                                              "src_alignment": {}}),
    )
    defaults.update(overrides)
    return ESSearchBackend(**defaults)


def _make_es_hits(timed_out=False, n_sentences=5, n_docs=2, n_occurrences=10,
                  subcorpus_enabled=False):
    hits = {
        "timed_out": timed_out,
        "hits": {
            "total": {"value": n_sentences},
            "hits": [],
        },
        "aggregations": {
            "agg_ndocs": {"value": n_docs},
            "agg_nwords": {"sum": n_occurrences},
        },
    }
    if subcorpus_enabled:
        hits["subcorpus_enabled"] = True
    return hits


def _session_getter():
    """Return a side_effect function for get_session_data."""
    data = {"page": 1, "page_size": 10, "translit": None}
    return lambda key: data.get(key)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestESSearchSentences:
    def test_result_keys(self):
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 10,
            "n_sentences": {"value": 5},
            "n_docs": 2,
            "page": 1,
            "message": "",
            "contexts": [{"toggled_on": True}],
        }
        backend = _make_backend(sent_viewer=sent_viewer)
        result = backend.search_sentences({}, 1, {})

        data = result["data"]
        assert "n_sentences" in data
        assert "n_docs" in data
        assert "n_occurrences" in data
        assert "page" in data
        assert "page_size" in data
        assert "timeout" in data
        assert "languages" in data
        assert "media" in data
        assert "subcorpus_enabled" in data
        assert "too_many_hits" in data
        assert "src_alignment" in data
        assert "max_page_number" in result

    def test_timeout_propagated(self):
        es_hits = _make_es_hits(timed_out=True)
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 0,
            "n_sentences": {"value": 0},
            "n_docs": 0,
            "page": 1,
            "message": "Nothing found.",
            "contexts": [],
        }
        backend = _make_backend(
            find_sentences_json=MagicMock(return_value=es_hits),
            sent_viewer=sent_viewer,
        )
        result = backend.search_sentences({}, 1, {})
        assert result["data"]["timeout"] is True

    def test_n_sentences_unwrapped_from_dict(self):
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 0,
            "n_sentences": {"value": 42},
            "n_docs": 1,
            "page": 1,
            "message": "",
            "contexts": [],
        }
        backend = _make_backend(sent_viewer=sent_viewer)
        result = backend.search_sentences({}, 1, {})
        assert result["data"]["n_sentences"] == 42

    def test_n_sentences_plain_int(self):
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 0,
            "n_sentences": 7,
            "n_docs": 1,
            "page": 1,
            "message": "",
            "contexts": [],
        }
        backend = _make_backend(sent_viewer=sent_viewer)
        result = backend.search_sentences({}, 1, {})
        assert result["data"]["n_sentences"] == 7

    def test_subcorpus_enabled(self):
        es_hits = _make_es_hits(subcorpus_enabled=True)
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 0,
            "n_sentences": {"value": 1},
            "n_docs": 1,
            "page": 1,
            "message": "",
            "contexts": [],
        }
        backend = _make_backend(
            find_sentences_json=MagicMock(return_value=es_hits),
            sent_viewer=sent_viewer,
        )
        result = backend.search_sentences({}, 1, {})
        assert result["data"]["subcorpus_enabled"] is True

    def test_negative_page_resets(self):
        set_session = MagicMock()
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 0,
            "n_sentences": {"value": 0},
            "n_docs": 0,
            "page": 1,
            "message": "",
            "contexts": [],
        }
        backend = _make_backend(
            set_session_data=set_session,
            sent_viewer=sent_viewer,
        )
        backend.search_sentences({}, -1, {})
        set_session.assert_any_call("page_data", {})

    def test_too_many_hits(self):
        sent_viewer = MagicMock()
        sent_viewer.process_sent_json.return_value = {
            "n_occurrences": 0,
            "n_sentences": {"value": 2000},
            "n_docs": 100,
            "page": 1,
            "message": "",
            "contexts": [],
        }
        backend = _make_backend(sent_viewer=sent_viewer)
        result = backend.search_sentences({}, 1, {})
        assert result["data"]["too_many_hits"] is True


class TestESGetSentenceContext:
    def test_delegates_to_build_context(self):
        ctx = {"n": 5, "languages": {"default": {"prev": "", "next": ""}},
               "src_alignment": {}}
        build = MagicMock(return_value=ctx)
        backend = _make_backend(build_context=build)
        result = backend.get_sentence_context(5, {})
        build.assert_called_once_with(5)
        assert result == ctx
