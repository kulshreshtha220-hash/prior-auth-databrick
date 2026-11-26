"""Review persistence (replaces Microsoft's in-memory `_review_store`).

Three layers, matching the diagram's Unity Catalog data layer:
  * Lakebase Postgres  - live case status, reviewer queue, decisions, audit log
  * UC Volume          - generated_reports/<request_id>/*.pdf
  * Delta tables       - analytical record (pa_requests, agent_runs, agent_findings,
                         gate_results, final_decisions, audit_events), written
                         asynchronously through the SQL warehouse

PA_STATE_STORE=memory keeps everything in memory for local development.
The public functions keep Microsoft's names so the routers barely change.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import logging
import queue
import threading
from datetime import datetime, timezone

from pa_core.config import get_settings

logger = logging.getLogger(__name__)
_PDF_KEYS = ("audit_justification_pdf",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------- volumes
def _volume_write(path: str, data: bytes) -> str | None:
    try:
        from pa_core.llm import workspace_client

        workspace_client().files.upload(path, io.BytesIO(data), overwrite=True)
        return path
    except Exception as e:  # noqa: BLE001
        logger.warning("Volume write failed for %s: %s", path, e)
        return None


def _volume_read_b64(path: str | None) -> str | None:
    if not path:
        return None
    try:
        from pa_core.llm import workspace_client

        return base64.b64encode(workspace_client().files.download(path).contents.read()).decode()
    except Exception as e:  # noqa: BLE001
        logger.warning("Volume read failed for %s: %s", path, e)
        return None


def save_pdf(request_id: str, name: str, b64: str | None) -> str | None:
    if not b64 or get_settings().state_store == "memory":
        return None
    return _volume_write(f"{get_settings().generated_reports_path}/{request_id}/{name}", base64.b64decode(b64))


# ----------------------------------------------------------------- delta (async)
_delta_q: "queue.Queue[tuple[str, dict]]" = queue.Queue()
_delta_thread: threading.Thread | None = None


def _delta_worker():
    from pa_core import sql

    while True:
        stmt, params = _delta_q.get()
        try:
            sql.execute(stmt, params)
        except Exception as e:  # noqa: BLE001
            logger.warning("Delta write failed (%s): %s", stmt[:60], e)


def delta_insert(table: str, row: dict) -> None:
    """Queue an INSERT into a Delta table (best effort, never blocks a review)."""
    s = get_settings()
    if not s.write_delta or s.state_store == "memory" or not s.warehouse_id:
        return
    global _delta_thread
    if _delta_thread is None or not _delta_thread.is_alive():
        _delta_thread = threading.Thread(target=_delta_worker, daemon=True, name="delta-writer")
        _delta_thread.start()
    from pa_core.sql import table as fq

    cols = list(row)
    placeholders = []
    for c in cols:
        if isinstance(row[c], list) and all(isinstance(x, str) for x in row[c]) and c.endswith(("_codes", "_ids", "reasons")):
            placeholders.append(f"from_json(:{c}, 'array<string>')")
        elif isinstance(row[c], (dict, list)):
            placeholders.append(f"parse_json(:{c})")
        elif c.endswith("_at"):
            placeholders.append(f"CAST(:{c} AS TIMESTAMP)")
        else:
            placeholders.append(f":{c}")
    stmt = f"INSERT INTO {fq(table)} ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
    _delta_q.put((stmt, row))


# ----------------------------------------------------------------- memory backend
_mem: dict[str, dict] = {}
_mem_audit: list[dict] = []


def _lb():
    from app.services import lakebase

    return lakebase.sync_pool()


def _is_mem() -> bool:
    return get_settings().state_store == "memory"


# ----------------------------------------------------------------- public API
def audit(request_id: str | None, event_type: str, data: dict | None = None, actor: str = "system") -> None:
    data = data or {}
    if _is_mem():
        _mem_audit.append({"request_id": request_id, "event_type": event_type, "actor": actor, "data": data, "at": _now()})
    else:
        try:
            with _lb().connection() as c:
                c.execute(
                    "INSERT INTO pa.audit_events (request_id, event_type, actor, event_data) VALUES (%s,%s,%s,%s::jsonb)",
                    (request_id, event_type, actor, json.dumps(data, default=str)),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("audit write failed: %s", e)
    delta_insert("audit_events", {"request_id": request_id, "event_type": event_type, "actor": actor,
                                  "event_data": data, "created_at": _now()})


def start_case(request_id: str, request_data: dict, actor: str = "system") -> None:
    if _is_mem():
        _mem[request_id] = {"request_id": request_id, "request_data": request_data, "response": None,
                            "decision": None, "status": "RUNNING", "stored_at": _now(), "submitted_by": actor}
    else:
        with _lb().connection() as c:
            c.execute(
                "INSERT INTO pa.cases (request_id, status, patient_name, provider_npi, request_data, submitted_by) "
                "VALUES (%s,'RUNNING',%s,%s,%s::jsonb,%s) ON CONFLICT (request_id) DO NOTHING",
                (request_id, request_data.get("patient_name"), request_data.get("provider_npi"),
                 json.dumps(request_data, default=str), actor),
            )
    delta_insert("pa_requests", {
        "request_id": request_id, "provider_npi": request_data.get("provider_npi"),
        "diagnosis_codes": request_data.get("diagnosis_codes", []),
        "procedure_codes": request_data.get("procedure_codes", []),
        "document_ids": request_data.get("document_ids", []),
        "submitted_by": actor, "submitted_at": _now(), "request_json": request_data,
    })
    audit(request_id, "review_started", {"provider_npi": request_data.get("provider_npi")}, actor)


def update_progress(request_id: str, phase: str, pct: int) -> None:
    if _is_mem():
        if request_id in _mem:
            _mem[request_id].update(phase=phase, progress_pct=pct)
        return
    try:
        with _lb().connection() as c:
            c.execute("UPDATE pa.cases SET phase=%s, progress_pct=%s, updated_at=now() WHERE request_id=%s",
                      (phase, pct, request_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("progress update failed: %s", e)


def fail_case(request_id: str, error: str) -> None:
    if _is_mem():
        if request_id in _mem:
            _mem[request_id]["status"] = "FAILED"
    else:
        try:
            with _lb().connection() as c:
                c.execute("UPDATE pa.cases SET status='FAILED', updated_at=now() WHERE request_id=%s", (request_id,))
        except Exception as e:  # noqa: BLE001
            logger.warning("fail_case update failed: %s", e)
    audit(request_id, "review_failed", {"error": error[:2000]})


def record_agent_outputs(request_id: str, results: dict[str, dict], gates: dict) -> None:
    """Analytical record of every agent run, finding and gate (Delta)."""
    for agent, res in results.items():
        meta = (res or {}).get("_meta", {})
        delta_insert("agent_runs", {
            "request_id": request_id, "agent": agent, "model": meta.get("model"), "prompt_version": meta.get("prompt"),
            "status": "error" if (res or {}).get("error") or (res or {}).get("_error") else "ok",
            "duration_s": float(meta.get("duration_s") or 0), "turns": int(meta.get("turns") or 0),
            "tool_calls": meta.get("tool_calls", []), "unavailable_sources": meta.get("unavailable_sources", {}),
            "created_at": _now(),
        })
        delta_insert("agent_findings", {"request_id": request_id, "agent": agent,
                                        "findings": {k: v for k, v in (res or {}).items() if k != "_meta"},
                                        "created_at": _now()})
    for gate, result in (gates.get("gate_results") or {}).items():
        delta_insert("gate_results", {
            "request_id": request_id, "gate": gate, "result": result,
            "reasons": (gates.get("gate_reasons") or {}).get(gate, []),
            "recommendation": gates.get("recommendation"), "confidence": float(gates.get("confidence") or 0),
            "created_at": _now(),
        })


def store_review(request_id: str, request_data: dict, response: dict) -> None:
    stored_resp = copy.deepcopy(response)
    pdf_path = save_pdf(request_id, "audit_justification.pdf", stored_resp.get("audit_justification_pdf"))
    if _is_mem():
        entry = _mem.setdefault(request_id, {"request_id": request_id, "decision": None, "stored_at": _now()})
        entry.update(request_data=request_data, response=stored_resp, status="COMPLETED")
    else:
        for k in _PDF_KEYS:
            stored_resp.pop(k, None)
        with _lb().connection() as c:
            c.execute(
                """INSERT INTO pa.cases (request_id, status, progress_pct, phase, patient_name, provider_npi,
                       recommendation, confidence, confidence_level, decision_gate, in_reviewer_queue,
                       request_data, response, audit_pdf_path)
                   VALUES (%s,'COMPLETED',100,'done',%s,%s,%s,%s,%s,%s,TRUE,%s::jsonb,%s::jsonb,%s)
                   ON CONFLICT (request_id) DO UPDATE SET status='COMPLETED', progress_pct=100, phase='done',
                       recommendation=EXCLUDED.recommendation, confidence=EXCLUDED.confidence,
                       confidence_level=EXCLUDED.confidence_level, decision_gate=EXCLUDED.decision_gate,
                       in_reviewer_queue=TRUE, response=EXCLUDED.response, audit_pdf_path=EXCLUDED.audit_pdf_path,
                       updated_at=now()""",
                (request_id, request_data.get("patient_name"), request_data.get("provider_npi"),
                 response.get("recommendation"), response.get("confidence"), response.get("confidence_level"),
                 response.get("decision_gate"), json.dumps(request_data, default=str),
                 json.dumps(stored_resp, default=str), pdf_path),
            )
    audit(request_id, "review_completed", {"recommendation": response.get("recommendation"),
                                           "confidence": response.get("confidence"), "audit_pdf_path": pdf_path})


def _row_to_review(row: dict) -> dict:
    resp = row.get("response") or {}
    if resp and not resp.get("audit_justification_pdf"):
        resp["audit_justification_pdf"] = _volume_read_b64(row.get("audit_pdf_path"))
    return {"request_id": row["request_id"], "request_data": row.get("request_data") or {}, "response": resp,
            "decision": row.get("decision"), "status": row.get("status"), "submitted_by": row.get("submitted_by"),
            "stored_at": (row.get("created_at") or _now()).isoformat() if hasattr(row.get("created_at"), "isoformat") else str(row.get("created_at"))}


def get_review(request_id: str) -> dict | None:
    if _is_mem():
        r = _mem.get(request_id)
        return r if r and r.get("response") else None
    from psycopg.rows import dict_row

    with _lb().connection() as c:
        cur = c.cursor(row_factory=dict_row)
        cur.execute(
            """SELECT c.*, CASE WHEN d.request_id IS NULL THEN NULL ELSE to_jsonb(d.*) END AS decision FROM pa.cases c
               LEFT JOIN pa.decisions d ON d.request_id = c.request_id WHERE c.request_id=%s""",
            (request_id,),
        )
        row = cur.fetchone()
    if not row or not row.get("response"):
        return None
    return _row_to_review(row)


def list_reviews(limit: int = 200) -> list[dict]:
    if _is_mem():
        return sorted((r for r in _mem.values() if r.get("response")), key=lambda r: r["stored_at"], reverse=True)
    from psycopg.rows import dict_row

    with _lb().connection() as c:
        cur = c.cursor(row_factory=dict_row)
        cur.execute(
            """SELECT c.request_id, c.status, c.request_data, c.response, c.created_at, c.audit_pdf_path, c.submitted_by,
                      CASE WHEN d.request_id IS NULL THEN NULL ELSE to_jsonb(d.*) END AS decision
               FROM pa.cases c LEFT JOIN pa.decisions d ON d.request_id = c.request_id
               WHERE c.response IS NOT NULL ORDER BY c.created_at DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        r["audit_pdf_path"] = None  # list view never needs the PDF
        out.append(_row_to_review(r))
    return out


