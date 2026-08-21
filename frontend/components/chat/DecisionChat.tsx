"use client";

import { useEffect, useRef, useState } from "react";
import { NODES_BY_ID } from "@/lib/nodes";
import {
  ApiError,
  AppliedOptionChange,
  AvailableNode,
  CalcResult,
  ComparisonState,
  ExplainRequest,
  ExplainResponse,
  MultiComparisonResponse,
  NavigationTarget,
  askComparison,
  explainDecision,
} from "@/lib/types";
import {
  DecisionInputs,
  Turn,
  buildDecisionFingerprint,
  decisionBoundaryLabel,
  nextTurnId,
  withDecisionBoundary,
} from "@/lib/conversation";
import ChatComposer from "./ChatComposer";
import ForkResponseCard, { ForkAvatar } from "./ForkResponseCard";

const SUGGESTED_QUESTIONS = [
  "Explain the biggest difference",
  "Why will graduation take longer?",
  "Break down the additional cost",
  "Compare the career outlook",
  "What does this data not tell me?",
];

const FAILURE_MESSAGE =
  "Fork could not generate an explanation right now. Your decision results are still available.";

// Distinct from FAILURE_MESSAGE on purpose: this is the intent-classifier
// provider failing outright (Ask Fork never understood the message at
// all), not the explanation step failing after a successfully resolved
// intent (which degrades to a deterministic grounded summary instead of
// erroring -- see ForkResponseCard's used_fallback note).
const UNAVAILABLE_MESSAGE =
  "Ask Fork is temporarily unavailable. Your calculated comparison has not been affected. Please try again in a moment.";

const EMPTY_ANSWER_BASE = {
  key_points: [],
  limitations: [],
  still_useful_for: [],
  next_step: null,
  related_node_ids: [],
  navigation_pills: [],
  navigation_target: null,
  topic_scope: null,
  used_fallback: false,
} satisfies Omit<ExplainResponse, "direct_answer">;

function availableNodesList(): AvailableNode[] {
  return Array.from(NODES_BY_ID.values()).map((n) => ({ id: n.id, label: n.label }));
}

interface SelectedNodeInfo {
  id: string;
  label: string;
  question: string;
}

