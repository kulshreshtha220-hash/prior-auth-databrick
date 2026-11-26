import { Home, Inbox, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EucloidMark } from "@/components/eucloid-mark";

export function Header({
  userName,
  isReviewer = false,
  onHome,
  onQueue,
}: {
  userName?: string | null;
  isReviewer?: boolean;
  onHome?: () => void;
  onQueue?: () => void;
}) {
  return (
    <header className="mb-10">
      {/* Top navigation */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <button onClick={onHome} className="text-[#10326E]" aria-label="Home">
          <EucloidMark compact />
        </button>
        <div className="flex items-center gap-2">
          {onHome && (
            <Button variant="ghost" size="sm" onClick={onHome}>
              <Home className="h-4 w-4" /> Home
            </Button>
          )}
          {onQueue && (
            <Button variant="outline" size="sm" onClick={onQueue}>
              <Inbox className="h-4 w-4" /> {isReviewer ? "Reviewer queue" : "My requests"}
            </Button>
          )}
          {userName && (
            <span className="hidden md:inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {userName}
            </span>
          )}
        </div>
      </div>

      {/* Gradient banner */}
      <div className="relative overflow-hidden rounded-xl bg-gradient-to-r from-brand via-brand-dark to-brand-darker px-6 py-8 text-white shadow-lg">
        {/* Decorative circles */}
        <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/10" />
        <div className="absolute -right-4 bottom-0 h-24 w-24 rounded-full bg-white/5" />

        <div className="relative flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-white/20 backdrop-blur-sm">
            <ShieldCheck className="h-7 w-7" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
                Prior Authorization Review
              </h1>
              <Badge className="bg-white/20 text-white border-white/30 text-[10px] uppercase tracking-widest">
                AI-Powered
              </Badge>
            </div>
            <p className="mt-2 text-sm text-blue-100/90 max-w-lg">
              Multi-agent clinical review on Databricks: Mosaic AI agents on Model Serving,
              governed by Unity Catalog, with real-time MCP verification
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-blue-200/80">
              <Sparkles className="h-3 w-3" />
              <span>4 specialized AI agents</span>
              <span className="mx-1">&#183;</span>
              <span>5 MCP data sources</span>
              <span className="mx-1">&#183;</span>
              <span>Gate-based decision rubric</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
