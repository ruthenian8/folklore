import re

from nltk.tokenize import sent_tokenize
from sqlalchemy import text as sql_text

from folklore_app.models import db, Texts


def normalize(text):
    lowered = (text or "").lower().replace("ё", "е")
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


def rebuild_index(truncate_first=False, batch_size=1000):
    if truncate_first:
        db.session.execute(sql_text("TRUNCATE TABLE texts_sentences"))
        db.session.commit()

    query = Texts.query.order_by(Texts.id)
    total = query.count()
    offset = 0
    while offset < total:
        texts = query.offset(offset).limit(batch_size).all()
        _index_texts(texts)
        offset += batch_size


def index_text(text_id, delete_existing=True):
    text = Texts.query.filter_by(id=text_id).one_or_none()
    if text is None:
        raise ValueError(f"Text {text_id} not found.")
    if delete_existing:
        db.session.execute(
            sql_text("DELETE FROM texts_sentences WHERE text_id = :text_id"),
            {"text_id": text_id},
        )
        db.session.commit()
    _index_texts([text])


def reindex_changed_texts(since_timestamp):
    if not hasattr(Texts, "updated_at"):
        raise RuntimeError(
            "Texts.updated_at is not available; use rebuild or index_text instead."
        )
    texts = Texts.query.filter(Texts.updated_at >= since_timestamp).all()
    if texts:
        _index_texts(texts)


def _index_texts(texts):
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
    if rows:
        db.session.execute(
            sql_text(
                """
                INSERT INTO texts_sentences
                    (text_id, sent_no, lang, content, content_norm, year, geo)
                VALUES
                    (:text_id, :sent_no, :lang, :content, :content_norm, :year, :geo)
                """
            ),
            rows,
        )
        db.session.commit()


def _get_geo(text):
    if text.geo and getattr(text.geo, "village", None):
        return text.geo.village.name
    if text.geo and getattr(text.geo, "district", None):
        return text.geo.district.name
    if text.geo and getattr(text.geo, "region", None):
        return text.geo.region.name
    return None
