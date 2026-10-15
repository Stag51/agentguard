"""Payload storage: large span inputs/outputs kept outside the Step rows.

WHY: see docs/data-model.md. Step rows hold a short reference ("payload:<hash>");
the content lives in the `payload` table, keyed by its hash, so repeated prompts
are stored once and writes are idempotent.

WHY a table and not files: a deployed (serverless) API has no persistent disk.
Older runs may still hold a file path as reference; `read_payload` handles both.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import db

PREFIX = "payload:"


def write_payload(text: str, session=None) -> str:
    """Store `text` and return its reference.

    Pass the caller's `session` to join its transaction; otherwise a short
    transaction of its own is used.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    if session is not None:
        db.insert_ignore(session, db.Payload, hash=digest, content=text)
    else:
        with db.get_session() as s:
            db.insert_ignore(s, db.Payload, hash=digest, content=text)
            s.commit()
    return PREFIX + digest


def read_payload(ref: str | None, session=None) -> str:
    """Load a payload by reference; empty string if missing."""
    if not ref:
        return ""
    if not ref.startswith(PREFIX):  # legacy: a file path from before payloads moved to the DB
        p = Path(ref)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    if session is not None:
        row = session.get(db.Payload, ref[len(PREFIX):])
        return row.content if row else ""
    with db.get_session() as s:
        row = s.get(db.Payload, ref[len(PREFIX):])
        return row.content if row else ""


def load_payloads(refs: list[str], session) -> dict[str, str]:
    """Fetch many payloads in one query: {reference: content}.

    WHY: scoring a run reads hundreds of payloads; one query per payload would be
    painfully slow against a remote database.
    """
    hashes = {r[len(PREFIX):] for r in refs if r and r.startswith(PREFIX)}
    out: dict[str, str] = {}
    if hashes:
        from sqlalchemy import select

        for h, content in session.execute(select(db.Payload.hash, db.Payload.content).where(db.Payload.hash.in_(hashes))):
            out[PREFIX + h] = content
    for r in refs:
        if r and not r.startswith(PREFIX):
            out[r] = read_payload(r)
    return out
