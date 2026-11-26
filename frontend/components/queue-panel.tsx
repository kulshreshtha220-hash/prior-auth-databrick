"use client";

import { useEffect, useState } from "react";
import { Inbox, Loader2, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getMyCases, getQueue, type QueueItem } from "@/lib/api";
import { cn } from "@/lib/utils";

const GATE_LABEL: Record<string, string> = {
  gate_1_provider: "Gate 1 · Provider",
  gate_2_codes: "Gate 2 · Codes",
  gate_3_necessity: "Gate 3 · Necessity",
};

type Tab = "mine" | "all";

function statusBadge(it: QueueItem) {
  if (it.status === "RUNNING") return { text: "Running", cls: "bg-info-light text-brand-dark border-brand/20" };
  if (it.status === "FAILED") return { text: "Failed", cls: "bg-red-50 text-red-700 border-red-200" };
  if (it.status === "DECIDED" || it.final_recommendation) {
    const approved = it.final_recommendation === "approve";
    return {
      text: `Decided · ${approved ? "Approved" : "Pended"}`,
      cls: "bg-muted text-foreground border-border",
    };
  }
  const approve = it.recommendation === "approve";
  return {
    text: `${approve ? "Approve" : "Pend"}${it.confidence_level ? ` · ${it.confidence_level}` : ""}`,
    cls: approve
      ? "bg-success-light text-success-dark border-success/30"
      : "bg-warning-light text-warning-dark border-warning/30",
  };
}

/**
 * Cases modal.
 * - "My requests": every case the signed-in user submitted (any status).
 * - "Pending review": every user's cases waiting for a decision; only for reviewers (PA_REVIEWERS).
 */
export function QueuePanel({
  isReviewer,
  onClose,
  onOpen,
}: {
  isReviewer: boolean;
  onClose: () => void;
  onOpen: (requestId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>(isReviewer ? "all" : "mine");
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(t: Tab = tab) {
    setItems(null);
    setError(null);
    try {
      setItems(t === "all" ? await getQueue() : await getMyCases());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load cases");
    }
  }

  useEffect(() => {
    load(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-16 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-3xl overflow-hidden rounded-xl border bg-background text-foreground shadow-2xl animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div className="flex items-center gap-2">
            <Inbox className="h-5 w-5 text-brand" />
            <h2 className="text-lg font-semibold">{isReviewer ? "Reviewer queue" : "My requests"}</h2>
            {items && <Badge variant="secondary">{items.length}</Badge>}
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" onClick={() => load()} aria-label="Refresh">
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {isReviewer && (
          <div className="flex gap-1 border-b bg-muted/40 px-4 py-2">
            {([
              ["all", "Pending review · all doctors"],
              ["mine", "My requests"],
            ] as [Tab, string][]).map(([t, label]) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition",
                  tab === t ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        <div className="max-h-[60vh] overflow-y-auto">
          {error && <p className="p-6 text-sm text-destructive">{error}</p>}
          {!error && !items && (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading cases…
            </div>
          )}
          {items && items.length === 0 && (
            <p className="p-6 text-sm text-muted-foreground">
              {tab === "all" ? "No cases are waiting for review." : "You have not submitted any cases yet."}
            </p>
          )}
          {items && items.length > 0 && (
            <ul className="divide-y">
              {items.map((it) => {
                const b = statusBadge(it);
                const done = it.status !== "RUNNING" && it.status !== "FAILED";
                return (
                  <li key={it.request_id}>
                    <button
                      disabled={!done}
                      className="flex w-full flex-col gap-1 px-5 py-3 text-left transition enabled:hover:bg-muted disabled:cursor-default disabled:opacity-70 sm:flex-row sm:items-center sm:justify-between"
                      onClick={() => onOpen(it.request_id)}
                    >
                      <div>
                        <p className="font-medium">{it.patient_name || "Unnamed patient"}</p>
                        <p className="font-mono text-[11px] text-muted-foreground">
                          {it.request_id.slice(0, 8)}
                          {it.provider_npi ? ` · NPI ${it.provider_npi}` : ""}
                          {tab === "all" && it.submitted_by ? ` · by ${it.submitted_by}` : ""}
                          {it.created_at ? ` · ${new Date(it.created_at).toLocaleString()}` : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {it.decision_gate && it.decision_gate !== "approved" && (
                          <Badge variant="outline">{GATE_LABEL[it.decision_gate] || it.decision_gate}</Badge>
                        )}
                        <span className={cn("rounded-full border px-2 py-0.5 text-xs font-medium", b.cls)}>{b.text}</span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
