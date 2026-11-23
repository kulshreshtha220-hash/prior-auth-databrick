import type {
  UploadedDocument,
  PriorAuthRequest,
  ReviewResponse,
  DecisionRequest,
  DecisionResponse,
  ProgressEvent,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

/**
 * Flatten a FastAPI error envelope into a human-readable string.
 *
 * On 4xx/5xx responses the body shape is one of:
 *   - { detail: "some string" }                       (HTTPException-raised)
 *   - { detail: [{loc, msg, type, input?}, ...] }     (Pydantic 422)
 *   - anything else / parse failure                   (fallback to status)
 *
 * The legacy code did `err.detail || ...`, which for the array form
 * stringified to "[object Object],[object Object]" — useless to the user.
 * This helper renders each Pydantic error as `<field>: <msg>` joined by
 * "; " so the form alert banner shows actionable, field-level guidance
 * (e.g. "patient_dob: must not be in the future; diagnosis_codes.0:
 * invalid ICD-10 ...").
 */
function formatApiError(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((e: { loc?: unknown; msg?: unknown }) => {
      const loc = Array.isArray(e?.loc) ? e.loc.slice(1).join(".") : "request";
      const msg = typeof e?.msg === "string" ? e.msg : "invalid value";
      return `${loc}: ${msg}`;
    });
    if (parts.length) return parts.join("; ");
  }
  return `Request failed (${status})`;
}

/**
 * Submit a prior auth review with real-time SSE progress streaming.
 * Returns an AbortController so the caller can cancel the request.
 */
export function submitReviewStream(
  request: PriorAuthRequest,
  onProgress: (event: ProgressEvent) => void,
  onResult: (result: ReviewResponse) => void,
  onError: (error: string) => void,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const response = await fetch(`${API_BASE}/review/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: controller.signal,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        onError(formatApiError(err, response.status));
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onError("No response stream available");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";
      // eventType must persist across chunks — if "event: result"
      // arrives at the end of one chunk and "data: ..." in the next,
      // resetting per-chunk would misroute the result as a progress event.
      let eventType = "progress";
      let receivedResult = false;
      let receivedError = false;

      const processLines = (lines: string[]) => {
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);
              if (eventType === "result") {
                receivedResult = true;
                onResult(parsed as ReviewResponse);
              } else if (eventType === "error") {
                receivedError = true;
                onError(parsed.detail || "Unknown error");
              } else {
                onProgress(parsed as ProgressEvent);
              }
            } catch (parseErr) {
              console.error("[SSE] Failed to parse JSON:", parseErr, "data:", data.slice(0, 200));
            }
            eventType = "progress"; // Reset after processing a data line
          }
          // Skip comment lines (": keepalive") and empty lines
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        processLines(lines);
      }

      // Process any remaining data left in the buffer after stream ends
      if (buffer.trim()) {
        processLines(buffer.split("\n"));
      }

      // If the stream completed without a result event, notify the caller
      // (keep the server's error message if one was sent)
      if (!receivedResult && !receivedError) {
        onError("Review stream ended without returning a result. Please try again.");
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onError(err instanceof Error ? err.message : "An error occurred");
      }
    }
  })();

  return controller;
}

export async function submitDecision(
  request: DecisionRequest
): Promise<DecisionResponse> {
  const response = await fetch(`${API_BASE}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, response.status));
  }

  return response.json();
}

/** Upload a document to the UC Volume and parse it with ai_parse_document (Databricks). */
export async function uploadDocument(file: File): Promise<UploadedDocument> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${API_BASE}/documents`, { method: "POST", body });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(formatApiError(error, response.status));
  }
  return response.json();
}

export interface CurrentUser {
  email: string;
  name: string;
}

/** Signed-in Databricks user (from the Apps SSO headers). Never throws. */
export async function getMe(): Promise<CurrentUser | null> {
  try {
    const r = await fetch(`${API_BASE}/me`);
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export interface QueueItem {
  request_id: string;
  patient_name?: string | null;
  provider_npi?: string | null;
  recommendation?: string | null;
  confidence_level?: string | null;
  decision_gate?: string | null;
  created_at?: string | null;
}

/** Cases waiting for a human decision (Lakebase reviewer queue). */
export async function getQueue(): Promise<QueueItem[]> {
  const r = await fetch(`${API_BASE}/queue`);
  if (!r.ok) {
    const error = await r.json().catch(() => ({}));
    throw new Error(formatApiError(error, r.status));
  }
  return r.json();
}

/** Load one stored review by request_id. */
export async function getReview(requestId: string): Promise<ReviewResponse> {
  const r = await fetch(`${API_BASE}/review/${encodeURIComponent(requestId)}`);
  if (!r.ok) {
    const error = await r.json().catch(() => ({}));
    throw new Error(formatApiError(error, r.status));
  }
  return r.json();
}
