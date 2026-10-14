"use client";

/**
 * Fork's home.
 *
 * Signed in: the student's academic notebook. Signed out: what Fork is, a
 * way in, and the compare tool one click away -- an account is never
 * required to try a comparison.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import AuthPanel from "@/components/notebook/AuthPanel";
import NotebookHome from "@/components/notebook/NotebookHome";
import TopBar from "@/components/notebook/TopBar";
import { ApiError } from "@/lib/types";
import { Notebook, NotSignedIn, Student, getNotebook, logout } from "@/lib/notebook";

type State =
  | { kind: "loading" }
  | { kind: "signed_out" }
  | { kind: "ready"; notebook: Notebook }
  | { kind: "error"; message: string };

export default function Home() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(() => {
    return getNotebook().then(
      (notebook): State => ({ kind: "ready", notebook }),
      (e): State =>
        e instanceof NotSignedIn
          ? { kind: "signed_out" }
          : {
              kind: "error",
              message: e instanceof ApiError ? e.message : "Fork couldn't load your notebook.",
            },
    );
  }, []);

  const reload = useCallback(() => {
    void load().then(setState);
  }, [load]);

  useEffect(() => {
    // Fetch-on-mount. State is set when the request resolves, never
    // synchronously inside the effect, and not at all once unmounted.
    let cancelled = false;
    void load().then((next) => {
      if (!cancelled) setState(next);
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function signOut() {
    try {
      await logout();
    } finally {
      setState({ kind: "signed_out" });
    }
  }

  const student: Student | null = state.kind === "ready" ? state.notebook.student : null;

  return (
    <div className="min-h-screen w-full bg-[#05070d] text-slate-200">
      <TopBar student={student} current="notebook" onSignOut={signOut} />
      {state.kind === "loading" && (
        <p role="status" className="mx-auto max-w-[1240px] px-4 py-10 text-[13px] text-slate-500">
          Opening your notebook…
        </p>
      )}
      {state.kind === "error" && (
        <div className="mx-auto max-w-[1240px] px-4 py-10">
          <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-[13px] text-rose-300">
            {state.message}
          </p>
          <button
            type="button"
            onClick={() => {
              setState({ kind: "loading" });
              reload();
            }}
            className="mt-3 text-[13px] text-cyan-300 hover:underline"
          >
            Try again
          </button>
        </div>
      )}
      {state.kind === "signed_out" && <Welcome onSignedIn={reload} />}
      {state.kind === "ready" && (
        <NotebookHome
          notebook={state.notebook}
          onNotebook={(notebook) => setState({ kind: "ready", notebook })}
        />
      )}
    </div>
  );
}

function Welcome({ onSignedIn }: { onSignedIn: () => void }) {
  return (
    <main className="mx-auto grid max-w-[1100px] grid-cols-1 gap-8 px-4 pb-16 pt-10 lg:grid-cols-[minmax(0,1fr)_400px] lg:pt-16">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-cyan-300/80">
          A fork in the road, priced
        </p>
        <h1 className="mt-3 max-w-xl text-[30px] font-semibold leading-tight tracking-tight text-slate-100">
          Your academic notebook, before the advisor meeting.
        </h1>
        <p className="mt-4 max-w-xl text-[14px] leading-relaxed text-slate-400">
          Fork keeps your degree audit, the paths you&rsquo;ve explored, and the decisions
          you&rsquo;ve made in one place — and shows where every figure comes from. Your
          documents, your own estimates, and Fork&rsquo;s calculations are always labelled
          as what they are.
        </p>
        <ul className="mt-6 max-w-xl space-y-3 text-[13px] text-slate-300">
          <Point title="Your record, with receipts">
            Credits and requirements come from your confirmed UNT degree audit, not a guess.
          </Point>
          <Point title="Paths, compared the same way every time">
            Credits, semesters, cost, and earnings for each major you&rsquo;re weighing,
            calculated from public data — the AI explains, it never does the math.
          </Point>
          <Point title="A journey you can look back on">
            What you added, compared, and decided, in order.
          </Point>
        </ul>
        <p className="mt-6 text-[13px] text-slate-500">
          Just want to try it?{" "}
          <Link href="/compare" className="font-medium text-cyan-300 hover:underline">
            Compare majors without an account →
          </Link>
        </p>
      </div>
      <div>
        <AuthPanel onSignedIn={onSignedIn} />
        <p className="mt-3 text-[11.5px] leading-relaxed text-slate-600">
          Fork helps you understand a decision before you make it. It doesn&rsquo;t replace
          your academic advisor, and confirming a document in Fork isn&rsquo;t verification
          by UNT.
        </p>
      </div>
    </main>
  );
}

function Point({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-400" />
      <span>
        <span className="font-medium text-slate-100">{title}.</span>{" "}
        <span className="text-slate-400">{children}</span>
      </span>
    </li>
  );
}
