"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SAMPLE_CASES, type SampleCase } from "@/lib/sample-case";
import { cn } from "@/lib/utils";

const TONE: Record<SampleCase["tone"], string> = {
  success: "bg-success-light text-success-dark border-success/30",
  warning: "bg-warning-light text-warning-dark border-warning/30",
  danger: "bg-red-50 text-red-700 border-red-200",
  info: "bg-info-light text-brand-dark border-brand/20",
};

/** "Load sample case" dropdown: highest / middle / lowest score plus gate-failure cases. */
export function SamplePicker({ onPick }: { onPick: (c: SampleCase) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const groups = Array.from(new Set(SAMPLE_CASES.map((c) => c.group)));

  return (
    <div ref={ref} className="relative">
      <Button type="button" variant="secondary" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <FlaskConical className="mr-1 h-3.5 w-3.5" />
        Load sample case
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
      </Button>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[min(92vw,420px)] overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl animate-in fade-in slide-in-from-top-1 duration-150">
          {groups.map((g) => (
            <div key={g}>
              <p className="border-b bg-muted/50 px-4 py-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                {g}
              </p>
              {SAMPLE_CASES.filter((c) => c.group === g).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => {
                    onPick(c);
                    setOpen(false);
                  }}
                  className="block w-full border-b px-4 py-3 text-left transition last:border-b-0 hover:bg-muted"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">{c.label}</span>
                    <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold", TONE[c.tone])}>
                      {c.expected}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{c.description}</p>
                </button>
              ))}
            </div>
          ))}
          <p className="bg-muted/30 px-4 py-2 text-[11px] text-muted-foreground">
            Expected results are a guide; the live AI can vary the score slightly.
          </p>
        </div>
      )}
    </div>
  );
}
