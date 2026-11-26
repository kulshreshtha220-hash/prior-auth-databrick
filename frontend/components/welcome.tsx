"use client";

import {
  ArrowRight,
  ClipboardCheck,
  FileText,
  History,
  Inbox,
  Lock,
  Scale,
  ShieldCheck,
  Stethoscope,
  UserCheck,
  FileSearch,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { EucloidMark } from "@/components/eucloid-mark";

/** Turn "kulshreshtha.220@eucloid.com" or "Abhishek Suman" into a friendly first name. */
export function firstName(nameOrEmail?: string | null): string {
  if (!nameOrEmail) return "";
  const base = nameOrEmail.split("@")[0];
  const token = base.split(/[\s._-]+/).find((t) => /^[a-zA-Z]{2,}$/.test(t));
  return token ? token.charAt(0).toUpperCase() + token.slice(1).toLowerCase() : "";
}

const STEPS = [
  { icon: ClipboardCheck, title: "Compliance", text: "Is the paperwork complete?" },
  { icon: Stethoscope, title: "Clinical", text: "Codes valid, evidence extracted" },
  { icon: FileSearch, title: "Coverage", text: "Provider + Medicare policy" },
  { icon: Scale, title: "Decision gates", text: "Fixed rules: approve or pend" },
  { icon: FileText, title: "Synthesis", text: "Rationale + audit PDF" },
];

const TRUST = [
  { icon: UserCheck, text: "A clinician makes every final decision" },
  { icon: ShieldCheck, text: "The system never auto-denies" },
  { icon: History, text: "Every step is audited and traceable" },
  { icon: Lock, text: "Data stays inside Databricks" },
];

export function Welcome({
  userName,
  isReviewer = false,
  onStart,
  onQueue,
}: {
  userName?: string | null;
  isReviewer?: boolean;
  onStart: () => void;
  onQueue: () => void;
}) {
  const first = firstName(userName);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#0B1B33] text-white">
      {/* Background: soft glows + faint grid */}
      <div className="pointer-events-none absolute -left-40 -top-40 h-[520px] w-[520px] rounded-full bg-brand/40 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-48 -right-32 h-[560px] w-[560px] rounded-full bg-cyan-500/20 blur-3xl" />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }}
      />

      <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col px-4 sm:px-6">
        {/* Top bar */}
        <div className="flex items-center justify-between py-6">
          <EucloidMark className="text-white" />
          {userName && (
            <span className="hidden sm:inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-blue-100/80">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Signed in as {userName}
            </span>
          )}
        </div>

        {/* Hero */}
        <div className="flex flex-1 flex-col justify-center py-10 animate-in fade-in slide-in-from-bottom-4 duration-700">
          <span className="inline-flex w-fit items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-[11px] font-medium uppercase tracking-widest text-cyan-200">
            AI-assisted · Human-decided
          </span>

          <h1 className="mt-6 text-4xl font-bold leading-tight tracking-tight sm:text-6xl">
            {first ? (
              <>
                Welcome back, <span className="bg-gradient-to-r from-cyan-200 to-blue-300 bg-clip-text text-transparent">{first}</span>
              </>
            ) : (
              <>Welcome to Prior Authorization Review</>
            )}
          </h1>

          <p className="mt-5 max-w-2xl text-base text-blue-100/80 sm:text-lg">
            Review prior authorization requests in minutes. Four AI agents check documentation, clinical evidence
            and Medicare coverage against real reference data, then fixed decision rules recommend approve or pend.
            You make the final call.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button
              size="lg"
              onClick={onStart}
              className="h-12 bg-white px-6 text-base font-semibold text-[#0B1B33] shadow-lg shadow-cyan-500/20 hover:bg-blue-50"
            >
              Start new review
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={onQueue}
              className="h-12 border-white/25 bg-white/5 px-6 text-base text-white hover:bg-white/10 hover:text-white"
            >
              <Inbox className="h-4 w-4" />
              {isReviewer ? "Reviewer queue" : "My requests"}
            </Button>
          </div>

          {/* How it works */}
          <div className="mt-14">
            <p className="text-xs font-semibold uppercase tracking-widest text-blue-200/60">How a review works</p>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-5">
              {STEPS.map((s, i) => (
                <div
                  key={s.title}
                  className="group relative rounded-xl border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm transition hover:border-cyan-300/40 hover:bg-white/[0.07]"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-cyan-500 text-white shadow">
                      <s.icon className="h-[18px] w-[18px]" />
                    </span>
                    <span className="text-[11px] font-medium text-blue-200/50">Step {i + 1}</span>
                  </div>
                  <p className="mt-3 text-sm font-semibold">{s.title}</p>
                  <p className="mt-1 text-xs text-blue-100/60">{s.text}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Trust row */}
          <div className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {TRUST.map((t) => (
              <div key={t.text} className="flex items-center gap-2 text-xs text-blue-100/70">
                <t.icon className="h-4 w-4 shrink-0 text-emerald-300" />
                {t.text}
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-col items-center justify-between gap-2 border-t border-white/10 py-5 text-[11px] text-blue-200/50 sm:flex-row">
          <span>Built on Databricks · Unity Catalog · Lakebase · MLflow</span>
          <span>AI-assisted draft. All decisions require human clinical review.</span>
        </div>
      </div>
    </div>
  );
}
