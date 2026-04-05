import os


def get_search_backend():
    backend = os.getenv("SEARCH_BACKEND", "elasticsearch").lower()
    allowed = {"elasticsearch", "mysql"}
    if backend not in allowed:
        raise ValueError(
            f"SEARCH_BACKEND must be one of {sorted(allowed)}; got {backend!r}"
        )
    return backend


SEARCH_BACKEND = get_search_backend()
