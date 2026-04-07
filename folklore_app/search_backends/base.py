try:
    from typing import Dict, List, Protocol, Union
except ImportError:  # pragma: no cover - fallback for Python 3.6
    from typing_extensions import Protocol
    from typing import Dict, List, Union

from werkzeug.datastructures import ImmutableMultiDict


class SearchBackend(Protocol):
    """Contract that every full-text search backend must satisfy.

    Both MySQL and Elasticsearch backends implement this protocol so that
    they can be swapped transparently by changing the ``SEARCH_BACKEND``
    environment variable.

    ``search_sentences`` must return::

        {
            "data": {
                "contexts":           list[dict],   # per-sentence result dicts
                "n_sentences":        int,           # total matching sentences
                "n_docs":             int,           # distinct documents matched
                "n_occurrences":      int,           # word-level occurrence count
                "page":               int,           # current page (1-based)
                "page_size":          int,           # results per page
                "timeout":            bool,          # True when query timed out
                "message":            str,           # user-visible message
                "subcorpus_enabled":  bool,
                "languages":          list[str],     # e.g. ["default"]
                "media":              bool,
                "src_alignment":      dict | str,
                "too_many_hits":      bool,
            },
            "max_page_number": int,
        }

    ``get_sentence_context`` must return::

        {
            "n":              int,
            "languages": {
                "<lang>": {"prev": str, "next": str},
                ...
            },
            "src_alignment":  dict,
        }

    or an empty ``dict`` when the index is out of range or expansion is
    no longer allowed.
    """

    def search_sentences(
        self,
        request_args: ImmutableMultiDict,
        page: int,
        session_data: dict,
    ) -> Dict[str, Union[dict, int]]:
        """Run a full-text sentence search and return paginated results."""
        raise NotImplementedError

    def get_sentence_context(
        self, n: int, session_data: dict
    ) -> dict:
        """Return neighbouring sentences for hit *n*."""
        raise NotImplementedError
