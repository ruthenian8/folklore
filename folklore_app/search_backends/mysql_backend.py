import html
import re

from sqlalchemy import text as sql_text

from folklore_app.models import db
from folklore_app.search_backends import mysql_indexer


class MySQLSearchBackend:
    def __init__(self, *, max_page_size=100, settings=None):
        self._max_page_size = max_page_size
        self._languages = ["default"]
        self._media = False
        self._max_context_expand = 6
        if settings is not None:
            self._languages = settings.get("languages", self._languages)
            self._media = settings.get("media", self._media)
            self._max_context_expand = settings.get(
                "max_context_expand", self._max_context_expand
            )

    # ------------------------------------------------------------------
    # Public API (SearchBackend protocol)
    # ------------------------------------------------------------------

    def search_sentences(self, request_args, page, session_data):
        request_args = self._resolve_request_args(request_args, session_data)
        query_text = self._build_query_text(request_args)
        normalized_query = mysql_indexer.normalize(query_text)
        if not normalized_query:
            return {
                "data": self._empty_results(page=1, page_size=10),
                "max_page_number": 1,
            }
        precise = request_args.get("precise") == "on"
        page_size = self._get_page_size(request_args)
        page = self._normalize_page(page)
        offset = (page - 1) * page_size
        terms = self._tokenize(normalized_query)
        boolean_query = self._build_boolean_query(terms)
        phrase_query = self._build_phrase_query(normalized_query)

        ft_query = phrase_query if precise else boolean_query
        meta_clause, meta_params = self._build_meta_filter(request_args)

        total_rows = db.session.execute(
            sql_text(
                "SELECT COUNT(*) AS total"
                " FROM texts_sentences"
                " WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)"
                + meta_clause
            ),
            {"q": ft_query, **meta_params},
        ).scalar()

        total_docs = db.session.execute(
            sql_text(
                "SELECT COUNT(DISTINCT text_id) AS total"
                " FROM texts_sentences"
                " WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)"
                + meta_clause
            ),
            {"q": ft_query, **meta_params},
        ).scalar()

        if precise:
            results = db.session.execute(
                sql_text(
                    "SELECT id, text_id, sent_no, content, content_norm"
                    " FROM texts_sentences"
                    " WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)"
                    + meta_clause
                    + " ORDER BY text_id, sent_no"
                    " LIMIT :limit OFFSET :offset"
                ),
                {"q": ft_query, "limit": page_size, "offset": offset,
                 **meta_params},
            ).mappings()
        else:
            results = db.session.execute(
                sql_text(
                    "SELECT id, text_id, sent_no, content, content_norm,"
                    " MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE) AS score"
                    " FROM texts_sentences"
                    " WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)"
                    + meta_clause
                    + " ORDER BY score DESC, text_id, sent_no"
                    " LIMIT :limit OFFSET :offset"
                ),
                {"q": ft_query, "limit": page_size, "offset": offset,
                 **meta_params},
            ).mappings()

        rows = list(results)
        contexts = [
            self._build_context(row, terms, precise=precise)
            for row in rows
        ]

        session_data["mysql_hit_ids"] = [
            {"text_id": row["text_id"], "sent_no": row["sent_no"]}
            for row in rows
        ]
        session_data["mysql_last_terms"] = terms
        session_data["mysql_times_expanded"] = [0] * len(rows)

        n_sentences = int(total_rows or 0)
        n_docs = int(total_docs or 0)

        data = {
            "contexts": contexts,
            "n_sentences": n_sentences,
            "n_docs": n_docs,
            "n_occurrences": 0,
            "page": page,
            "page_size": page_size,
            "timeout": False,
            "message": "" if n_sentences > 0 else "Nothing found.",
            "subcorpus_enabled": bool(meta_clause),
            "languages": self._languages,
            "media": self._media,
            "src_alignment": {},
        }
        max_page_number = max(
            1, (min(data["n_sentences"], 1000) - 1) // page_size + 1
        )
        data["too_many_hits"] = 1000 < data["n_sentences"]
        return {"data": data, "max_page_number": max_page_number}

    def get_sentence_context(self, n, session_data):
        hit_ids = session_data.get("mysql_hit_ids", [])
        if n < 0 or n >= len(hit_ids):
            return {}

        times_expanded = session_data.get("mysql_times_expanded", [])
        if n < len(times_expanded):
            if times_expanded[n] >= self._max_context_expand:
                return {}
            times_expanded[n] += 1
        else:
            return {}

        hit = hit_ids[n]
        text_id = hit["text_id"]
        sent_no = hit["sent_no"]
        offset = times_expanded[n]
        terms = session_data.get("mysql_last_terms", [])

        prev_row = db.session.execute(
            sql_text(
                "SELECT content"
                " FROM texts_sentences"
                " WHERE text_id = :text_id AND sent_no = :sent_no"
            ),
            {"text_id": text_id, "sent_no": sent_no - offset},
        ).scalar()
        next_row = db.session.execute(
            sql_text(
                "SELECT content"
                " FROM texts_sentences"
                " WHERE text_id = :text_id AND sent_no = :sent_no"
            ),
            {"text_id": text_id, "sent_no": sent_no + offset},
        ).scalar()

        lang = self._languages[0] if self._languages else "default"
        return {
            "n": n,
            "languages": {
                lang: {
                    "prev": self._highlight(prev_row or "", terms),
                    "next": self._highlight(next_row or "", terms),
                }
            },
            "src_alignment": {},
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _normalize_page(self, page):
        if page <= 0:
            return 1
        return page

    def _get_page_size(self, request_args):
        try:
            page_size = int(request_args.get("page_size", 10))
        except (TypeError, ValueError):
            page_size = 10
        page_size = max(1, min(page_size, self._max_page_size))
        return page_size

    def _build_query_text(self, request_args):
        txt = request_args.get("txt", "").strip()
        if txt:
            return txt
        wf = request_args.get("wf1", "").strip()
        lex = request_args.get("lex1", "").strip()
        return " ".join([part for part in (wf, lex) if part])

    def _resolve_request_args(self, request_args, session_data):
        if request_args:
            session_data["mysql_last_request_args"] = dict(request_args)
            return request_args
        stored = session_data.get("mysql_last_request_args")
        if stored:
            return stored
        return request_args

    def _tokenize(self, text):
        return [token for token in re.split(r"\s+", text.strip()) if token]

    def _build_boolean_query(self, terms):
        if not terms:
            return ""
        return " ".join(f"+{term}*" for term in terms)

    def _build_phrase_query(self, query_text):
        if not query_text:
            return ""
        return f'"{query_text}"'

    def _build_meta_filter(self, request_args):
        """Return an SQL clause fragment and parameter dict for metadata filters.

        Supports *year_from*, *year_to* (inclusive range on the ``year``
        column) and *geo* (exact match on the ``geo`` column).
        """
        clauses = []
        params = {}

        year_from = request_args.get("year_from")
        if year_from is not None:
            try:
                params["year_from"] = int(year_from)
                clauses.append(" AND year >= :year_from")
            except (TypeError, ValueError):
                pass

        year_to = request_args.get("year_to")
        if year_to is not None:
            try:
                params["year_to"] = int(year_to)
                clauses.append(" AND year <= :year_to")
            except (TypeError, ValueError):
                pass

        geo = request_args.get("geo", "").strip()
        if geo:
            params["geo"] = geo
            clauses.append(" AND geo = :geo")

        return "".join(clauses), params

    def _build_context(self, row, terms, precise=False):
        header = f"Text ID {row['text_id']} \u00b7 Sentence {row['sent_no'] + 1}"
        highlighted = self._highlight(row["content"], terms)
        lang = self._languages[0] if self._languages else "default"
        return {
            "toggled_on": True,
            "header": header,
            "languages": {
                lang: {
                    "text": highlighted,
                }
            },
        }

    def _highlight(self, content, terms):
        escaped = html.escape(content or "")
        if not terms:
            return escaped
        pattern = re.compile(
            "(" + "|".join(re.escape(term) for term in terms) + ")",
            flags=re.IGNORECASE,
        )
        return pattern.sub(r'<span class="word w_highlighted">\1</span>', escaped)

    def _empty_results(self, page, page_size):
        return {
            "contexts": [],
            "n_sentences": 0,
            "n_docs": 0,
            "n_occurrences": 0,
            "page": page,
            "page_size": page_size,
            "timeout": False,
            "message": "Nothing found.",
            "subcorpus_enabled": False,
            "languages": self._languages,
            "media": self._media,
            "src_alignment": {},
            "too_many_hits": False,
        }
