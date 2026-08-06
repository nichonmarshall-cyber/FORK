"use client";

import { forwardRef, useId, useRef, useState } from "react";
import AskFork from "@/components/AskFork";
import DecisionMap from "@/components/DecisionMap";
import NodePanel from "@/components/NodePanel";
import Sidebar from "@/components/Sidebar";
import { NODES_BY_ID, payDelta } from "@/lib/nodes";
import { ApiError, CalcResult, calculateChangeMajor } from "@/lib/types";
import { validateCreditsPair } from "@/lib/validation";

/**
 * Major keys have to match the reference JSON exactly. Listed here rather
 * than fetched because the backend has no endpoint for them yet — worth
 * adding one so this list can't drift out of sync with the data file (it
 * already has once: this list used to include "psychology", "nursing",
 * and "mechanical_engineering", which Stage 3's data work turned into a
 * clarification case, an unsupported case, and a renamed key,
 * respectively — see backend/decision_paths/change_major/major_resolution.py).
 */
const MAJORS = [
  { key: "computer_science", label: "Computer Science" },
  { key: "information_technology", label: "Information Technology" },
  { key: "business_administration", label: "Business Administration (BBA)" },
  { key: "psychology_ba", label: "Psychology (B.A.)" },
  { key: "psychology_bs", label: "Psychology (B.S.)" },
  { key: "mechanical_energy_engineering", label: "Mechanical & Energy Engineering" },
];

const money = (n: number) =>
  `${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", {
    maximumFractionDigits: 0,
  })}`;

