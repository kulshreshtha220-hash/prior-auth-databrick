import { cn } from "@/lib/utils";

/** Text logo: Eucloid wordmark + product name. Swap in the real logo file when available. */
export function EucloidMark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-cyan-500 text-base font-black text-white shadow">
        e
      </span>
      <div className="leading-tight">
        <div className="text-base font-bold tracking-tight">eucloid</div>
        {!compact && <div className="text-[11px] opacity-70">Prior Authorization Review</div>}
      </div>
    </div>
  );
}
