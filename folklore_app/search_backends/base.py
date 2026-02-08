try:
    from typing import Protocol
except ImportError:  # pragma: no cover - fallback for Python 3.6
    from typing_extensions import Protocol

from werkzeug.datastructures import ImmutableMultiDict


class SearchBackend(Protocol):
    def search_sentences(
        self,
        request_args: ImmutableMultiDict,
        page: int,
        session_data: dict,
    ):
        raise NotImplementedError

    def get_sentence_context(self, n: int, session_data: dict):
        raise NotImplementedError