export default function DecisionChat({
  result,
  calcInputs,
  selectedNode,
  onSelectNode,
  comparisonSessionId,
  onComparisonState,
  selectedDetailPath,
  onSelectDetailPath,
  onComparisonSnapshot,
  onApplyPairwiseOptionChange,
}: {
  result: CalcResult | null;
  /**
   * The inputs that produced `result` -- NOT the live form state. Null
   * until the first successful calculation, which is the same condition
   * that makes `result` null, so the two always agree about whether
   * there's anything to ask about.
   */
  calcInputs: DecisionInputs | null;
  selectedNode: SelectedNodeInfo | null;
  onSelectNode: (id: string) => void;
  /**
   * Set only in Compare Multiple mode. When present, questions go to the
   * session endpoint instead of /explain, so Fork reasons across every
   * active option rather than the one path the map happens to show.
   *
   * Deliberately just the id: which majors are active lives in the
   * backend session, and a second copy here would go stale the moment a
   * student typed "just compare CS and IT".
   */
  comparisonSessionId?: string | null;
  /** Backend state changes on some turns (an option-set instruction, a
   * topic switch, a stated priority), so the page needs it back to update
   * the header. */
  onComparisonState?: (state: ComparisonState) => void;
  /** Multi mode only: which alternative's map is currently displayed --
   * sent as a per-request hint (never persisted server-side) so Ask Fork
   * can resolve "this one" and decide whether an explicit auto-focus
   * should also switch paths. */
  selectedDetailPath?: string | null;
  /** Multi mode only: switches which alternative's map is displayed.
   * Called only from an explicit navigation_target/pill that names a
   * major -- never from a topic change or option change. */
  onSelectDetailPath?: (major: string) => void;
  /** Multi mode only: syncs the canonical comparison snapshot after a
   * chat-driven option change (e.g. a genuinely new option added) so the
   * Decision Map and PathNavigator reflect it immediately, without
   * requiring a manual recalculation. */
  onComparisonSnapshot?: (comparison: MultiComparisonResponse["comparison"]) => void;
  /** Compare One only: applies a chat-resolved "replace" instruction --
   * updates the draft prospective major/credits and, once a transfer
   * figure is known, triggers the same recompute a manual form
   * submission would go through. */
  onApplyPairwiseOptionChange?: (change: AppliedOptionChange) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  // Compare One has no session established until its first chat turn --
  // unlike Multi mode, where the session already exists from
  // /comparison/start. Resets naturally on remount (mode switch), same
  // as everything else in this component.
  const [pairwiseSessionId, setPairwiseSessionId] = useState<string | null>(null);

  // Both must be present: a question needs a result to be about AND the
  // snapshot of inputs that produced it. They're set together, so this is
  // belt-and-braces, but it makes the non-null assertion in ask() honest.
  // In multi-option mode there is no pairwise calcInputs — the backend
  // session holds the trusted inputs instead, so a live session is what
  // makes the chat usable. Requiring calcInputs there would leave the
  // composer permanently disabled.
  const disabled = comparisonSessionId
    ? result === null
    : result === null || calcInputs === null;
  const scrollRef = useRef<HTMLDivElement>(null);
  const fingerprintRef = useRef<string | null>(null);

  // Detect that a NEW calculation completed, and insert a visible
  // boundary rather than clearing history (which would throw away
  // context the student may still want to read).
  //
  // Keyed on `result` only — NOT on calcInputs. The two update at
  // different moments: the form's dropdowns change the instant a student
  // picks a different major, while `result` changes only once they click
  // "Show me the difference". Watching calcInputs meant a boundary could
  // fire during that gap and get labelled from the still-previous
  // result, which is precisely the stale-label bug. Both the trigger and
  // the labels now come from the same object, so they cannot disagree.
  useEffect(() => {
    if (result === null) return;
    const fingerprint = buildDecisionFingerprint(result.summary);
    if (fingerprintRef.current === null) {
      fingerprintRef.current = fingerprint;
      return;
    }
    if (fingerprintRef.current !== fingerprint) {
      fingerprintRef.current = fingerprint;
      setTurns((prev) =>
        withDecisionBoundary(
          prev,
          result.summary.current_major,
          result.summary.prospective_major,
        ),
      );
    }
  }, [result]);

  // Keep the newest turn in view as the conversation grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, busy]);

  /** Applies a backend-computed navigation_target -- purely mechanical,
   * never a judgment call the frontend makes itself. See
   * conversation/orchestrator.py's _compute_navigation for how this is
   * decided server-side. */
  function applyNavigationTarget(target: NavigationTarget | null) {
    if (!target) return;
    onSelectNode(target.node_id);
    if (target.major && onSelectDetailPath) {
      onSelectDetailPath(target.major);
    }
  }

  function pushClarification(message: string) {
    setTurns((prev) => [
      ...prev,
      {
        kind: "fork",
        id: nextTurnId("fork"),
        answer: { direct_answer: message, ...EMPTY_ANSWER_BASE },
      },
    ]);
  }

  function pushUnavailable(question: string) {
    setTurns((prev) => [
      ...prev,
      {
        kind: "error",
        id: nextTurnId("error"),
        failedQuestion: question,
        message: UNAVAILABLE_MESSAGE,
      },
    ]);
  }

  async function ask(text: string) {
    const trimmed = text.trim();
    // `busy` is the real duplicate-submit gate — the disabled attributes
    // on the buttons are the visible signal, this is what actually
    // prevents a second in-flight request.
    if (!trimmed || disabled || busy) return;
    // Only the pairwise path needs calcInputs; the session path sends
    // nothing but the session id.
    if (!comparisonSessionId && calcInputs === null) return;

    setBusy(true);
    setDraft("");
    // The user's message appears immediately, before the request even
    // starts, so the conversation reads as a real exchange rather than a
    // form that eventually produces output.
    setTurns((prev) => [
      ...prev,
      { kind: "user", id: nextTurnId("user"), text: trimmed },
    ]);

    try {
      // Multi-option mode: one call, and the backend already knows which
      // majors are active. Nothing about the currently displayed path is
      // sent as anything but a hint, which is what keeps opening a map
      // from narrowing the conversation.
      if (comparisonSessionId) {
        const response = await askComparison(comparisonSessionId, trimmed, {
          selectedDetailPath,
          availableNodes: availableNodesList(),
        });
        onComparisonState?.(response.state);

        if (response.status === "ai_unavailable") {
          pushUnavailable(trimmed);
          return;
        }
        if (response.status === "clarification_required") {
          pushClarification(response.message);
          return;
        }

        if (response.comparison) onComparisonSnapshot?.(response.comparison);
        applyNavigationTarget(response.navigation_target);
        setTurns((prev) => [
          ...prev,
          {
            kind: "fork",
            id: nextTurnId("fork"),
            answer: {
              ...response.answer,
              navigation_pills: response.navigation_pills,
              navigation_target: response.navigation_target,
              topic_scope: response.topic_scope,
              used_fallback: response.used_fallback,
            },
          },
        ]);
        return;
      }

      // Narrowed by the early return above, but TypeScript loses that
      // across the multi-option branch, so it's restated here.
      if (calcInputs === null) return;
      const req: ExplainRequest = {
        ...calcInputs,
        question: trimmed,
        selected_node_id: selectedNode?.id,
        selected_node_label: selectedNode?.label,
        selected_node_question: selectedNode?.question,
        available_nodes: availableNodesList(),
        session_id: pairwiseSessionId ?? undefined,
        // Deliberately absent: any prior Fork answer. Conversation
        // history is UI state only — the trusted facts for this request
        // come from the server recomputing the calculation from
        // calcInputs, never from text a model produced earlier.
      };
      const response = await explainDecision(req);
      if (response.state.session_id) setPairwiseSessionId(response.state.session_id);

      if (response.status === "ai_unavailable") {
        pushUnavailable(trimmed);
        return;
      }
      if (response.status === "clarification_required") {
        pushClarification(response.message);
        return;
      }
      if (response.status === "option_change_applied") {
        onApplyPairwiseOptionChange?.(response.applied_option_change);
        pushClarification(
          response.applied_option_change.credits_transferable !== null
            ? "Got it — updating your comparison with that now."
            : "Got it — updating what you're comparing against.",
        );
        return;
      }

      applyNavigationTarget(response.navigation_target);
      setTurns((prev) => [
        ...prev,
        { kind: "fork", id: nextTurnId("fork"), answer: response },
      ]);
    } catch (e) {
      if (e instanceof ApiError) {
        console.error("Fork: chat request failed:", e.message);
      } else {
        console.error("Fork: chat request failed with an unexpected error:", e);
      }
      setTurns((prev) => [
        ...prev,
        { kind: "error", id: nextTurnId("error"), failedQuestion: trimmed },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function retry(question: string) {
    // Drop the trailing error turn so a successful retry doesn't leave a
    // stale failure card sitting above the answer.
    setTurns((prev) => {
      const last = prev[prev.length - 1];
      return last?.kind === "error" ? prev.slice(0, -1) : prev;
    });
    ask(question);
  }

  const isEmpty = turns.length === 0;

  return (
    <section className="flex flex-col overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0a0e17]">
      <header className="flex items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <ForkAvatar />
          <div>
            <h2 className="text-[12.5px] font-semibold text-slate-200">Ask Fork</h2>
            <p className="text-[11px] text-slate-500">
              Ask questions about your current decision
            </p>
          </div>
        </div>
        {selectedNode && (
          <span className="shrink-0 rounded-full border border-white/[0.07] px-2 py-0.5 text-[10.5px] text-slate-500">
            Focused on: <span className="text-slate-400">{selectedNode.label}</span>
          </span>
        )}
      </header>

      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label="Conversation with Fork"
        className={`themed-scroll space-y-3 overflow-y-auto px-3.5 ${isEmpty ? "py-3" : "max-h-[420px] py-3.5"}`}
      >
        {isEmpty ? (
          <p className="text-[12.5px] text-slate-500">
            What would you like to understand about this decision?
          </p>
        ) : (
          turns.map((turn) => (
            <TurnView
              key={turn.id}
              turn={turn}
              onSelectNode={onSelectNode}
              onSelectDetailPath={onSelectDetailPath}
              onRetry={retry}
            />
          ))
        )}

        {busy && (
          <div className="flex gap-2.5">
            <ForkAvatar />
            <p className="pt-1 text-[12px] italic text-slate-500">
              Fork is reviewing your decision...
            </p>
          </div>
        )}
      </div>

      <div className={`flex flex-wrap gap-1.5 px-3.5 ${isEmpty ? "pb-3" : "pb-2 pt-1"}`}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={disabled || busy}
            onClick={() => ask(q)}
            className={`rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 transition hover:border-cyan-400/40 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400/60 ${
              isEmpty ? "text-[11.5px] text-slate-400" : "text-[11px] text-slate-500"
            }`}
          >
            {q}
          </button>
        ))}
      </div>

      <ChatComposer
        value={draft}
        onChange={setDraft}
        onSubmit={() => ask(draft)}
        disabled={disabled}
        busy={busy}
      />
    </section>
  );
}

function TurnView({
  turn,
  onSelectNode,
  onSelectDetailPath,
  onRetry,
}: {
  turn: Turn;
  onSelectNode: (id: string) => void;
  onSelectDetailPath?: (major: string) => void;
  onRetry: (question: string) => void;
}) {
  if (turn.kind === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-cyan-500/15 px-3 py-1.5 text-[12.5px] leading-relaxed text-slate-200">
          {turn.text}
        </p>
      </div>
    );
  }

  if (turn.kind === "fork") {
    return (
      <ForkResponseCard
        answer={turn.answer}
        onSelectNode={onSelectNode}
        onSelectDetailPath={onSelectDetailPath}
      />
    );
  }

  if (turn.kind === "error") {
    return (
      <div className="flex gap-2.5">
        <ForkAvatar />
        <div
          role="alert"
          className="flex min-w-0 flex-1 items-center justify-between gap-3 rounded-2xl rounded-tl-sm border border-rose-500/25 bg-rose-500/[0.07] px-3 py-2 text-[12px] leading-relaxed text-rose-300"
        >
          <span>{turn.message ?? FAILURE_MESSAGE}</span>
          <button
            type="button"
            onClick={() => onRetry(turn.failedQuestion)}
            className="shrink-0 rounded-md border border-rose-400/30 px-2 py-0.5 text-[11px] font-medium text-rose-200 transition hover:bg-rose-400/10 focus:outline-none focus-visible:ring-1 focus-visible:ring-rose-300"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className="h-px flex-1 bg-white/[0.08]" />
      <span className="shrink-0 text-[10.5px] uppercase tracking-[0.12em] text-slate-600">
        {decisionBoundaryLabel(turn)}
      </span>
      <span className="h-px flex-1 bg-white/[0.08]" />
    </div>
  );
}
