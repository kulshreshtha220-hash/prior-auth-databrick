"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { ReviewResponse } from "@/lib/types";
import { getMe, getReview } from "@/lib/api";
import { Header } from "@/components/header";
import { UploadForm } from "@/components/upload-form";
import { ReviewDashboard } from "@/components/review-dashboard";
import { Welcome } from "@/components/welcome";
import { QueuePanel } from "@/components/queue-panel";

const ENTERED_KEY = "pa-entered";

function readEntered(): boolean {
  try {
    return sessionStorage.getItem(ENTERED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeEntered(v: boolean) {
  try {
    if (v) sessionStorage.setItem(ENTERED_KEY, "1");
    else sessionStorage.removeItem(ENTERED_KEY);
  } catch {
    /* storage unavailable: welcome screen simply shows again */
  }
}

export default function Home() {
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [entered, setEntered] = useState(false);
  const [ready, setReady] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [userName, setUserName] = useState<string | null>(null);

  useEffect(() => {
    setEntered(readEntered());
    setReady(true);
    getMe().then((u) => setUserName(u?.name || u?.email || null));
  }, []);

  function start() {
    writeEntered(true);
    setEntered(true);
    window.scrollTo({ top: 0 });
  }

  function goHome() {
    writeEntered(false);
    setEntered(false);
    setReview(null);
  }

  async function openCase(requestId: string) {
    setQueueOpen(false);
    try {
      const r = await getReview(requestId);
      writeEntered(true);
      setEntered(true);
      setReview(r);
      setTimeout(() => document.getElementById("review-result")?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not open the case");
    }
  }

  if (!ready) return <div className="min-h-screen bg-[#0B1B33]" />;

  return (
    <>
      {!entered ? (
        <Welcome userName={userName} onStart={start} onQueue={() => setQueueOpen(true)} />
      ) : (
        <div className="min-h-screen bg-gradient-to-b from-info-light/50 via-background to-background animate-in fade-in duration-500">
          <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
            <Header userName={userName} onHome={goHome} onQueue={() => setQueueOpen(true)} />
            <UploadForm onReviewComplete={setReview} />
            {review && (
              <div id="review-result">
                <ReviewDashboard key={review.request_id} review={review} />
              </div>
            )}
          </main>

          <footer className="border-t mt-16 py-6">
            <div className="mx-auto max-w-5xl px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>Eucloid · Prior Authorization Review on Databricks</span>
              <span>AI-assisted draft &mdash; all decisions require human clinical review</span>
            </div>
          </footer>
        </div>
      )}
      {queueOpen && <QueuePanel onClose={() => setQueueOpen(false)} onOpen={openCase} />}
    </>
  );
}
