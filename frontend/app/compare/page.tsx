"use client";

import Link from "next/link";
import { forwardRef, useEffect, useId, useMemo, useRef, useState } from "react";
import AuditPanel from "@/components/AuditPanel";
import WhatIfPanel from "@/components/WhatIfPanel";
import DecisionMap from "@/components/DecisionMap";
import DecisionChat from "@/components/chat/DecisionChat";
import PathNavigator from "@/components/PathNavigator";
import CompareModeToggle, { CompareMode } from "@/components/form/CompareModeToggle";
import MultiOptionInputs, {
  DraftOption,
  validateAllOptions,
} from "@/components/form/MultiOptionInputs";
import NodePanel from "@/components/NodePanel";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/notebook/TopBar";
import RecordSaveBar from "@/components/notebook/RecordSaveBar";
import { NODES_BY_ID, payDelta } from "@/lib/nodes";
import { MAJORS } from "@/lib/majors";
import {
  ApiError,
  AppliedOptionChange,
  CalcRequest,
  CalcResult,
  MultiComparisonResponse,
  StartComparisonRequest,
  calculateChangeMajor,
  startComparison,
} from "@/lib/types";
import { validateCreditsPair } from "@/lib/validation";
import { AuditSession } from "@/lib/audit";
import {
  Notebook,
  SaveScenarioInput,
  Snapshot,
  Student,
  getMe,
  getNotebook,
  hasSignInHint,
  logout,
  saveScenario,
} from "@/lib/notebook";
import {
  OptionSource,
  SharedSource,
  optionSourceFor,
  recordSources,
  sharedProvenanceFor,
} from "@/lib/compareProvenance";

const money = (n: number) =>
  `${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", {
    maximumFractionDigits: 0,
  })}`;

type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; title: string; forResult: unknown }
  | { kind: "error"; message: string };