def store_decision(request_id: str, decision: dict) -> None:
    letter = dict(decision.get("letter") or {})
    letter_path = save_pdf(request_id, f"letter_{decision.get('authorization_number', 'x')}.pdf", letter.get("pdf_base64"))
    updated_audit = decision.pop("updated_audit_pdf", None)
    audit_path = save_pdf(request_id, "audit_justification_final.pdf", updated_audit)
    if _is_mem():
        if request_id in _mem:
            _mem[request_id]["decision"] = decision
            if updated_audit:
                _mem[request_id]["response"]["audit_justification_pdf"] = updated_audit
    else:
        letter.pop("pdf_base64", None)
        with _lb().connection() as c:
            c.execute(
                """INSERT INTO pa.decisions (request_id, authorization_number, final_recommendation, was_overridden,
                       override_rationale, decided_by, decided_at, letter, letter_pdf_path)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                (request_id, decision["authorization_number"], decision["final_recommendation"],
                 decision["was_overridden"], decision.get("override_rationale"), decision["decided_by"],
                 decision["decided_at"], json.dumps(letter, default=str), letter_path),
            )
            c.execute(
                "UPDATE pa.cases SET status='DECIDED', in_reviewer_queue=FALSE, updated_at=now()"
                + (", audit_pdf_path=%s" if audit_path else "") + " WHERE request_id=%s",
                ((audit_path, request_id) if audit_path else (request_id,)),
            )
    delta_insert("final_decisions", {
        "request_id": request_id, "authorization_number": decision["authorization_number"],
        "final_recommendation": decision["final_recommendation"], "was_overridden": decision["was_overridden"],
        "override_rationale": decision.get("override_rationale"), "decided_by": decision["decided_by"],
        "decided_at": decision["decided_at"], "letter_pdf_path": letter_path,
    })
    audit(request_id, "decision_recorded", {"final_recommendation": decision["final_recommendation"],
                                            "was_overridden": decision["was_overridden"]}, decision["decided_by"])


def reviewer_queue(limit: int = 100, owner: str | None = None) -> list[dict]:
    """Open cases waiting for a human decision (diagram: reviewer queue).

    owner=None: every user's cases (reviewers). owner=<email>: only that user's cases.
    """
    if _is_mem():
        return [{"request_id": r["request_id"], "patient_name": r["request_data"].get("patient_name"),
                 "provider_npi": r["request_data"].get("provider_npi"),
                 "recommendation": (r.get("response") or {}).get("recommendation"),
                 "confidence_level": (r.get("response") or {}).get("confidence_level"),
                 "decision_gate": (r.get("response") or {}).get("decision_gate"),
                 "submitted_by": r.get("submitted_by"), "created_at": r.get("stored_at")}
                for r in _mem.values()
                if r.get("response") and not r.get("decision") and (owner is None or r.get("submitted_by") == owner)]
    from psycopg.rows import dict_row

    with _lb().connection() as c:
        cur = c.cursor(row_factory=dict_row)
        cur.execute(
            """SELECT request_id, patient_name, provider_npi, recommendation, confidence_level, decision_gate,
                      submitted_by, created_at
               FROM pa.cases WHERE in_reviewer_queue AND (%s::text IS NULL OR submitted_by = %s)
               ORDER BY created_at LIMIT %s""",
            (owner, owner, limit),
        )
        return cur.fetchall()


def my_cases(owner: str, limit: int = 100) -> list[dict]:
    """Every case one user submitted, any status, newest first (the doctor's own view)."""
    if _is_mem():
        rows = [r for r in _mem.values() if r.get("submitted_by") == owner]
        rows.sort(key=lambda r: r["stored_at"], reverse=True)
        return [{"request_id": r["request_id"], "patient_name": r["request_data"].get("patient_name"),
                 "provider_npi": r["request_data"].get("provider_npi"),
                 "status": "DECIDED" if r.get("decision") else r.get("status") or ("COMPLETED" if r.get("response") else "RUNNING"),
                 "recommendation": (r.get("response") or {}).get("recommendation"),
                 "confidence_level": (r.get("response") or {}).get("confidence_level"),
                 "decision_gate": (r.get("response") or {}).get("decision_gate"),
                 "final_recommendation": (r.get("decision") or {}).get("final_recommendation"),
                 "submitted_by": owner, "created_at": r.get("stored_at")}
                for r in rows[:limit]]
    from psycopg.rows import dict_row

    with _lb().connection() as c:
        cur = c.cursor(row_factory=dict_row)
        cur.execute(
            """SELECT c.request_id, c.patient_name, c.provider_npi, c.status, c.recommendation, c.confidence_level,
                      c.decision_gate, d.final_recommendation, c.submitted_by, c.created_at
               FROM pa.cases c LEFT JOIN pa.decisions d ON d.request_id = c.request_id
               WHERE c.submitted_by = %s ORDER BY c.created_at DESC LIMIT %s""",
            (owner, limit),
        )
        return cur.fetchall()


def case_owner(request_id: str) -> str | None:
    if _is_mem():
        return (_mem.get(request_id) or {}).get("submitted_by")
    with _lb().connection() as c:
        row = c.execute("SELECT submitted_by FROM pa.cases WHERE request_id=%s", (request_id,)).fetchone()
    return row[0] if row else None


def case_status(request_id: str) -> dict | None:
    if _is_mem():
        r = _mem.get(request_id)
        return {k: r.get(k) for k in ("request_id", "status", "phase", "progress_pct")} if r else None
    from psycopg.rows import dict_row

    with _lb().connection() as c:
        cur = c.cursor(row_factory=dict_row)
        cur.execute("SELECT request_id, status, phase, progress_pct, updated_at FROM pa.cases WHERE request_id=%s",
                    (request_id,))
        return cur.fetchone()
