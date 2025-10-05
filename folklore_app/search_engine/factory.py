"""Search client factory providing backend-specific clients."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .corpus_settings import CorpusSettings


def get_search_client(settings_dir: str, corpus_settings: "CorpusSettings"):
    """Return a search client configured for the active backend.

    Parameters
    ----------
    settings_dir:
        Path to the directory containing corpus settings.
    corpus_settings:
        Loaded corpus configuration.
    """

    backend = getattr(corpus_settings, "search_backend", "elasticsearch")
    if backend == "mysql":
        from .mysql_client import MySQLSearchClient

        return MySQLSearchClient(settings_dir, corpus_settings)

    from .client import SearchClient

    return SearchClient(settings_dir, corpus_settings)

