"use client";

import { forwardRef, useId, useMemo, useRef, useState } from "react";
import AuditPanel from "@/components/AuditPanel";
import DecisionMap from "@/components/DecisionMap";
import DecisionChat from "@/components/chat/DecisionChat";
import PathNavigator from "@/components/PathNavigator";
import CompareModeToggle, { CompareMode } from "@/components/form/CompareModeToggle";
import MultiOptionInputs, {
  DraftOption,
  MAX_OPTIONS,
  validateAllOptions,
} from "@/components/form/MultiOptionInputs";
import NodePanel from "@/components/NodePanel";
import Sidebar from "@/components/Sidebar";
import { NODES_BY_ID, payDelta } from "@/lib/nodes";
import { MAJORS } from "@/lib/majors";
import {
  ApiError,
  AppliedOptionChange,
  CalcResult,
  MultiComparisonResponse,
  calculateChangeMajor,
  startComparison,
} from "@/lib/types";
import { validateCreditsPair } from "@/lib/validation";
import { AuditSession } from "@/lib/audit";

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
  // The exact inputs that produced `result`. Distinct from the draft form
  // state above: those change the instant a dropdown moves, while this
  // only advances when a calculation actually succeeds. Ask Fork reads
  // THIS, so changing a dropdown without recalculating can never silently
  // shift the factual context Fork explains away from the numbers still
  // on screen.
  const [calculatedInputs, setCalculatedInputs] = useState<{
    current_major: string;
    prospective_major: string;
    credits_completed: number;
    credits_transferable: number;
  } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // The confirmed audit, when there is one. Held alongside the manual
  // fields rather than replacing them: reverting has to restore what the
  // student typed, so those values are never overwritten -- see
  // handleAuditConfirmed, which saves them before prefilling.
  const [auditSession, setAuditSession] = useState<AuditSession | null>(null);
  const [manualBackup, setManualBackup] = useState<{
    completed: string;
    transferable: string;
  } | null>(null);

  const auditInputs = auditSession?.change_major_inputs ?? null;
  const auditActive = auditSession?.uploaded_source.is_active ?? false;
  // The one figure a degree audit doesn't establish. The backend says so
  // explicitly rather than the frontend inferring it from an absent field,
  // and it ships the sentence to show -- so when a matcher exists and the
  // entry disappears, this field stops explaining itself automatically.
  const transferableUnavailable =
    auditInputs?.unavailable.find((u) => u.field === "credits_transferable") ?? null;

  function handleAuditConfirmed(session: AuditSession) {
    const inputs = session.change_major_inputs;
    if (!inputs) return;
    // Saved before the overwrite, so "go back to entering credits myself"
    // returns the student's own numbers rather than an empty form.
    setManualBackup({ completed: completedRaw, transferable: transferableRaw });
    setCompletedRaw(String(inputs.credits_completed));
    // credits_transferable is deliberately left alone: the audit doesn't
    // establish it, so whatever the student entered stands.
  }

  function handleAuditReverted() {
    if (manualBackup) {
      setCompletedRaw(manualBackup.completed);
      setTransferableRaw(manualBackup.transferable);
      setManualBackup(null);
    }
  }

  // --- Multi-option comparison ---------------------------------------
  //
  // Four separate concepts, deliberately not collapsed into fewer:
  //
  //   compareMode        which form is showing
  //   draftOptions       what's typed but not yet submitted
  //   multiComparison    the last SUCCESSFUL fan-out (trusted)
  //   selectedDetailPath which alternative's map is on screen
  //
  // activeOptions is NOT here. It lives in the backend session and is
  // mirrored from every response, because a typed instruction like "just
  // compare CS and IT" changes it server-side and a second client-side
  // copy would immediately disagree.
  const [compareMode, setCompareMode] = useState<CompareMode>("one");
  const [draftOptions, setDraftOptions] = useState<DraftOption[]>([]);
  const [multiComparison, setMultiComparison] =
    useState<MultiComparisonResponse | null>(null);
  const [selectedDetailPath, setSelectedDetailPath] = useState<string | null>(null);
  const [multiSubmitAttempted, setMultiSubmitAttempted] = useState(false);

  const optionRefs = useRef<Record<string, HTMLInputElement | null>>({});

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
        // Provenance travels with the figures so the panel can say which
        // came from a document and which the student estimated. When no
        // audit is active these are omitted and the backend's
        // "Student-reported" defaults apply, exactly as before.
        ...(auditActive && auditInputs
          ? {
              credits_source: auditInputs.credits_source,
              credits_source_date: auditInputs.credits_source_date,
              credits_in_progress: auditInputs.credits_in_progress,
            }
          : {}),
      });
      setResult(data);
      setCalculatedInputs({
        current_major: currentMajor,
        prospective_major: prospectiveMajor,
        credits_completed: validation.completed.value as number,
        credits_transferable: validation.transferable.value as number,
      });
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

  // --- Multi-option derived state ------------------------------------

  const isMulti = compareMode === "multiple";

  /** Only the alternatives the backend still considers active. This is
   * what "1 of N" counts — the anchor is what they're measured against,
   * not one of the numbered options. */
  const activePaths = useMemo(() => {
    if (!multiComparison) return [];
    const active = new Set(multiComparison.state.active_options);
    return multiComparison.comparison.options.filter((o) =>
      active.has(o.major_key),
    );
  }, [multiComparison]);

  /** The alternative currently on the map. Falls back to the first
   * calculated path when the selected one was removed from the active set
   * by a conversational instruction. */
  const effectiveDetailPath = useMemo(() => {
    if (activePaths.length === 0) return null;
    const stillActive = activePaths.some(
      (o) => o.major_key === selectedDetailPath && o.status === "calculated",
    );
    if (stillActive) return selectedDetailPath;
    return (
      activePaths.find((o) => o.status === "calculated")?.major_key ?? null
    );
  }, [activePaths, selectedDetailPath]);

  const detailResult: CalcResult | null = useMemo(() => {
    if (!isMulti || !effectiveDetailPath) return null;
    const option = activePaths.find((o) => o.major_key === effectiveDetailPath);
    return (option?.detail as CalcResult | undefined) ?? null;
  }, [isMulti, effectiveDetailPath, activePaths]);

  // What the workspace actually renders. In multi mode that's whichever
  // path the navigator has selected; in single mode it's the pairwise
  // result. One variable so the map and node panel don't each have to
  // know which mode is active.
  const displayedResult = isMulti ? detailResult : result;

  const multiValidation = validateAllOptions(draftOptions, completedRaw);

  function handleModeChange(next: CompareMode) {
    if (next === compareMode) return;
    setCompareMode(next);
    setError(null);

    if (next === "multiple") {
      // Seed the first row from whatever the pairwise form already has,
      // so switching modes doesn't throw away what they just typed.
      const seeded: DraftOption[] = [
        { major: prospectiveMajor, transferableRaw: transferableRaw },
      ];
      const nextFree = MAJORS.find(
        (m) => m.key !== currentMajor && m.key !== prospectiveMajor,
      );
      if (nextFree) seeded.push({ major: nextFree.key, transferableRaw: "" });
      setDraftOptions(seeded);
      setMultiSubmitAttempted(false);
    } else {
      // Back to a clean pairwise slate. The multi session is abandoned
      // rather than kept warm — holding a hidden conversation the student
      // can't see would make "just compare CS and IT" apply to something
      // invisible.
      setMultiComparison(null);
      setSelectedDetailPath(null);
      setDraftOptions([]);
    }
  }

  async function handleMultiSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMultiSubmitAttempted(true);

    if (validation.completed.error) {
      completedRef.current?.focus();
      return;
    }
    if (!multiValidation.isValid) {
      const firstBad = draftOptions.find((o) => multiValidation.errors[o.major]);
      if (firstBad) optionRefs.current[firstBad.major]?.focus();
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await startComparison({
        current_major: currentMajor,
        credits_completed: validation.completed.value as number,
        options: draftOptions.map((o) => ({
          major: o.major,
          credits_transferable: Number(o.transferableRaw),
        })),
      });
      setMultiComparison(response);
      // Open on the first path that actually has numbers.
      const firstCalculated = response.comparison.options.find(
        (o) => o.status === "calculated",
      );
      setSelectedDetailPath(firstCalculated?.major_key ?? null);
      setSelectedId("root");
      setMultiSubmitAttempted(false);
    } catch (e) {
      // Same rule as the pairwise path: a failed request never wipes a
      // comparison the student already built successfully.
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  /** Applies a chat-resolved Compare One "replace" (see
   * conversation.orchestrator.handle_pairwise_turn). When a transfer
   * figure came with it, this recomputes immediately through the exact
   * same calculate/explain trust path a manual form submission already
   * uses -- chat never gets a shortcut around validation. When no figure
   * was given yet, only the draft major updates and the transfer field is
   * cleared/invalidated so the OLD major's figure can never be reused for
   * the new one; Ask Fork's own reply already asked for the real number. */
  async function handlePairwiseOptionChange(change: AppliedOptionChange) {
    setProspectiveMajor(change.major);
    if (change.credits_transferable === null) {
      setTransferableRaw("");
      return;
    }
    setTransferableRaw(String(change.credits_transferable));
    setLoading(true);
    setError(null);
    try {
      const data = await calculateChangeMajor({
        current_major: currentMajor,
        prospective_major: change.major,
        credits_completed: validation.completed.value as number,
        credits_transferable: change.credits_transferable,
      });
      setResult(data);
      setCalculatedInputs({
        current_major: currentMajor,
        prospective_major: change.major,
        credits_completed: validation.completed.value as number,
        credits_transferable: change.credits_transferable,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  /** Syncs the canonical comparison snapshot after a chat-driven option
   * change (e.g. a genuinely new option added) so the Decision Map and
   * PathNavigator reflect it immediately -- /comparison/ask now returns
   * the full snapshot on every "complete" response for exactly this. */
  function handleComparisonSnapshot(comparison: MultiComparisonResponse["comparison"]) {
    setMultiComparison((prev) => (prev ? { ...prev, comparison } : prev));
  }

  /** A pending path has no result to show, so send the student to the
   * input that's missing instead of swapping to an empty map. */
  function handleFocusPending(majorKey: string) {
    setMultiSubmitAttempted(true);
    const option = multiComparison?.comparison.options.find(
      (o) => o.major_key === majorKey,
    );
    setError(
      option
        ? `${option.major} isn't calculated yet — Fork needs ${(
            option.missing_fields ?? ["more information"]
          ).join(", ")}.`
        : null,
    );
    optionRefs.current[majorKey]?.focus();
  }

  return (
    <div className="min-h-screen bg-[#05070d] text-slate-200">
      <div className="mx-auto grid max-w-[1840px] grid-cols-1 gap-4 p-4 xl:grid-cols-[172px_250px_minmax(0,1fr)_300px]">
        <div className="hidden xl:block">
          <Sidebar result={displayedResult} />
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

          <form
            onSubmit={isMulti ? handleMultiSubmit : handleSubmit}
            className="space-y-5"
            noValidate
          >
            <div className="space-y-4 border-t border-white/[0.07] pt-5">
              <Select label="Current major" value={currentMajor} onChange={setCurrentMajor} />

              <CompareModeToggle
                mode={compareMode}
                onChange={handleModeChange}
                disabled={loading}
              />

              {!isMulti && (
                <Select
                  label="Considering"
                  value={prospectiveMajor}
                  onChange={setProspectiveMajor}
                />
              )}
              <NumberField
                ref={completedRef}
                label="Credits completed"
                displayValue={validation.completed.display}
                onChange={setCompletedRaw}
                onBlur={() => setTouched((t) => ({ ...t, completed: true }))}
                hint={
                  auditActive
                    ? "From your confirmed UNT degree audit."
                    : "Courses you've finished and passed."
                }
                error={showCompletedError ? validation.completed.error : null}
                provenance={auditActive ? "document" : null}
              />
              {!isMulti && (
                <NumberField
                  ref={transferableRef}
                  label={
                    auditActive
                      ? `Credits that apply to ${
                          MAJORS.find((m) => m.key === prospectiveMajor)?.label ??
                          "the new major"
                        }`
                      : "Credits that transfer"
                  }
                  displayValue={validation.transferable.display}
                  onChange={setTransferableRaw}
                  onBlur={() => setTouched((t) => ({ ...t, transferable: true }))}
                  hint={
                    transferableUnavailable
                      ? transferableUnavailable.user_message
                      : "Counting toward the new degree, electives included."
                  }
                  error={showTransferableError ? validation.transferable.error : null}
                  provenance={auditActive ? "student" : null}
                />
              )}

              {isMulti && (
                <MultiOptionInputs
                  majors={MAJORS}
                  currentMajor={currentMajor}
                  completedRaw={completedRaw}
                  options={draftOptions}
                  onChange={setDraftOptions}
                  showErrors={multiSubmitAttempted}
                  disabled={loading}
                  inputRefs={optionRefs}
                />
              )}
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
              aria-disabled={
                (isMulti ? !multiValidation.isValid : !validation.isValid) || loading
              }
              title={
                !validation.isValid
                  ? "Fix the highlighted field before calculating"
                  : undefined
              }
              className={`w-full rounded-xl px-4 py-2.5 text-[13.5px] font-semibold text-slate-950 shadow-[0_0_22px_-6px_#22d3ee] transition ${
                (isMulti ? !multiValidation.isValid : !validation.isValid) || loading
                  ? "cursor-not-allowed bg-cyan-500/40 opacity-50"
                  : "cursor-pointer bg-cyan-500/90 hover:bg-cyan-400"
              }`}
            >
              {loading
                ? "Calculating…"
                : isMulti
                  ? `Compare ${draftOptions.length} options`
                  : "Show me the difference"}
            </button>
          </form>

          <AuditPanel
            session={auditSession}
            onSession={setAuditSession}
            onConfirmed={handleAuditConfirmed}
            onReverted={handleAuditReverted}
            onCorrected={() => setAuditSession((s) => s)}
          />

          {error && (
            <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-rose-300">
              {error}
            </p>
          )}

          {displayedResult && (
            <div className="space-y-3 border-t border-white/[0.07] pt-5">
              <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
                How this affects you
              </p>
              <Affect
                label="Time to graduate"
                value={
                  displayedResult.summary.incremental_semesters === 0
                    ? "No change"
                    : `${displayedResult.summary.incremental_semesters > 0 ? "+" : "−"}${Math.abs(displayedResult.summary.incremental_semesters)} semesters`
                }
                bad={displayedResult.summary.incremental_semesters > 0}
              />
              <Affect
                label="Est. additional cost"
                value={money(displayedResult.summary.incremental_total_cost)}
                bad={displayedResult.summary.incremental_total_cost > 0}
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
                value={payDelta(displayedResult.summary.annual_salary_delta)}
                bad={(displayedResult.summary.annual_salary_delta ?? 0) < 0}
              />
            </div>
          )}
        </section>

        {/* ---- Map ---- */}
        <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#060911]">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-3.5">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-[15px] font-semibold text-slate-100">
                  Change Major
                </h2>
                {/* Only in multi mode — a single comparison shouldn't be
                    dressed up as "1 of 1". */}
                {isMulti && activePaths.length > 0 && effectiveDetailPath && (
                  <PathNavigator
                    options={activePaths}
                    selectedMajorKey={effectiveDetailPath}
                    onSelect={setSelectedDetailPath}
                    onFocusPending={handleFocusPending}
                  />
                )}
              </div>
              {/* In multi mode the pairwise "A → B" subtitle is actively
                  misleading — it makes a four-way comparison look like it
                  only contains two majors. Show the alternative currently
                  being inspected instead, with the shared anchor under it. */}
              {isMulti && displayedResult ? (
                <div className="leading-tight">
                  <p className="text-[13px] font-medium text-slate-200">
                    {displayedResult.summary.prospective_major}
                  </p>
                  <p className="text-[11px] text-slate-500">
                    From {displayedResult.summary.current_major}
                  </p>
                </div>
              ) : (
                <p className="text-[12px] text-slate-500">
                  {displayedResult
                    ? `${displayedResult.summary.current_major} → ${displayedResult.summary.prospective_major}`
                    : "Set your situation, then explore what each part costs."}
                </p>
              )}
            </div>
            <Legend />
          </header>

          <div className="aspect-[1000/720] w-full">
            <DecisionMap
              result={displayedResult}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>

          {displayedResult && (
            <div className="grid grid-cols-1 gap-px border-t border-white/[0.07] bg-white/[0.07] sm:grid-cols-2">
              <PathCard
                title={`Finish ${displayedResult.summary.current_major}`}
                items={displayedResult.comparison.staying.line_items}
              />
              <PathCard
                title={`Switch to ${displayedResult.summary.prospective_major}`}
                items={displayedResult.comparison.switching.line_items}
              />
            </div>
          )}

          <div className="border-t border-white/[0.07] p-4">
            <DecisionChat
              result={displayedResult}
              calcInputs={calculatedInputs}
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
              comparisonSessionId={
                isMulti ? multiComparison?.state.session_id ?? null : null
              }
              onComparisonState={(state) =>
                setMultiComparison((prev) =>
                  prev ? { ...prev, state } : prev,
                )
              }
              selectedDetailPath={isMulti ? effectiveDetailPath : null}
              onSelectDetailPath={setSelectedDetailPath}
              onComparisonSnapshot={handleComparisonSnapshot}
              onApplyPairwiseOptionChange={handlePairwiseOptionChange}
              // Remounts the chat when the mode flips, which clears
              // history. The two modes answer from different factual
              // scopes, so carrying pairwise answers into a four-way
              // conversation would leave stale claims on screen.
              key={isMulti ? "multi" : "single"}
            />
          </div>

        </section>

        {/* ---- Detail ---- */}
        <NodePanel
          node={selectedNode}
          result={displayedResult}
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
  /** Where this value came from, shown as a small badge beside the label.
   * Only set once an audit is confirmed -- with everything typed by hand
   * there's nothing to distinguish, and badging every field would be
   * noise. */
  provenance?: "document" | "student" | null;
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
  { label, displayValue, onChange, onBlur, hint, error, provenance }: NumberFieldProps,
  ref: React.ForwardedRef<HTMLInputElement>,
) {
  const errorId = useId();
  return (
    <label className="block">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
          {label}
        </span>
        {provenance === "document" && (
          <span className="rounded-full border border-emerald-400/30 bg-emerald-400/[0.08] px-1.5 py-0.5 text-[9.5px] uppercase tracking-[0.1em] text-emerald-300/90">
            From your audit
          </span>
        )}
        {provenance === "student" && (
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-1.5 py-0.5 text-[9.5px] uppercase tracking-[0.1em] text-slate-400">
            Your estimate
          </span>
        )}
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