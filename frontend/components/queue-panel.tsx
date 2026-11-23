"use client";

import { useEffect, useState } from "react";
import { Inbox, Loader2, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getQueue, type QueueItem } from "@/lib/api";

const GATE_LABEL: Record<string, string> = {
  gate_1_provider: "Gate 1 · Provider",
  gate_2_codes: "Gate 2 · Codes",
  gate_3_necessity: "Gate 3 · Necessity",
};

/** Modal list of cases waiting for a reviewer decision. Click a row to open it. */
export function QueuePanel({ onClose, onOpen }: { onClose: () => void; onOpen: (requestId: string) => void }) {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setItems(null);
    setError(null);
    try {
      setItems(await getQueue());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the queue");
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-16 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-3xl overflow-hidden rounded-xl border bg-background text-foreground shadow-2xl animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div className="flex items-center gap-2">
            <Inbox className="h-5 w-5 text-brand" />
            <h2 className="text-lg font-semibold">Reviewer queue</h2>
            {items && <Badge variant="secondary">{items.length}</Badge>}
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" onClick={load} aria-label="Refresh">
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="max-h-[60vh] overflow-y-auto">
          {error && <p className="p-6 text-sm text-destructive">{error}</p>}
          {!error && !items && (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading cases…
            </div>
          )}
          {items && items.length === 0 && (
            <p className="p-6 text-sm text-muted-foreground">No cases are waiting for review.</p>
          )}
          {items && items.length > 0 && (
            <ul className="divide-y">
              {items.map((it) => (
                <li key={it.request_id}>
                  <button
                    className="flex w-full flex-col gap-1 px-5 py-3 text-left transition hover:bg-muted sm:flex-row sm:items-center sm:justify-between"
                    onClick={() => onOpen(it.request_id)}
                  >
                    <div>
                      <p className="font-medium">{it.patient_name || "Unnamed patient"}</p>
                      <p className="font-mono text-[11px] text-muted-foreground">
                        {it.request_id.slice(0, 8)}
                        {it.provider_npi ? ` · NPI ${it.provider_npi}` : ""}
                        {it.created_at ? ` · ${new Date(it.created_at).toLocaleString()}` : ""}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {it.decision_gate && it.decision_gate !== "approved" && (
                        <Badge variant="outline">{GATE_LABEL[it.decision_gate] || it.decision_gate}</Badge>
                      )}
                      <Badge className="bg-warning-light text-warning-dark border-warning/30">
                        {it.recommendation === "approve" ? "Approve" : "Pend"}
                        {it.confidence_level ? ` · ${it.confidence_level}` : ""}
                      </Badge>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
