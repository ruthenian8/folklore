"""MySQL-backed search client compatible with the legacy interface."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import joinedload, selectinload

from folklore_app.models import Texts, db

from .query_parsers import InterfaceQueryParser


def _log_if_needed(func):
    """Wrap client calls to optionally log queries or responses."""

    def decorated(self, es_query: Dict[str, Any]):
        if self.logging == "query":
            self.query_log.append(es_query)
        result = func(self, es_query)
        if self.logging == "hits" and isinstance(result, dict):
            self.query_log.append(result)
        return result

    return decorated


class MySQLSearchClient:
    """Client that proxies search requests to MySQL helper functions."""

    def __init__(self, settings_dir: str, settings):
        self.settings = settings
        self.name = self.settings.corpus_name
        self.qp = InterfaceQueryParser(settings_dir, self.settings)
        self.logging = "none"
        self.query_log: List[Any] = []
        self._word_count_cache: Dict[int, int] = {}
        self._corpus_word_total: Optional[int] = None

    # ------------------------------------------------------------------
    # Logging helpers (kept for compatibility with the elastic client)
    # ------------------------------------------------------------------
    def start_query_logging(self):
        self.query_log = []
        self.logging = "query"

    def start_hits_logging(self):
        self.query_log = []
        self.logging = "hits"

    def stop_logging(self) -> List[Any]:
        query_log = self.query_log
        self.query_log = []
        self.logging = "none"
        return query_log

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _call_function(
        self,
        key: str,
        es_query: Optional[Dict[str, Any]] = None,
        extra_params: Optional[Dict[str, Any]] = None,
        expect_scalar: bool = False,
    ) -> Any:
        """Execute a configured SQL statement and return parsed JSON."""

        if key not in self.settings.mysql_functions:
            raise RuntimeError(f"MySQL function for '{key}' is not configured")

        config = self.settings.mysql_functions[key]
        if isinstance(config, str):
            sql = f"SELECT {config}(:query_json) AS payload"
        else:
            sql = config.get("sql")
            if sql is None:
                raise RuntimeError(f"Invalid configuration for MySQL function '{key}'")
            expect_scalar = config.get("expect_scalar", expect_scalar)

        params: Dict[str, Any] = {}
        if es_query is not None:
            params["query_json"] = json.dumps(es_query)
        if extra_params:
            params.update(extra_params)

        result = db.session.execute(text(sql), params)
        rows = result.fetchall()
        if not rows:
            return [] if not expect_scalar else 0

        if expect_scalar:
            value = list(rows[0]._mapping.values())[0]
            return value

        payloads: List[Any] = []
        for row in rows:
            value = next(iter(row._mapping.values()))
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("utf-8")
            if isinstance(value, str):
                payloads.append(json.loads(value))
            else:
                payloads.append(value)

        if len(payloads) == 1:
            return payloads[0]
        return payloads

    # ------------------------------------------------------------------
    # Data formatting helpers
    # ------------------------------------------------------------------
    def _empty_hits(self) -> Dict[str, Any]:
        return {
            "took": 0,
            "timed_out": False,
            "_shards": {"total": 0, "successful": 0, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": 0, "relation": "eq"}, "max_score": None, "hits": []},
        }

    @staticmethod
    def _strip_empty(values: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in values.items() if v not in (None, "", [], {})}

    @staticmethod
    def _count_words(raw_text: Optional[str]) -> int:
        if not raw_text:
            return 0
        tokens = re.findall(r"\w+", raw_text, flags=re.UNICODE)
        return len(tokens)

    def _collect_people(self, people: Iterable[Any]) -> List[str]:
        names: List[str] = []
        for person in people:
            parts = [person.name]
            if getattr(person, "code", None):
                parts.append(f"[{person.code}]")
            if getattr(person, "birth_year", None):
                parts.append(str(person.birth_year))
            formatted = " ".join(part for part in parts if part)
            if formatted:
                names.append(formatted)
        return names

    def _serialize_text(self, text: Texts) -> Dict[str, Any]:
        geo = text.geo
        videos = [video.video for video in getattr(text, "video", []) if video.video]
        images = [
            image.image.image_file
            for image in getattr(text, "images", [])
            if image is not None and getattr(image, "image", None) is not None and hasattr(image.image, "image_file")
        ]
        audio = [audio.audio for audio in getattr(text, "audio", []) if audio.audio]

        metadata: Dict[str, Any] = {
            "doc_id": text.id,
            "id": text.id,
            "old_id": text.old_id,
            "year": text.year,
            "genre": text.genre,
            "leader": text.leader,
            "address": text.address,
            "region": geo.region.name if geo and geo.region else None,
            "district": geo.district.name if geo and geo.district else None,
            "village": geo.village.name if geo and geo.village else None,
            "collectors": self._collect_people(text.collectors),
            "informators": self._collect_people(text.informators),
            "questions": [
                "".join(
                    part
                    for part in [question.question_list, str(question.question_num or ""), question.question_letter or ""]
                    if part
                )
                for question in text.questions
            ],
            "keywords": [keyword.word for keyword in text.keywords if keyword.word],
            "raw_text": text.raw_text,
            "pdf": text.pdf,
            "video": videos,
            "audio": audio,
            "images": images,
        }
        if text.id in self._word_count_cache:
            metadata["n_words"] = self._word_count_cache[text.id]
        else:
            metadata["n_words"] = self._count_words(text.raw_text)
            self._word_count_cache[text.id] = metadata["n_words"]
        return self._strip_empty(metadata)

    def _format_hits(self, items: List[Dict[str, Any]], index_suffix: str) -> Dict[str, Any]:
        hits = [
            {
                "_index": f"{self.name}{index_suffix}",
                "_id": str(item.get("id") or item.get("doc_id")),
                "_score": None,
                "_source": item,
            }
            for item in items
        ]
        return {
            "took": 0,
            "timed_out": False,
            "_shards": {"total": 1 if hits else 0, "successful": 1 if hits else 0, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": len(hits), "relation": "eq"}, "max_score": None, "hits": hits},
        }

    @staticmethod
    def _normalize_doc_id(doc_id: str) -> Optional[int]:
        try:
            return int(doc_id)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Public API – mirrors the elastic client
    # ------------------------------------------------------------------
    @_log_if_needed
    def get_words(self, es_query: Dict[str, Any]) -> Dict[str, Any]:
        return self._call_function("get_words", es_query)

    @_log_if_needed
    def get_docs(self, es_query: Dict[str, Any]) -> Dict[str, Any]:
        return self._call_function("get_docs", es_query)

    @_log_if_needed
    def get_all_docs(self, es_query: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        data = self._call_function("get_all_docs", es_query)
        return data if isinstance(data, list) else [data]

    @_log_if_needed
    def get_sentences(self, es_query: Dict[str, Any]) -> Dict[str, Any]:
        return self._call_function("get_sentences", es_query)

    @_log_if_needed
    def get_all_sentences(self, es_query: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        data = self._call_function("get_all_sentences", es_query)
        return data if isinstance(data, list) else [data]

    @_log_if_needed
    def get_sentence_by_id(self, sent_id: str) -> Dict[str, Any]:
        return self._call_function("get_sentence_by_id", extra_params={"sent_id": sent_id})

    @_log_if_needed
    def get_word_by_id(self, word_id: str) -> Dict[str, Any]:
        return self._call_function("get_word_by_id", extra_params={"word_id": word_id})

    @_log_if_needed
    def get_doc_by_id(self, doc_id: str) -> Dict[str, Any]:
        if "get_doc_by_id" in self.settings.mysql_functions:
            return self._call_function("get_doc_by_id", extra_params={"doc_id": doc_id})

        doc_id_int = self._normalize_doc_id(doc_id)
        if doc_id_int is None:
            return self._empty_hits()

        text = (
            Texts.query.options(
                joinedload(Texts.geo),
                selectinload(Texts.collectors),
                selectinload(Texts.informators),
                selectinload(Texts.questions),
                selectinload(Texts.keywords),
                selectinload(Texts.video),
                selectinload(Texts.audio),
                selectinload(Texts.images),
            )
            .filter(Texts.id == doc_id_int)
            .one_or_none()
        )
        if text is None:
            return self._empty_hits()
        source = self._serialize_text(text)
        return self._format_hits([source], index_suffix=".docs")

    def get_n_words(self) -> int:
        if self._corpus_word_total is not None:
            return self._corpus_word_total

        if "get_n_words" in self.settings.mysql_functions:
            total = int(self._call_function("get_n_words", expect_scalar=True))
            self._corpus_word_total = total
            return total

        texts = Texts.query.with_entities(Texts.id, Texts.raw_text).all()
        total = 0
        for text in texts:
            if text.id in self._word_count_cache:
                total += self._word_count_cache[text.id]
            else:
                count = self._count_words(text.raw_text)
                self._word_count_cache[text.id] = count
                total += count
        self._corpus_word_total = total
        return total

    def get_n_words_in_document(self, doc_id: str) -> int:
        if "get_n_words_in_document" in self.settings.mysql_functions:
            return int(
                self._call_function(
                    "get_n_words_in_document", extra_params={"doc_id": doc_id}, expect_scalar=True
                )
            )

        doc_id_int = self._normalize_doc_id(doc_id)
        if doc_id_int is None:
            return 0

        if doc_id_int in self._word_count_cache:
            return self._word_count_cache[doc_id_int]

        text = (
            Texts.query.with_entities(Texts.id, Texts.raw_text)
            .filter(Texts.id == doc_id_int)
            .one_or_none()
        )
        if text is None:
            return 0
        count = self._count_words(text.raw_text)
        self._word_count_cache[text.id] = count
        return count

    @_log_if_needed
    def get_word_freq_by_rank(self, lang: str) -> Dict[str, Any]:
        return self._call_function("get_word_freq_by_rank", extra_params={"lang": lang})

    @_log_if_needed
    def get_lemma_freq_by_rank(self, lang: str) -> Dict[str, Any]:
        return self._call_function("get_lemma_freq_by_rank", extra_params={"lang": lang})

    def is_alive(self) -> bool:
        try:
            db.session.execute(text("SELECT 1"))
            return True
        except Exception:  # pragma: no cover - defensive
            return False

