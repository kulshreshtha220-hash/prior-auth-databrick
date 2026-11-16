"""Document upload and parsing (diagram: Document processing).

Upload -> UC Volume raw_documents/<doc_id>/<file> -> ai_parse_document (SQL
warehouse) -> normalized text, stored in the Delta `documents` table and
returned to the UI, which appends it to the case's clinical notes.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile

from pa_core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BYTES = 25 * 1024 * 1024
PARSEABLE = (".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".ppt", ".pptx")
TEXT = (".txt", ".md", ".csv")

PARSE_SQL = """
WITH parsed AS (
  SELECT ai_parse_document(content) AS p
  FROM read_files('{path}', format => 'binaryFile')
)
SELECT
  concat_ws('\\n\\n', transform(
    try_cast(p:document:elements AS ARRAY<VARIANT>),
    e -> try_cast(e:content AS STRING))) AS text,
  size(try_cast(p:document:pages AS ARRAY<VARIANT>)) AS pages,
  try_cast(p:error_status AS STRING) AS error_status
FROM parsed
"""


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "document")[:120]


def _parse(path: str) -> tuple[str, int | None]:
    from pa_core import sql

    # path is built from a UUID and a sanitized file name ([A-Za-z0-9._-]), so inlining is safe;
    # read_files needs a literal path.
    if not re.fullmatch(r"/Volumes/[A-Za-z0-9_./-]+", path):
        raise ValueError("unexpected volume path")
    rows = sql.execute(PARSE_SQL.replace("{path}", path), timeout_s=600)
    if not rows:
        return "", None
    r = rows[0]
    if r.get("error_status"):
        logger.warning("ai_parse_document reported: %s", r["error_status"])
    return r.get("text") or "", int(r["pages"]) if r.get("pages") else None


@router.post("")
async def upload_document(file: UploadFile = File(...)):
    s = get_settings()
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File larger than 25 MB")
    name = _safe_name(file.filename or "document")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in PARSEABLE + TEXT:
        raise HTTPException(415, f"Unsupported file type {ext or '(none)'}")

    doc_id = str(uuid.uuid4())
    if s.state_store == "memory":
        text = data.decode("utf-8", "ignore") if ext in TEXT else "(document parsing needs Databricks: ai_parse_document)"
        return {"document_id": doc_id, "filename": name, "pages": None, "text": text, "path": None}

    from pa_core.llm import workspace_client

    path = f"{s.raw_documents_path}/{doc_id}/{name}"
    await asyncio.to_thread(workspace_client().files.upload, path, io.BytesIO(data), overwrite=True)
    try:
        if ext in TEXT:
            text, pages = data.decode("utf-8", "ignore"), None
        else:
            text, pages = await asyncio.to_thread(_parse, path)
    except Exception as e:  # noqa: BLE001
        logger.exception("Parsing failed for %s", path)
        raise HTTPException(502, f"Document stored but parsing failed: {e}") from e

    from app.services.store import audit, delta_insert

    delta_insert("documents", {
        "document_id": doc_id, "filename": name, "volume_path": path, "pages": pages,
        "parsed_text": text[:200000], "parser": "text" if ext in TEXT else "ai_parse_document",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })
    audit(None, "document_uploaded", {"document_id": doc_id, "path": path, "pages": pages})
    return {"document_id": doc_id, "filename": name, "pages": pages, "text": text, "path": path}