export default function Home() {
  const [currentMajor, setCurrentMajor] = useState("computer_science");
  const [prospectiveMajor, setProspectiveMajor] = useState("information_technology");
  // Raw text, not number — needed to control exactly what's displayed
  // (leading-zero normalization) and to represent "user typed something
  // invalid" as a real, visible state rather than silently coercing to 0.
  const [completedRaw, setCompletedRaw] = useState("72");
  const [transferableRaw, setTransferableRaw] = useState("66");
  const [touched, setTouched] = useState<{ completed: boolean; transferable: boolean }>({
    completed: false,
    transferable: false,
  });
  const [submitAttempted, setSubmitAttempted] = useState(false);

  const [result, setResult] = useState<CalcResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const completedRef = useRef<HTMLInputElement>(null);
  const transferableRef = useRef<HTMLInputElement>(null);

  const validation = validateCreditsPair(completedRaw, transferableRaw);
  // A field's error only SHOWS once the person has interacted with it (or
  // tried to submit) — otherwise every field would flash "Enter a number"
  // before anyone's typed anything, which is just noise on first load.
  const showCompletedError = (touched.completed || submitAttempted) && validation.completed.error;
  const showTransferableError =
    (touched.transferable || submitAttempted) && validation.transferable.error;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitAttempted(true);

    if (!validation.isValid) {
      // Focus the first actually-invalid field, completed before
      // transferable — matches field order in the form.
      if (validation.completed.error) {
        completedRef.current?.focus();
      } else if (validation.transferable.error) {
        transferableRef.current?.focus();
      }
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await calculateChangeMajor({
        current_major: currentMajor,
        prospective_major: prospectiveMajor,
        credits_completed: validation.completed.value as number,
        credits_transferable: validation.transferable.value as number,
      });
      setResult(data);
      setSelectedId("root");
      setSubmitAttempted(false);
    } catch (e) {
      // Deliberately does NOT touch result/selectedId. A failed request —
      // whether it's a network blip or a server-side rejection — must
      // never wipe out a map the person already successfully built. Only
      // a NEW success (above) is allowed to replace what's shown.
      const message = e instanceof ApiError ? e.message : "Something went wrong.";
      setError(message);
      if (e instanceof ApiError && e.field === "credits_transferable") {
        transferableRef.current?.focus();
      } else if (e instanceof ApiError && e.field === "credits_completed") {
        completedRef.current?.focus();
      }
    } finally {
      setLoading(false);
    }
  }

  const selectedNode = selectedId ? NODES_BY_ID.get(selectedId) ?? null : null;

  return (
    <div className="min-h-screen bg-[#05070d] text-slate-200">
      <div className="mx-auto grid max-w-[1840px] grid-cols-1 gap-4 p-4 xl:grid-cols-[172px_250px_minmax(0,1fr)_300px]">
        <div className="hidden xl:block">
          <Sidebar result={result} />
        </div>

        {/* ---- Scenario ---- */}
        <section className="space-y-5 rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5">
          <div>
            <h1 className="text-[15px] font-semibold text-slate-100">
              Your situation
            </h1>
            <p className="mt-1 text-[12.5px] leading-relaxed text-slate-500">
              Everything on the map is calculated from these four values.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5" noValidate>
            <div className="space-y-4 border-t border-white/[0.07] pt-5">
              <Select label="Current major" value={currentMajor} onChange={setCurrentMajor} />
              <Select label="Considering" value={prospectiveMajor} onChange={setProspectiveMajor} />
              <NumberField
                ref={completedRef}
                label="Credits completed"
                displayValue={validation.completed.display}
                onChange={setCompletedRaw}
                onBlur={() => setTouched((t) => ({ ...t, completed: true }))}
                hint="Courses you've finished and passed."
                error={showCompletedError ? validation.completed.error : null}
              />
              <NumberField
                ref={transferableRef}
                label="Credits that transfer"
                displayValue={validation.transferable.display}
                onChange={setTransferableRaw}
                onBlur={() => setTouched((t) => ({ ...t, transferable: true }))}
                hint="Counting toward the new degree, electives included."
                error={showTransferableError ? validation.transferable.error : null}
              />
            </div>

            <button
              type="submit"
              // Deliberately NOT the native `disabled` attribute: a
              // disabled button never fires onClick/onSubmit at all,
              // which would make "move focus to the invalid field after
              // an attempted submission" impossible to satisfy — there'd
              // be no attempt to react to. aria-disabled communicates the
              // same state to assistive tech and gets the same visual
              // treatment via the styles below, while handleSubmit
              // itself remains the actual gate (it re-checks validity and
              // returns early without calling the API). Only genuinely
              // disabled during the real network request, where a second
              // click really should do nothing.
              disabled={loading}
              aria-disabled={!validation.isValid || loading}
              title={
                !validation.isValid
                  ? "Fix the highlighted field before calculating"
                  : undefined
              }
              className={`w-full rounded-xl px-4 py-2.5 text-[13.5px] font-semibold text-slate-950 shadow-[0_0_22px_-6px_#22d3ee] transition ${
                !validation.isValid || loading
                  ? "cursor-not-allowed bg-cyan-500/40 opacity-50"
                  : "cursor-pointer bg-cyan-500/90 hover:bg-cyan-400"
              }`}
            >
              {loading ? "Calculating…" : "Show me the difference"}
            </button>
          </form>

          {error && (
            <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-rose-300">
              {error}
            </p>
          )}

          {result && (
            <div className="space-y-3 border-t border-white/[0.07] pt-5">
              <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
                How this affects you
              </p>
              <Affect
                label="Time to graduate"
                value={
                  result.summary.incremental_semesters === 0
                    ? "No change"
                    : `${result.summary.incremental_semesters > 0 ? "+" : "−"}${Math.abs(result.summary.incremental_semesters)} semesters`
                }
                bad={result.summary.incremental_semesters > 0}
              />
              <Affect
                label="Est. additional cost"
                value={money(result.summary.incremental_total_cost)}
                bad={result.summary.incremental_total_cost > 0}
              />
              {/* Not "starting salary": the figure is a median measured at
                  a stated point after graduation, and calling it a starting
                  salary implies a precision and a timing the data doesn't
                  have. payDelta also handles two non-"real number" states:
                  null (comparison unavailable — must not render as $0) and
                  a genuine 0 (CS and IT share one federal earnings
                  category, so "no difference" is real information, not a
                  missing value — worded as "No change in pay" instead of
                  a bare $0 that would read as broken data). */}
              <Affect
                label="Earnings 1 yr after graduation"
                value={payDelta(result.summary.annual_salary_delta)}
                bad={(result.summary.annual_salary_delta ?? 0) < 0}
              />
            </div>
          )}
        </section>

        {/* ---- Map ---- */}
        <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#060911]">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-3.5">
            <div>
              <h2 className="text-[15px] font-semibold text-slate-100">
                Change Major
              </h2>
              <p className="text-[12px] text-slate-500">
                {result
                  ? `${result.summary.current_major} → ${result.summary.prospective_major}`
                  : "Set your situation, then explore what each part costs."}
              </p>
            </div>
            <Legend />
          </header>

          <div className="aspect-[1000/720] w-full">
            <DecisionMap
              result={result}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>

          {result && (
            <div className="grid grid-cols-1 gap-px border-t border-white/[0.07] bg-white/[0.07] sm:grid-cols-2">
              <PathCard
                title={`Finish ${result.summary.current_major}`}
                items={result.comparison.staying.line_items}
              />
              <PathCard
                title={`Switch to ${result.summary.prospective_major}`}
                items={result.comparison.switching.line_items}
              />
            </div>
          )}

          <div className="border-t border-white/[0.07] p-4">
            <AskFork
              result={result}
              calcInputs={{
                current_major: currentMajor,
                prospective_major: prospectiveMajor,
                credits_completed: validation.completed.value ?? 0,
                credits_transferable: validation.transferable.value ?? 0,
              }}
              selectedNode={
                selectedNode
                  ? {
                      id: selectedNode.id,
                      label: selectedNode.label,
                      question: selectedNode.question,
                    }
                  : null
              }
              onSelectNode={setSelectedId}
            />
          </div>
        </section>

        {/* ---- Detail ---- */}
        <NodePanel
          node={selectedNode}
          result={result}
          onClose={() => setSelectedId(null)}
        />
      </div>
    </div>
  );
}