export default function ComparePage() {
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
  // The exact request that produced `result` -- provenance and in-progress
  // hours included. Distinct from the draft form state above: those change
  // the instant a dropdown moves, while this only advances when a
  // calculation actually succeeds. Ask Fork reads THIS and its /explain
  // recomputes from it, so it must carry everything the original
  // calculation did; a copy holding only the four numbers grounded the
  // explanation on a "Student-reported", zero-in-progress recomputation
  // that differed from the map on screen.
  const [calculatedInputs, setCalculatedInputs] = useState<CalcRequest | null>(null);
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

  // --- Notebook ------------------------------------------------------
  //
  // Optional. A visitor who never signs in uses this page exactly as
  // before; nothing below makes a request unless the browser carries the
  // signed-in hint cookie.
  const [student, setStudent] = useState<Student | null>(null);
  const [recordSnapshot, setRecordSnapshot] = useState<Snapshot | null>(null);
  const [recordBanner, setRecordBanner] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>({ kind: "idle" });

  const auditInputs = auditSession?.change_major_inputs ?? null;
  const auditActive = auditSession?.uploaded_source.is_active ?? false;
  // The one figure a degree audit doesn't establish. The backend says so
  // explicitly rather than the frontend inferring it from an absent field,
  // and it ships the sentence to show -- so when a matcher exists and the
  // entry disappears, this field stops explaining itself automatically.
  // A confirmed What-If for THIS option's major. Attachment is a property of
  // the document, not of what's currently selected -- switching options must
  // not detach it or restore that option's manual value.
  const documents = auditSession?.documents ?? null;
  const optionCredits = documents?.resolved.option_credits ?? null;

  const labelForMajor = (key: string) =>
    MAJORS.find((m) => m.key === key)?.label ?? key;

  const transferableUnavailable =
    auditInputs?.unavailable.find((u) => u.field === "credits_transferable") ?? null;

  // Every document that could stand behind a figure, from this visit's
  // audit review and from the saved notebook. A figure carries a document's
  // label only while it still equals what that document says -- see
  // lib/compareProvenance.ts.
  const record = useMemo(() => recordSources(recordSnapshot), [recordSnapshot]);
  const sharedCandidates: (SharedSource | null)[] = [
    auditActive && auditInputs
      ? {
          completed: auditInputs.credits_completed,
          credits_source: auditInputs.credits_source,
          credits_source_date: auditInputs.credits_source_date,
          credits_in_progress: auditInputs.credits_in_progress,
        }
      : null,
    record.shared,
  ];
  const optionCandidates: (OptionSource | null)[] = [
    optionCredits
      ? {
          major: optionCredits.program_key,
          value: optionCredits.credits_transferable,
          source: optionCredits.source,
        }
      : null,
    ...record.options,
  ];

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

  // Applied by an explicit user action rather than an effect watching the
  // session. An effect would rewrite the field on every payload -- including
  // ones the student triggered for another reason -- and silently overwrite
  // an edit they had just made.
  function applyWhatIfToForm(next: AuditSession) {
    const credits = next.documents?.resolved.option_credits;
    if (!credits || credits.program_key !== prospectiveMajor) return;

    setManualBackup((backup) =>
      // Only the FIRST time a document takes over, so a second What-If
      // doesn't overwrite the student's own figure with a document-derived
      // one and call it manual.
      backup ?? { completed: completedRaw, transferable: transferableRaw },
    );
    setTransferableRaw(String(credits.credits_transferable));
  }

  function handleWhatIfSession(next: AuditSession | null) {
    setAuditSession(next);
    if (next) applyWhatIfToForm(next);
  }

  /** Switching the prospective major re-resolves which document applies.
   *
   * Applying only at confirm time made this one-shot: a student who
   * confirmed a Psychology What-If while considering IT, then switched to
   * Psychology, kept their manual estimate forever, because nothing ran
   * again. The document was attached and correct -- it just never reached
   * the form.
   *
   * Attachment itself is unaffected. A document stays bound to its own
   * program; this only decides which value the field shows.
   */
  function handleProspectiveMajorChange(next: string) {
    setProspectiveMajor(next);

    const credits = auditSession?.documents?.resolved.option_credits ?? null;
    if (credits && credits.program_key === next) {
      setManualBackup(
        (backup) => backup ?? { completed: completedRaw, transferable: transferableRaw },
      );
      setTransferableRaw(String(credits.credits_transferable));
      return;
    }

    // A What-If saved in the notebook covers this option: offer its figure
    // the same way, keeping the student's own number to come back to.
    const fromRecord = record.options.find((o) => o.major === next);
    if (fromRecord) {
      setManualBackup(
        (backup) => backup ?? { completed: completedRaw, transferable: transferableRaw },
      );
      setTransferableRaw(String(fromRecord.value));
      return;
    }

    // Moving to an option no document covers: give the student their own
    // figure back rather than leaving another program's number in the field.
    if (manualBackup) setTransferableRaw(manualBackup.transferable);
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
  // The request behind multiComparison, kept so saving to the notebook
  // sends the figures (and their sources) that were actually compared.
  const [multiRequest, setMultiRequest] = useState<StartComparisonRequest | null>(null);
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

  // Which figures on the form a document currently stands behind.
  const sharedFields = sharedProvenanceFor(validation.completed.value, sharedCandidates);
  const completedFromDocument = sharedFields.credits_source !== undefined;
  const completedFromSession =
    sharedCandidates[0] !== null && validation.completed.value === sharedCandidates[0].completed;
  const transferSource = optionSourceFor(
    prospectiveMajor,
    validation.transferable.value,
    optionCandidates,
  );
  const transferFromSessionWhatIf =
    transferSource !== undefined && optionCredits !== null && transferSource === optionCredits.source;
  const anyDocument = auditActive || record.shared !== null || record.options.length > 0;

  /** The request for one pairwise comparison, with the provenance each
   * figure has earned. When no document backs a figure its source is
   * omitted and the backend's "Student-reported" default applies, exactly
   * as before.
   *
   * credits_source and credits_transferable_source come from different
   * documents on purpose. The current audit establishes completed hours; a
   * What-If establishes what applies to ONE program. Sending only the first
   * is what once made a document-derived transfer figure show up as
   * "Student-reported". */
  function pairwiseRequest(
    current: string,
    prospective: string,
    completed: number,
    transferable: number,
  ): CalcRequest {
    const source = optionSourceFor(prospective, transferable, optionCandidates);
    return {
      current_major: current,
      prospective_major: prospective,
      credits_completed: completed,
      credits_transferable: transferable,
      ...sharedProvenanceFor(completed, sharedCandidates),
      ...(source ? { credits_transferable_source: source } : {}),
    };
  }

  async function runPairwise(request: CalcRequest) {
    setLoading(true);
    setError(null);
    try {
      const data = await calculateChangeMajor(request);
      setResult(data);
      setCalculatedInputs(request);
      setSelectedId("root");
      setSubmitAttempted(false);
      return true;
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
      return false;
    } finally {
      setLoading(false);
    }
  }

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

    await runPairwise(
      pairwiseRequest(
        currentMajor,
        prospectiveMajor,
        validation.completed.value as number,
        validation.transferable.value as number,
      ),
    );
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
      setMultiRequest(null);
      setSelectedDetailPath(null);
      setDraftOptions([]);
    }
  }

  /** The multi-option request, each option's transfer figure carrying the
   * source of the document that backs it -- if one does, for that program,
   * at that value. Previously no source was sent here at all, so a
   * confirmed audit's completed hours were labelled "Student-reported" in
   * every multi-option comparison. */
  function multiRequestFor(
    current: string,
    completed: number,
    options: { major: string; credits_transferable: number | null }[],
  ): StartComparisonRequest {
    return {
      current_major: current,
      credits_completed: completed,
      ...sharedProvenanceFor(completed, sharedCandidates),
      options: options.map((o) => {
        const source = optionSourceFor(o.major, o.credits_transferable, optionCandidates);
        return {
          major: o.major,
          ...(o.credits_transferable !== null ? { credits_transferable: o.credits_transferable } : {}),
          ...(source ? { credits_transferable_source: source } : {}),
        };
      }),
    };
  }

  async function runMulti(request: StartComparisonRequest) {
    setLoading(true);
    setError(null);
    try {
      const response = await startComparison(request);
      setMultiComparison(response);
      setMultiRequest(request);
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

    await runMulti(
      multiRequestFor(
        currentMajor,
        validation.completed.value as number,
        draftOptions.map((o) => ({
          major: o.major,
          credits_transferable: Number(o.transferableRaw),
        })),
      ),
    );
  }

  /** Applies a chat-resolved Compare One "replace" (see
   * conversation.orchestrator.handle_pairwise_turn). When a transfer
   * figure came with it, this recomputes immediately through the exact
   * same calculate/explain trust path a manual form submission already
   * uses -- chat never gets a shortcut around validation. When no figure
   * was given yet, only the draft major updates and the transfer field is
   * cleared/invalidated so the OLD major's figure can never be reused for
   * the new one; Ask Fork's own reply already asked for the real number.
   *
   * Carries the same provenance a form submission would. It used to send
   * the bare figures, so a chat-driven recalculation silently relabelled a
   * confirmed audit's hours as "Student-reported" and dropped in-progress
   * hours from the calculation. */
  async function handlePairwiseOptionChange(change: AppliedOptionChange) {
    setProspectiveMajor(change.major);
    if (change.credits_transferable === null) {
      setTransferableRaw("");
      return;
    }
    setTransferableRaw(String(change.credits_transferable));
    await runPairwise(
      pairwiseRequest(
        currentMajor,
        change.major,
        validation.completed.value as number,
        change.credits_transferable,
      ),
    );
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

  // --- Notebook: identity, prefill, save -----------------------------

  /** Fill the form from the notebook. Values only; the provenance each one
   * earns is worked out at submit time from the same snapshot, so a value
   * the student then edits stops claiming the document. */
  function prefillFromRecord(notebook: Notebook) {
    const snap = notebook.snapshot;
    const filled: string[] = [];
    let current = currentMajor;
    if (snap.current_major) {
      current = snap.current_major.value;
      setCurrentMajor(current);
      filled.push("your major");
    }
    if (snap.credits_completed) {
      setCompletedRaw(String(snap.credits_completed.value));
      filled.push("completed credits");
    }
    let prospective = prospectiveMajor;
    if (prospective === current) {
      prospective = MAJORS.find((m) => m.key !== current)?.key ?? prospective;
      setProspectiveMajor(prospective);
    }
    const applicable = snap.applicable_credits.find((f) => f.scope === prospective);
    if (applicable) {
      setTransferableRaw(String(applicable.value));
      filled.push(`credits that apply to ${labelForMajor(prospective)}`);
    }
    setRecordBanner(
      filled.length
        ? `Filled in ${filled.join(", ")} from your notebook. Change anything and it becomes your own figure.`
        : "Your notebook doesn't have academic figures yet — enter them below.",
    );
  }

  /** Reopen a saved comparison on the map. Recalculated now, from the
   * saved inputs, with provenance re-checked against the current record --
   * the same rules a fresh comparison follows. */
  function openScenario(notebook: Notebook, scenarioId: string) {
    const scenario = notebook.scenarios.find((s) => s.id === scenarioId);
    if (!scenario) {
      setRecordBanner("That comparison isn't in your notebook.");
      return;
    }
    const inputs = scenario.inputs;
    const completed = inputs.credits_completed.value;
    // Sources from the snapshot directly: state set during this function
    // isn't visible to the request builders until the next render.
    const rec = recordSources(notebook.snapshot);
    const shared = sharedProvenanceFor(completed, [rec.shared]);
    setCurrentMajor(inputs.current_major);
    setCompletedRaw(String(completed));
    setRecordBanner(
      `Showing “${scenario.title}” from your notebook, recalculated with Fork's current data.`,
    );

    if (inputs.options.length === 1 && inputs.options[0].credits_transferable !== null) {
      const option = inputs.options[0];
      const value = option.credits_transferable as number;
      setCompareMode("one");
      setProspectiveMajor(option.major);
      setTransferableRaw(String(value));
      const source = optionSourceFor(option.major, value, rec.options);
      void runPairwise({
        current_major: inputs.current_major,
        prospective_major: option.major,
        credits_completed: completed,
        credits_transferable: value,
        ...shared,
        ...(source ? { credits_transferable_source: source } : {}),
      });
      return;
    }

    setCompareMode("multiple");
    setDraftOptions(
      inputs.options.map((o) => ({
        major: o.major,
        transferableRaw: o.credits_transferable === null ? "" : String(o.credits_transferable),
      })),
    );
    void runMulti({
      current_major: inputs.current_major,
      credits_completed: completed,
      ...shared,
      options: inputs.options.map((o) => {
        const source = optionSourceFor(o.major, o.credits_transferable, rec.options);
        return {
          major: o.major,
          ...(o.credits_transferable !== null ? { credits_transferable: o.credits_transferable } : {}),
          ...(source ? { credits_transferable_source: source } : {}),
        };
      }),
    });
  }

  // On arrival only: who's signed in, and whether the link asked for the
  // notebook's figures, a saved comparison, or the audit panel. Every state
  // update happens after a request resolves, never synchronously here.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("panel") === "audit") {
      document.getElementById("audit-panel")?.scrollIntoView({ block: "start" });
    }
    if (!hasSignInHint()) return;
    let cancelled = false;
    getMe()
      .then(async (me) => {
        if (cancelled || !me) return;
        setStudent(me);
        const notebook = await getNotebook();
        if (cancelled) return;
        setRecordSnapshot(notebook.snapshot);
        const scenarioId = params.get("scenario");
        if (scenarioId) openScenario(notebook, scenarioId);
        else if (params.get("from") === "record") prefillFromRecord(notebook);
      })
      .catch(() => {
        // The notebook is an extra here, never a requirement: if it can't
        // be reached the page works exactly as it does signed out.
      });
    return () => {
      cancelled = true;
    };
    // Arrival-time only by design; see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshRecord() {
    try {
      setRecordSnapshot((await getNotebook()).snapshot);
    } catch {
      // Leave the last snapshot in place; provenance stays conservative.
    }
  }

  async function handleSignOut() {
    try {
      await logout();
    } finally {
      setStudent(null);
      setRecordSnapshot(null);
    }
  }

  /** Save what's on the map to the notebook. Sends the inputs of the
   * calculation that produced it -- never the result; the backend
   * recalculates and checks every source label against the record. */
  async function handleSaveToNotebook() {
    let input: SaveScenarioInput | null = null;
    if (!isMulti && calculatedInputs) {
      input = {
        current_major: calculatedInputs.current_major,
        credits_completed: calculatedInputs.credits_completed,
        credits_in_progress: calculatedInputs.credits_in_progress ?? 0,
        credits_source: calculatedInputs.credits_source ?? "Student-reported",
        options: [
          {
            major: calculatedInputs.prospective_major,
            credits_transferable: calculatedInputs.credits_transferable,
            credits_transferable_source:
              calculatedInputs.credits_transferable_source ?? "Student-reported",
          },
        ],
      };
    } else if (isMulti && multiRequest && multiComparison) {
      // The options active NOW, which a chat instruction may have changed
      // since the form was submitted. Figures come from the submitted
      // request where it has them, otherwise from the calculation itself.
      const submitted = new Map(multiRequest.options.map((o) => [o.major, o]));
      input = {
        current_major: multiRequest.current_major,
        credits_completed: multiRequest.credits_completed,
        credits_in_progress: multiRequest.credits_in_progress ?? 0,
        credits_source: multiRequest.credits_source ?? "Student-reported",
        options: activePaths.map((o) => {
          const sent = submitted.get(o.major_key);
          const fromCalc = o.dimensions?.credits?.credits_transferable?.value ?? null;
          return {
            major: o.major_key,
            credits_transferable: sent?.credits_transferable ?? fromCalc,
            credits_transferable_source:
              sent?.credits_transferable_source ?? "Student-reported",
          };
        }),
      };
    }
    if (!input) return;
    input.audit_session_id = auditSession?.session_id ?? null;

    setSaveStatus({ kind: "saving" });
    try {
      const { scenario } = await saveScenario(input);
      setSaveStatus({
        kind: "saved",
        title: scenario.title,
        forResult: isMulti ? multiComparison : result,
      });
    } catch (e) {
      setSaveStatus({
        kind: "error",
        message: e instanceof ApiError ? e.message : "Couldn't save to your notebook.",
      });
    }
  }

  const savedForCurrent =
    saveStatus.kind === "saved" &&
    saveStatus.forResult === (isMulti ? multiComparison : result);

  return (
    <div className="min-h-screen w-full bg-[#05070d] text-slate-200">
      <TopBar student={student} current="compare" onSignOut={handleSignOut} />
      <div className="mx-auto grid max-w-[1840px] grid-cols-1 gap-4 p-4 xl:grid-cols-[172px_250px_minmax(0,1fr)_300px]">
        <div className="hidden xl:block">
          <Sidebar result={displayedResult} signedIn={student !== null} />
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

          {recordBanner && (
            <p role="status" className="rounded-xl border border-cyan-400/20 bg-cyan-400/[0.05] px-3 py-2 text-[12px] leading-relaxed text-cyan-100/90">
              {recordBanner}
            </p>
          )}

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
                  onChange={handleProspectiveMajorChange}
                />
              )}
              <NumberField
                ref={completedRef}
                label="Credits completed"
                displayValue={validation.completed.display}
                onChange={setCompletedRaw}
                onBlur={() => setTouched((t) => ({ ...t, completed: true }))}
                hint={
                  completedFromSession
                    ? "From your confirmed UNT degree audit."
                    : completedFromDocument
                      ? "From the degree audit in your notebook."
                      : "Courses you've finished and passed."
                }
                error={showCompletedError ? validation.completed.error : null}
                provenance={completedFromDocument ? "document" : anyDocument ? "student" : null}
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
                    transferFromSessionWhatIf
                      ? `From your confirmed What-If audit for ${labelForMajor(
                          prospectiveMajor,
                        )}.`
                      : transferSource
                        ? `From the What-If audit in your notebook for ${labelForMajor(
                            prospectiveMajor,
                          )}.`
                        : transferableUnavailable
                          ? transferableUnavailable.user_message
                          : "Counting toward the new degree, electives included."
                  }
                  error={showTransferableError ? validation.transferable.error : null}
                  // A document figure and a typed estimate must not look the
                  // same. Once a What-If supplies this option -- at this
                  // value -- the badge says so; otherwise it stays the
                  // student's own number.
                  provenance={transferSource ? "document" : anyDocument ? "student" : null}
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

          {auditSession && documents && (
            <WhatIfPanel
              session={auditSession}
              documents={documents}
              onSession={handleWhatIfSession}
              optionLabel={labelForMajor}
              selectedProgramKey={prospectiveMajor}
            />
          )}

          <div id="audit-panel" className="scroll-mt-4 space-y-3">
            <AuditPanel
              session={auditSession}
              onSession={setAuditSession}
              onConfirmed={handleAuditConfirmed}
              onReverted={handleAuditReverted}
              onCorrected={() => setAuditSession((s) => s)}
            />
            {student && !student.is_demo && auditSession && (
              <RecordSaveBar session={auditSession} onSaved={refreshRecord} />
            )}
          </div>

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

              {student?.is_demo ? (
                <p className="text-[11.5px] text-slate-500">
                  This is the read-only demo, so comparisons can&rsquo;t be saved.{" "}
                  <Link href="/" className="text-cyan-300 hover:underline">
                    Back to the demo notebook
                  </Link>
                </p>
              ) : student ? (
                <div className="pt-1">
                  {savedForCurrent && saveStatus.kind === "saved" ? (
                    <p role="status" className="text-[12px] text-emerald-300">
                      Saved to your notebook as “{saveStatus.title}”.{" "}
                      <Link href="/#comparisons" className="text-cyan-300 hover:underline">
                        Open notebook
                      </Link>
                    </p>
                  ) : (
                    <button
                      type="button"
                      onClick={handleSaveToNotebook}
                      disabled={saveStatus.kind === "saving" || loading}
                      className="w-full rounded-xl border border-cyan-400/30 px-4 py-2 text-[12.5px] font-medium text-cyan-200 hover:bg-cyan-400/10 disabled:opacity-60"
                    >
                      {saveStatus.kind === "saving"
                        ? "Saving…"
                        : isMulti
                          ? "Save this comparison to my notebook"
                          : "Save to my notebook"}
                    </button>
                  )}
                  {saveStatus.kind === "error" && (
                    <p role="alert" className="mt-2 text-[12px] text-rose-300">
                      {saveStatus.message}
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-[11.5px] text-slate-500">
                  <Link href="/" className="text-cyan-300 hover:underline">
                    Sign in
                  </Link>{" "}
                  to keep comparisons in a notebook.
                </p>
              )}
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

          <div id="ask-fork" className="border-t border-white/[0.07] p-4">
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
   * Only set once a document is in play -- with everything typed by hand
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
