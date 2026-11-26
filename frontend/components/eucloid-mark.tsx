import { cn } from "@/lib/utils";

/**
 * Eucloid brand mark: the official icon (public/eucloid-icon.png, transparent background)
 * plus the EUCLOID wordmark as text, so it stays crisp and takes the colour of its context
 * (white on the dark welcome screen, navy on light pages).
 */
export function EucloidMark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/eucloid-icon.png" alt="Eucloid" width={40} height={40} className="h-10 w-10 shrink-0" />
      <div className="leading-tight text-left">
        <div className="text-lg font-extrabold tracking-[0.12em]">EUCLOID</div>
        {!compact && <div className="text-[11px] opacity-70">Prior Authorization Review</div>}
      </div>
    </div>
  );
}
