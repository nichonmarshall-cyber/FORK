"use client";

/**
 * "Who you are academically" -- the top of the notebook.
 *
 * Every figure carries its provenance badge and, underneath, the exact
 * source it came from. A figure Fork doesn't have is shown as missing with
 * what would fill it, never as zero.
 */

import { useEffect, useState } from "react";
import { MAJORS } from "@/lib/majors";
import { hours } from "@/lib/format";
import { ApiError } from "@/lib/types";
import {
  DerivedFact,
  Fact,
  Notebook,
  ProfileEdits,
  Snapshot,
  updateProfile,
} from "@/lib/notebook";
import ProvenanceBadge from "./ProvenanceBadge";
import { Field, INPUT } from "./AuthPanel";

export default function SnapshotCard({
  notebook,
  onNotebook,
}: {
  notebook: Notebook;
  onNotebook: (next: Notebook) => void;
}) {
  const s = notebook.snapshot;
  // Next steps and the empty state link to #record-details; arriving with
  // that hash opens the form. Read once at mount (this renders after the
  // notebook loads, never during server rendering) and on later hash
  // changes, rather than synchronising in an effect.
  const [editing, setEditing] = useState(
    () => typeof window !== "undefined" && window.location.hash === "#record-details",
  );
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === "#record-details") setEditing(true);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <section
      aria-labelledby="snapshot-heading"
      className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="snapshot-heading" className="text-[15px] font-semibold text-slate-100">
            Your academic snapshot
          </h2>
          <p className="mt-1 text-[12.5px] text-slate-500">
            {s.institution.name}
            {s.current_major?.display ? ` · ${s.current_major.display}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          aria-expanded={editing}
          aria-controls="record-details"
          className="rounded-lg border border-white/10 px-3 py-1.5 text-[12px] text-slate-300 hover:border-cyan-400/40 hover:text-cyan-200"
        >
          {editing ? "Close" : "Update your details"}
        </button>
      </div>

      <dl className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Tile
          label="Major"
          fact={s.current_major}
          render={(f) => f.display ?? String(f.value)}
          empty="Not set yet"
          sub={s.program ? `Program on your audit: ${s.program.value}` : undefined}
        />
        <Tile label="Catalog year" fact={s.catalog_year} empty="Not set yet" />
        <Tile
          label="GPA"
          fact={s.gpa}
          render={(f) => Number(f.value).toFixed(2)}
          empty="Not added"
          emptyHint="Fork doesn't read GPA from audits yet."
        />
        <Tile
          label="Credits completed"
          fact={s.credits_completed}
          empty="Not known yet"
          emptyHint="Add a degree audit or enter it yourself."
        />
        <Tile label="Credits in progress" fact={s.credits_in_progress} empty="Not known yet" />
        <DegreeProgress snapshot={s} />
      </dl>

      {s.applicable_credits.length > 0 && (
        <div className="mt-4 rounded-xl border border-violet-400/15 bg-violet-400/[0.03] p-3.5">
          <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
            Credits that would apply elsewhere
          </p>
          <ul className="mt-2 space-y-2">
            {s.applicable_credits.map((f) => (
              <li key={f.scope} className="flex flex-wrap items-center gap-2 text-[13px] text-slate-200">
                <span>
                  <span className="font-semibold tabular-nums">{f.value}</span> hours would
                  apply to {f.display ?? f.scope}
                </span>
                <ProvenanceBadge provenance={f.provenance} title={f.source_label} />
                <span className="w-full text-[11px] text-slate-500">{f.source_label}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-4 text-[11.5px] leading-relaxed text-slate-500">
        {s.graduation.message}
      </p>

      {editing && (
        <RecordDetailsForm
          snapshot={s}
          onSaved={(next) => {
            onNotebook(next);
            setEditing(false);
          }}
        />
      )}
    </section>
  );
}

function Tile<T>({
  label,
  fact,
  render,
  empty,
  emptyHint,
  sub,
}: {
  label: string;
  fact: (Fact<T> & { display?: string | null }) | null;
  render?: (f: Fact<T> & { display?: string | null }) => string;
  empty: string;
  emptyHint?: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
      <dt className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">{label}</dt>
      <dd className="mt-1.5">
        {fact ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[17px] font-semibold tabular-nums text-slate-100">
                {render ? render(fact) : String(fact.value)}
              </span>
              <ProvenanceBadge provenance={fact.provenance} title={fact.source_label} />
            </div>
            <p className="mt-1 text-[11px] leading-snug text-slate-500">
              {fact.source_label}
              {fact.source_date && fact.source_date !== "Not stated" ? ` · ${fact.source_date}` : ""}
            </p>
            {sub && <p className="mt-1 text-[11px] text-slate-500">{sub}</p>}
          </>
        ) : (
          <>
            <span className="text-[13.5px] text-slate-500">{empty}</span>
            {emptyHint && <p className="mt-1 text-[11px] text-slate-600">{emptyHint}</p>}
          </>
        )}
      </dd>
    </div>
  );
}

/** Degree progress, from the strongest evidence available: the audit's own
 * degree-hours block, then Fork's derived "credits still needed", then an
 * honest blank. */
function DegreeProgress({ snapshot }: { snapshot: Snapshot }) {
  const dh = snapshot.degree_hours;
  const remaining: DerivedFact | null = snapshot.credits_remaining_current;

  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
      <dt className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        Degree progress
      </dt>
      <dd className="mt-1.5">
        {dh ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[17px] font-semibold tabular-nums text-slate-100">
                {hours(dh.value.needed)} still needed
              </span>
              <ProvenanceBadge provenance={dh.provenance} title={dh.source_label} />
            </div>
            <p className="mt-1 text-[11px] leading-snug text-slate-500">
              {`${hours(dh.value.earned)} applied · ${hours(dh.value.in_progress)} in progress, per your audit’s degree total`}
            </p>
            {snapshot.requirements && (
              <p className="mt-1 text-[11px] text-slate-500">
                {snapshot.requirements.value.complete} of {snapshot.requirements.value.total}{" "}
                requirement blocks complete
              </p>
            )}
          </>
        ) : remaining ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[17px] font-semibold tabular-nums text-slate-100">
                {remaining.value} credits still needed
              </span>
              <ProvenanceBadge provenance="derived" title={remaining.source_label} />
            </div>
            <p className="mt-1 text-[11px] leading-snug text-slate-500">{remaining.source_label}</p>
          </>
        ) : (
          <>
            <span className="text-[13.5px] text-slate-500">Not known yet</span>
            <p className="mt-1 text-[11px] text-slate-600">
              Needs your major and completed credits.
            </p>
          </>
        )}
      </dd>
    </div>
  );
}

// --- editing student-reported facts -------------------------------------

type Draft = {
  current_major: string;
  gpa: string;
  credits_completed: string;
  credits_in_progress: string;
  catalog_year: string;
};

function initialDraft(s: Snapshot): Draft {
  return {
    current_major: s.current_major ? String(s.current_major.value) : "",
    gpa: s.gpa ? String(s.gpa.value) : "",
    credits_completed: s.credits_completed ? String(s.credits_completed.value) : "",
    credits_in_progress: s.credits_in_progress ? String(s.credits_in_progress.value) : "",
    catalog_year: s.catalog_year ? String(s.catalog_year.value) : "",
  };
}

function RecordDetailsForm({
  snapshot,
  onSaved,
}: {
  snapshot: Snapshot;
  onSaved: (next: Notebook) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(snapshot));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const original = initialDraft(snapshot);

  const locked = (f: Fact | null) => f !== null && f.provenance !== "student_reported";

  function parse(): ProfileEdits | string {
    const edits: ProfileEdits = {};
    if (draft.current_major !== original.current_major) {
      edits.current_major = draft.current_major || null;
    }
    if (draft.catalog_year !== original.catalog_year) {
      edits.catalog_year = draft.catalog_year.trim() || null;
    }
    if (draft.gpa !== original.gpa) {
      if (draft.gpa.trim() === "") edits.gpa = null;
      else {
        const v = Number(draft.gpa);
        if (!Number.isFinite(v) || v < 0 || v > 4) return "GPA must be between 0.00 and 4.00.";
        edits.gpa = v;
      }
    }
    for (const key of ["credits_completed", "credits_in_progress"] as const) {
      if (draft[key] !== original[key]) {
        if (draft[key].trim() === "") edits[key] = null;
        else {
          const v = Number(draft[key]);
          const max = key === "credits_completed" ? 300 : 30;
          if (!Number.isInteger(v) || v < 0 || v > max) {
            return key === "credits_completed"
              ? "Completed credits must be a whole number from 0 to 300."
              : "Credits in progress must be a whole number from 0 to 30.";
          }
          edits[key] = v;
        }
      }
    }
    return edits;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const edits = parse();
    if (typeof edits === "string") {
      setError(edits);
      return;
    }
    if (Object.keys(edits).length === 0) {
      setError("Nothing has changed.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await updateProfile(edits));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save your details.");
    } finally {
      setBusy(false);
    }
  }

  const lockedNote = (f: Fact | null) =>
    locked(f) ? `From ${f!.source_label}. Add a newer document to change it.` : undefined;

  return (
    <form
      id="record-details"
      onSubmit={submit}
      noValidate
      className="mt-5 space-y-4 border-t border-white/[0.07] pt-5"
    >
      <p className="text-[12px] leading-relaxed text-slate-400">
        Anything you enter here is labelled as your own figure. Values that come from a
        document you confirmed can only change with a newer document.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Current major" hint={lockedNote(snapshot.current_major)}>
          <select
            value={draft.current_major}
            disabled={locked(snapshot.current_major)}
            onChange={(e) => setDraft({ ...draft, current_major: e.target.value })}
            className={`${INPUT} disabled:opacity-60`}
          >
            <option value="">Not set</option>
            {MAJORS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Catalog year" hint={lockedNote(snapshot.catalog_year) ?? "e.g. Fall 2024"}>
          <input
            value={draft.catalog_year}
            disabled={locked(snapshot.catalog_year)}
            onChange={(e) => setDraft({ ...draft, catalog_year: e.target.value })}
            maxLength={32}
            className={`${INPUT} disabled:opacity-60`}
          />
        </Field>
        <Field label="GPA" hint="Your cumulative GPA, 0.00–4.00.">
          <input
            inputMode="decimal"
            value={draft.gpa}
            onChange={(e) => setDraft({ ...draft, gpa: e.target.value })}
            className={INPUT}
          />
        </Field>
        <Field label="Credits completed" hint={lockedNote(snapshot.credits_completed)}>
          <input
            inputMode="numeric"
            value={draft.credits_completed}
            disabled={locked(snapshot.credits_completed)}
            onChange={(e) => setDraft({ ...draft, credits_completed: e.target.value })}
            className={`${INPUT} disabled:opacity-60`}
          />
        </Field>
        <Field label="Credits in progress" hint={lockedNote(snapshot.credits_in_progress)}>
          <input
            inputMode="numeric"
            value={draft.credits_in_progress}
            disabled={locked(snapshot.credits_in_progress)}
            onChange={(e) => setDraft({ ...draft, credits_in_progress: e.target.value })}
            className={`${INPUT} disabled:opacity-60`}
          />
        </Field>
      </div>
      {error && (
        <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-300">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="rounded-xl bg-cyan-500/90 px-4 py-2 text-[13px] font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
      >
        {busy ? "Saving…" : "Save my details"}
      </button>
    </form>
  );
}
