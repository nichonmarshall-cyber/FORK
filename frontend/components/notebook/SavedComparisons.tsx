"use client";

/**
 * Saved comparisons and the plan the student is leaning toward.
 *
 * Each comparison shows its headline figures, which were calculated by
 * Fork's engine when it was saved, and what each input rested on. Marking a
 * plan records it on the journey; only one plan holds at a time.
 */

import Link from "next/link";
import { useState } from "react";
import { money, semestersDelta, shortDate } from "@/lib/format";
import { payDelta } from "@/lib/nodes";
import { ApiError } from "@/lib/types";
import {
  Notebook,
  SavedScenario,
  getNotebook,
  refreshScenario,
  removeScenario,
  updateScenario,
} from "@/lib/notebook";
import ProvenanceBadge from "./ProvenanceBadge";
import { useReadOnly } from "./readOnly";

export default function SavedComparisons({
  notebook,
  onNotebook,
}: {
  notebook: Notebook;
  onNotebook: (next: Notebook) => void;
}) {
  const saved = notebook.scenarios;

  return (
    <section
      id="comparisons"
      aria-labelledby="comparisons-heading"
      className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="comparisons-heading" className="text-[15px] font-semibold text-slate-100">
            Paths you&rsquo;ve explored
          </h2>
          <p className="mt-1 text-[12.5px] text-slate-500">
            Saved comparisons, calculated by Fork from the figures shown.
          </p>
        </div>
        <Link
          href="/compare?from=record"
          className="rounded-lg bg-cyan-500/90 px-3 py-1.5 text-[12.5px] font-semibold text-slate-950 hover:bg-cyan-400"
        >
          Compare paths
        </Link>
      </div>

      {saved.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-white/10 p-4">
          <p className="text-[13px] text-slate-300">Nothing saved yet.</p>
          <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
            Compare your major with one you&rsquo;re considering. When the map looks right,
            save it here so it&rsquo;s waiting for you — and for your advisor meeting.
          </p>
        </div>
      ) : (
        <ul className="mt-4 space-y-3">
          {saved.map((s) => (
            <ScenarioCard key={s.id} scenario={s} onNotebook={onNotebook} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ScenarioCard({
  scenario: s,
  onNotebook,
}: {
  scenario: SavedScenario;
  onNotebook: (next: Notebook) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const readOnly = useReadOnly();

  async function run(action: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      onNotebook(await getNotebook());
      if (done) setMessage(done);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const anchor = s.outcome.anchor;
  const completed = s.inputs.credits_completed;
  const inputByMajor = new Map(s.inputs.options.map((o) => [o.major, o]));
  const decisionName =
    s.decision === anchor.major_key
      ? `Stay in ${anchor.major}`
      : s.outcome.options.find((o) => o.major_key === s.decision)?.major;

  return (
    <li className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13.5px] font-medium text-slate-100">{s.title}</p>
          <p className="mt-0.5 text-[11.5px] text-slate-500">
            Saved {shortDate(s.created_at)}
            {/* Only after a real recheck: saving stamps both times a few
                microseconds apart, which isn't a recalculation. */}
            {s.calculated_at &&
            s.created_at &&
            new Date(s.calculated_at).getTime() - new Date(s.created_at).getTime() > 60_000
              ? ` · recalculated ${shortDate(s.calculated_at)}`
              : ""}
          </p>
        </div>
        {decisionName && (
          <span className="rounded-full border border-emerald-400/30 bg-emerald-400/[0.08] px-2 py-0.5 text-[11px] text-emerald-300">
            Your plan: {decisionName}
          </span>
        )}
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-slate-400">
        From {anchor.major} with {completed.value} credits completed
        {s.inputs.credits_in_progress ? ` (${s.inputs.credits_in_progress} in progress)` : ""}
        {completed.provenance && (
          <ProvenanceBadge provenance={completed.provenance} title={completed.source_label ?? undefined} />
        )}
      </p>
      {completed.note && <p className="mt-1 text-[11px] text-slate-500">{completed.note}</p>}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[480px] text-left text-[12px]">
          <caption className="sr-only">Headline figures for each option compared with {anchor.major}</caption>
          <thead>
            <tr className="text-[10.5px] uppercase tracking-[0.12em] text-slate-600">
              <th scope="col" className="py-1 pr-3 font-normal">Switch to</th>
              <th scope="col" className="py-1 pr-3 font-normal">Credits that apply</th>
              <th scope="col" className="py-1 pr-3 font-normal">Time</th>
              <th scope="col" className="py-1 pr-3 font-normal">Extra cost</th>
              <th scope="col" className="py-1 font-normal">Earnings</th>
            </tr>
          </thead>
          <tbody>
            {s.outcome.options.map((o) => {
              const input = inputByMajor.get(o.major_key);
              return (
                <tr key={o.major_key} className="border-t border-white/[0.05] align-top">
                  <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">
                    {o.major}
                  </th>
                  <td className="py-1.5 pr-3 text-slate-300">
                    {input?.credits_transferable ?? "—"}
                    {input?.provenance && (
                      <span className="ml-1.5 align-middle">
                        <ProvenanceBadge provenance={input.provenance} title={input.source_label ?? undefined} />
                      </span>
                    )}
                  </td>
                  {o.status === "calculated" && o.summary ? (
                    <>
                      <td className="py-1.5 pr-3 tabular-nums text-slate-300">
                        {semestersDelta(o.summary.incremental_semesters)}
                      </td>
                      <td className="py-1.5 pr-3 tabular-nums text-slate-300">
                        {money(o.summary.incremental_total_cost)}
                      </td>
                      <td className="py-1.5 tabular-nums text-slate-300">
                        {payDelta(o.summary.annual_salary_delta)}
                      </td>
                    </>
                  ) : (
                    <td colSpan={3} className="py-1.5 text-slate-500">
                      {o.status === "pending"
                        ? `Waiting on ${(o.missing_fields ?? ["a figure"]).join(", ").replaceAll("_", " ")}`
                        : o.error ?? "Couldn't be calculated."}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-500">
        <ProvenanceBadge provenance="derived" title={s.outcome_provenance_label} />
        Time, cost and earnings differences are Fork&rsquo;s calculation from these inputs.
      </p>

      {!readOnly && <fieldset className="mt-3" disabled={busy}>
        <legend className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
          Which way are you leaning?
        </legend>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {[
            { key: anchor.major_key, label: `Stay in ${anchor.major}` },
            ...s.outcome.options
              .filter((o) => o.status === "calculated")
              .map((o) => ({ key: o.major_key, label: `Switch to ${o.major}` })),
          ].map((choice) => {
            const active = s.decision === choice.key;
            return (
              <button
                key={choice.key}
                type="button"
                aria-pressed={active}
                onClick={() =>
                  run(() => updateScenario(s.id, { decision: active ? null : choice.key }))
                }
                className={`rounded-lg border px-2.5 py-1 text-[12px] transition ${
                  active
                    ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200"
                    : "border-white/10 text-slate-400 hover:border-cyan-400/40 hover:text-cyan-200"
                }`}
              >
                {choice.label}
              </button>
            );
          })}
        </div>
      </fieldset>}

      <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px]">
        <Link href={`/compare?scenario=${s.id}`} className="text-cyan-300 hover:underline">
          Open on the map
        </Link>
        {!readOnly && <button
          type="button"
          disabled={busy}
          onClick={() =>
            run(async () => {
              const r = await refreshScenario(s.id);
              if (!r.changed) throw new ApiError("Already up to date with your record.");
            }, "Updated with your current record.")
          }
          className="text-slate-400 hover:text-cyan-200 disabled:opacity-60"
        >
          Recheck against my record
        </button>}
        {readOnly ? null : confirmRemove ? (
          <span className="flex items-center gap-2">
            <span className="text-slate-400">Remove this comparison?</span>
            <button
              type="button"
              onClick={() => run(() => removeScenario(s.id))}
              className="rounded-md border border-rose-500/40 px-2 py-0.5 text-rose-300 hover:bg-rose-500/10"
            >
              Remove
            </button>
            <button type="button" onClick={() => setConfirmRemove(false)} className="text-slate-500">
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmRemove(true)}
            className="text-slate-500 hover:text-rose-300"
          >
            Remove
          </button>
        )}
      </div>
      {message && (
        <p role="status" className="mt-2 text-[12px] text-slate-400">
          {message}
        </p>
      )}
    </li>
  );
}
