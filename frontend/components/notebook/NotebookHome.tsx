"use client";

/**
 * The student's academic notebook: the product's home once signed in.
 *
 * Reads one payload from GET /notebook and lays it out. Reading never
 * changes anything; every edit goes through a component that asks the
 * backend and then re-renders from what the backend returns, so the screen
 * can't drift from the stored record.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { logout, type Notebook } from "@/lib/notebook";
import BrainMap from "./BrainMap";
import { ReadOnlyContext } from "./readOnly";
import SnapshotCard from "./SnapshotCard";
import RecordSection from "./RecordSection";
import SavedComparisons from "./SavedComparisons";
import JourneyTimeline from "./JourneyTimeline";
import NextSteps, { ProvenanceLegend } from "./NextSteps";

export default function NotebookHome({
  notebook,
  onNotebook,
}: {
  notebook: Notebook;
  onNotebook: (next: Notebook) => void;
}) {
  const name = notebook.student.display_name;
  const isDemo = notebook.student.is_demo === true;
  // "#map" opens the brain map directly, so it can be linked to.
  const [view, setView] = useState<"notebook" | "map">(() =>
    typeof window !== "undefined" && window.location.hash === "#map" ? "map" : "notebook",
  );
  useEffect(() => {
    const onHash = () => setView(window.location.hash === "#map" ? "map" : "notebook");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  function choose(next: "notebook" | "map") {
    setView(next);
    const url = next === "map" ? "#map" : window.location.pathname;
    window.history.replaceState(null, "", url);
  }

  return (
    <ReadOnlyContext.Provider value={isDemo}>
    <main className="mx-auto max-w-[1240px] px-4 pb-16 pt-6">
      {isDemo && <DemoBanner />}
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-100">
            {name ? `${name}'s notebook` : "Your notebook"}
          </h1>
          <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-slate-500">
            Your academic record, the paths you&rsquo;ve explored, and why Fork says what it
            says — so you can walk into your advisor&rsquo;s office already knowing the
            questions to ask.
          </p>
        </div>
        <div
          role="tablist"
          aria-label="Notebook view"
          className="flex gap-1 rounded-xl border border-white/[0.07] bg-white/[0.02] p-1"
        >
          {(["notebook", "map"] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => choose(v)}
              className={`rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition ${
                view === v ? "bg-cyan-400/10 text-cyan-300" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {v === "notebook" ? "Notebook" : "Brain map"}
            </button>
          ))}
        </div>
      </div>

      {view === "map" ? (
        <BrainMap notebook={notebook} />
      ) : (
      <>
      {!notebook.has_record && <StartHere />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-4">
          <SnapshotCard notebook={notebook} onNotebook={onNotebook} />
          {/* On a phone the side column stacks last, which would bury the
              most actionable section under the whole journey. */}
          <div className="lg:hidden">
            <NextSteps steps={notebook.next_steps} id="next-mobile" />
          </div>
          <SavedComparisons notebook={notebook} onNotebook={onNotebook} />
          <JourneyTimeline events={notebook.timeline} />
        </div>
        <aside className="space-y-4" aria-label="Your record and next steps">
          <div className="hidden lg:block">
            <NextSteps steps={notebook.next_steps} />
          </div>
          <RecordSection notebook={notebook} onNotebook={onNotebook} />
          <ProvenanceLegend />
        </aside>
      </div>
      </>
      )}
    </main>
    </ReadOnlyContext.Provider>
  );
}

function DemoBanner() {
  return (
    <div
      role="note"
      className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300/25 bg-amber-300/[0.06] px-4 py-3"
    >
      <p className="text-[12.5px] leading-relaxed text-amber-100/90">
        <span className="font-semibold">Demo notebook.</span> Jordan is a fictional student and
        every document here is made up. The comparisons are real: Fork calculated them from
        these figures and public data. Nothing can be changed.
      </p>
      <button
        type="button"
        onClick={async () => {
          // Leave the demo, then land on sign-up rather than back in it.
          try {
            await logout();
          } finally {
            window.location.assign("/?create=1");
          }
        }}
        className="shrink-0 rounded-lg bg-cyan-500/90 px-3 py-1.5 text-[12px] font-semibold text-slate-950 hover:bg-cyan-400"
      >
        Make your own
      </button>
    </div>
  );
}

function StartHere() {
  return (
    <section
      aria-labelledby="start-heading"
      className="mb-4 rounded-2xl border border-cyan-400/20 bg-gradient-to-br from-cyan-400/[0.06] to-violet-400/[0.04] p-5"
    >
      <h2 id="start-heading" className="text-[15px] font-semibold text-slate-100">
        Your notebook is empty — here&rsquo;s where to start
      </h2>
      <ol className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <StartItem
          n={1}
          title="Add your degree audit"
          body="Upload your UNT degree audit PDF. You check Fork's reading before anything is used."
          href="/compare?panel=audit"
          cta="Upload an audit"
        />
        <StartItem
          n={2}
          title="Or enter your details"
          body="No audit handy? Type your major and credits. They're labelled as your own figures."
          href="/#record-details"
          cta="Enter details"
        />
        <StartItem
          n={3}
          title="Compare a path"
          body="See what switching majors means for credits, time, cost, and earnings — then save it."
          href="/compare?from=record"
          cta="Compare paths"
        />
      </ol>
    </section>
  );
}

function StartItem({
  n,
  title,
  body,
  href,
  cta,
}: {
  n: number;
  title: string;
  body: string;
  href: string;
  cta: string;
}) {
  return (
    <li className="rounded-xl border border-white/[0.07] bg-[#0a0e17]/70 p-3.5">
      <p className="text-[10.5px] uppercase tracking-[0.15em] text-cyan-300/80">Step {n}</p>
      <p className="mt-1 text-[13.5px] font-medium text-slate-100">{title}</p>
      <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{body}</p>
      <Link href={href} className="mt-2 inline-block text-[12px] font-medium text-cyan-300 hover:underline">
        {cta} →
      </Link>
    </li>
  );
}
