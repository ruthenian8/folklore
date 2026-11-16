import re

from nltk.tokenize import sent_tokenize
from sqlalchemy import text as sql_text

from folklore_app.models import db, Texts

# Default number of rows to flush per INSERT batch.
_INSERT_CHUNK_SIZE = 500


def normalize(text):
    lowered = (text or "").lower().replace("ё", "е").replace("\\", "")
    cleaned = re.sub(r"[^\w\s-]", " ", lowered, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def split_sentences(raw_text):
    if not raw_text:
        return []
    try:
        return sent_tokenize(raw_text)
    except LookupError as exc:
        raise RuntimeError(
            "NLTK punkt tokenizer data is missing. "
            "Run `python -m nltk.downloader punkt` before indexing."
        ) from exc


def get_indexed_text_count():
    """Return the number of distinct text_ids currently in the search index."""
    row = db.session.execute(
        sql_text("SELECT COUNT(DISTINCT text_id) AS cnt FROM texts_sentences")
    ).scalar()
    return int(row or 0)


def rebuild_index(truncate_first=False, batch_size=1000):
    if batch_size <= 0:
        raise ValueError('batch_size must be positive')
    try:
        # Keep the old index visible until the complete replacement commits.
        db.session.execute(sql_text("DELETE FROM texts_sentences"))
        query = Texts.query.order_by(Texts.id)
        total = query.count()
        indexed = 0
        last_id = 0
        while True:
            texts = query.filter(Texts.id > last_id).limit(batch_size).all()
            if not texts:
                break
            _index_texts(texts, commit=False)
            indexed += len(texts)
            last_id = texts[-1].id
        db.session.commit()
        return {"total": total, "indexed": indexed}
    except Exception:
        db.session.rollback()
        raise


def index_text(text_id, delete_existing=True):
    text = Texts.query.filter_by(id=text_id).one_or_none()
    if text is None:
        raise ValueError(f"Text {text_id} not found.")
    try:
        _index_texts([text])
    except Exception:
        db.session.rollback()
        raise


def reindex_changed_texts(since_timestamp):
    if not hasattr(Texts, "updated_at"):
        raise RuntimeError(
            "Texts.updated_at is not available; use rebuild or index_text instead."
        )
    texts = Texts.query.filter(Texts.updated_at >= since_timestamp).all()
    if texts:
        _index_texts(texts)


_UPSERT_SQL = sql_text(
    "INSERT INTO texts_sentences"
    " (text_id, sent_no, lang, content, content_norm, year, geo)"
    " VALUES"
    " (:text_id, :sent_no, :lang, :content, :content_norm, :year, :geo)"
    " ON DUPLICATE KEY UPDATE"
    " content = VALUES(content),"
    " content_norm = VALUES(content_norm),"
    " year = VALUES(year),"
    " geo = VALUES(geo)"
)


def _index_texts(texts, chunk_size=_INSERT_CHUNK_SIZE, commit=True):
    if not texts:
        return

    # Remove existing rows for the text_ids being indexed so that stale
    # sentences (e.g. if a text was shortened or deleted) don't linger.
    text_ids = [t.id for t in texts]
    for start in range(0, len(text_ids), chunk_size):
        batch_ids = text_ids[start : start + chunk_size]
        params = {f"id_{i}": tid for i, tid in enumerate(batch_ids)}
        placeholders = ", ".join(f":{k}" for k in params)
        db.session.execute(
            sql_text(
                "DELETE FROM texts_sentences WHERE text_id IN ({})".format(
                    placeholders
                )
            ),
            params,
        )

    rows = []
    for text in texts:
        sentences = split_sentences(text.raw_text)
        for sent_no, sentence in enumerate(sentences):
            rows.append(
                {
                    "text_id": text.id,
                    "sent_no": sent_no,
                    "lang": "default",
                    "content": sentence,
                    "content_norm": normalize(sentence),
                    "year": text.year,
                    "geo": _get_geo(text),
                }
            )
            # Flush incrementally to bound memory usage.
            if len(rows) >= chunk_size:
                db.session.execute(_UPSERT_SQL, rows)
                rows = []
    if rows:
        db.session.execute(_UPSERT_SQL, rows)
    if commit:
        db.session.commit()


def _get_geo(text):
    if text.geo and getattr(text.geo, "village", None):
        return text.geo.village.name
    if text.geo and getattr(text.geo, "district", None):
        return text.geo.district.name
    if text.geo and getattr(text.geo, "region", None):
        return text.geo.region.name
    return None
