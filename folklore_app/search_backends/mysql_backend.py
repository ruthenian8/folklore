import html
import re

from sqlalchemy import text as sql_text

from folklore_app.models import db


class MySQLSearchBackend:
    def __init__(self, *, max_page_size=100):
        self._max_page_size = max_page_size

    def search_sentences(self, request_args, page, session_data):
        request_args = self._resolve_request_args(request_args, session_data)
        query_text = self._build_query_text(request_args)
        if not query_text:
            return {
                "data": self._empty_results(page=1, page_size=10),
                "max_page_number": 1,
            }
        precise = request_args.get("precise") == "on"
        page_size = self._get_page_size(request_args)
        page = self._normalize_page(page)
        offset = (page - 1) * page_size
        terms = self._tokenize(query_text)
        boolean_query = self._build_boolean_query(terms, precise=precise)
        like_query = f"%{query_text.strip()}%"

        if precise:
            total_rows = db.session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) AS total
                    FROM texts_sentences
                    WHERE content_norm LIKE :q
                    """
                ),
                {"q": like_query},
            ).scalar()
            total_docs = db.session.execute(
                sql_text(
                    """
                    SELECT COUNT(DISTINCT text_id) AS total
                    FROM texts_sentences
                    WHERE content_norm LIKE :q
                    """
                ),
                {"q": like_query},
            ).scalar()
            results = db.session.execute(
                sql_text(
                    """
                    SELECT id, text_id, sent_no, content, content_norm
                    FROM texts_sentences
                    WHERE content_norm LIKE :q
                    ORDER BY text_id, sent_no
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"q": like_query, "limit": page_size, "offset": offset},
            ).mappings()
        else:
            total_rows = db.session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) AS total
                    FROM texts_sentences
                    WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)
                    """
                ),
                {"q": boolean_query},
            ).scalar()
            total_docs = db.session.execute(
                sql_text(
                    """
                    SELECT COUNT(DISTINCT text_id) AS total
                    FROM texts_sentences
                    WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)
                    """
                ),
                {"q": boolean_query},
            ).scalar()
            results = db.session.execute(
                sql_text(
                    """
                    SELECT id, text_id, sent_no, content, content_norm,
                           MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE) AS score
                    FROM texts_sentences
                    WHERE MATCH(content_norm) AGAINST (:q IN BOOLEAN MODE)
                    ORDER BY score DESC, text_id, sent_no
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"q": boolean_query, "limit": page_size, "offset": offset},
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

        data = {
            "contexts": contexts,
            "n_sentences": int(total_rows or 0),
            "n_docs": int(total_docs or 0),
            "n_occurrences": 0,
            "page": page,
            "page_size": page_size,
            "timeout": False,
            "message": None,
            "subcorpus_enabled": False,
            "languages": ["default"],
            "media": False,
            "src_alignment": None,
        }
        max_page_number = (min(data["n_sentences"], 1000) - 1) // page_size + 1
        data["too_many_hits"] = 1000 < data["n_sentences"]
        return {"data": data, "max_page_number": max_page_number}

    def get_sentence_context(self, n, session_data):
        hit_ids = session_data.get("mysql_hit_ids", [])
        if n < 0 or n >= len(hit_ids):
            return {}
        hit = hit_ids[n]
        text_id = hit["text_id"]
        sent_no = hit["sent_no"]
        terms = session_data.get("mysql_last_terms", [])

        prev_row = db.session.execute(
            sql_text(
                """
                SELECT content
                FROM texts_sentences
                WHERE text_id = :text_id AND sent_no = :sent_no
                """
            ),
            {"text_id": text_id, "sent_no": sent_no - 1},
        ).scalar()
        next_row = db.session.execute(
            sql_text(
                """
                SELECT content
                FROM texts_sentences
                WHERE text_id = :text_id AND sent_no = :sent_no
                """
            ),
            {"text_id": text_id, "sent_no": sent_no + 1},
        ).scalar()

        return {
            "n": n,
            "languages": {
                "default": {
                    "prev": self._highlight(prev_row or "", terms),
                    "next": self._highlight(next_row or "", terms),
                }
            },
            "src_alignment": {},
        }

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

    def _build_boolean_query(self, terms, precise=False):
        if not terms:
            return ""
        if precise:
            return " ".join(terms)
        return " ".join(f"+{term}*" for term in terms)

    def _build_context(self, row, terms, precise=False):
        header = f"Text ID {row['text_id']} · Sentence {row['sent_no'] + 1}"
        highlighted = self._highlight(row["content"], terms)
        return {
            "toggled_on": True,
            "header": header,
            "languages": {
                "default": {
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
            "message": None,
            "subcorpus_enabled": False,
            "languages": ["default"],
            "media": False,
            "src_alignment": None,
            "too_many_hits": False,
        }