function Affect({
  label,
  value,
  bad,
}: {
  label: string;
  value: string;
  bad: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2">
      <span className="text-[12.5px] text-slate-400">{label}</span>
      <span
        className="shrink-0 text-[13px] font-semibold tabular-nums"
        style={{ color: bad ? "#fbbf24" : "#34d399" }}
      >
        {value}
      </span>
    </div>
  );
}

function Legend() {
  const items = [
    { label: "Answered", color: "#34d399", dash: false },
    { label: "Moves against you", color: "#fbbf24", dash: false },
    { label: "Needs info", color: "#38bdf8", dash: true },
    { label: "Not available yet", color: "#46536d", dash: false },
  ];
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden>
            <circle
              cx="5"
              cy="5"
              r="4"
              fill="none"
              stroke={i.color}
              strokeWidth="1.4"
              strokeDasharray={i.dash ? "2 1.8" : undefined}
            />
          </svg>
          {i.label}
        </li>
      ))}
    </ul>
  );
}

function PathCard({
  title,
  items,
}: {
  title: string;
  items: { label: string; value: number | null }[];
}) {
  return (
    <div className="bg-[#0a0e17] px-5 py-4">
      <h3 className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        {title}
      </h3>
      <dl className="mt-3 space-y-1.5">
        {items.map((li) => {
          const isMoney = li.label.toLowerCase().includes("tuition");
          const isSemesters = li.label.toLowerCase().includes("semester");
          return (
            <div key={li.label} className="flex justify-between gap-4 text-[12.5px]">
              <dt className="text-slate-500">{li.label}</dt>
              <dd className="shrink-0 tabular-nums text-slate-200">
                {/* A null value means the figure genuinely isn't published
                    (federal privacy suppression, or no data). Say that
                    plainly — rendering 0 or a dash would read as a real
                    number, or as a rendering bug. */}
                {li.value === null ? (
                  <span className="text-slate-500">Not available</span>
                ) : isMoney ? (
                  money(li.value)
                ) : isSemesters ? (
                  `${li.value} semesters`
                ) : (
                  li.value
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#0e141f] px-3 py-2 text-[13px] text-slate-200 outline-none focus:border-cyan-400/50"
      >
        {MAJORS.map((m) => (
          <option key={m.key} value={m.key}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );
}

interface NumberFieldProps {
  label: string;
  displayValue: string;
  onChange: (v: string) => void;
  onBlur: () => void;
  hint: string;
  error: string | null;
}

// forwardRef called with NO explicit generic arguments on purpose: a
// call like `forwardRef<A, B>(...)` — two comma-separated type
// arguments — is a known ambiguity in .tsx files (the parser has to
// decide whether `<A,` starts a generic call or a JSX element), and it
// parses differently across TypeScript versions. Passing an already-typed
// function instead lets TypeScript infer both type parameters from the
// function's own signature, which sidesteps the ambiguous syntax
// entirely rather than trying to work around it.
function NumberFieldInner(
  { label, displayValue, onChange, onBlur, hint, error }: NumberFieldProps,
  ref: React.ForwardedRef<HTMLInputElement>,
) {
  const errorId = useId();
  return (
    <label className="block">
      <span className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        {label}
      </span>
      <input
        ref={ref}
        type="text"
        inputMode="numeric"
        value={displayValue}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={`mt-1.5 w-full rounded-lg border bg-[#0e141f] px-3 py-2 text-[13px] tabular-nums text-slate-200 outline-none focus:border-cyan-400/50 ${
          error ? "border-rose-500/60 focus:border-rose-500/60" : "border-white/10"
        }`}
      />
      {error ? (
        <span
          id={errorId}
          role="alert"
          className="mt-1 block text-[11px] leading-relaxed text-rose-400"
        >
          {error}
        </span>
      ) : (
        <span className="mt-1 block text-[11px] leading-relaxed text-slate-600">
          {hint}
        </span>
      )}
    </label>
  );
}

const NumberField = forwardRef(NumberFieldInner);