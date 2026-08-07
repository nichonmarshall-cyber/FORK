"use client";

import { useState } from "react";
import { NODES_BY_ID } from "@/lib/nodes";
import {
  ApiError,
  AvailableNode,
  CalcResult,
  ExplainRequest,
  ExplainResponse,
  explainDecision,
} from "@/lib/types";

const STARTER_PROMPTS = [
  "Explain the biggest difference",
  "Why will graduation take longer?",
  "Break down the additional cost",
  "Compare the career outlook",
  "What does this data not tell me?",
];

// Built once per render from the same node list the map itself uses — not
// a second, hand-maintained copy. Sent with every request so the backend
// can tell the model which node ids are real and filter its response
// against them, per lib/nodes.ts being the one place ids are defined.
function availableNodesList(): AvailableNode[] {
  return Array.from(NODES_BY_ID.values()).map((n) => ({ id: n.id, label: n.label }));
}

interface SelectedNodeInfo {
  id: string;
  label: string;
  question: string;
}

const FAILURE_MESSAGE =
  "Fork could not generate an explanation right now. Your calculation is still available.";

export default function AskFork({
  result,
  calcInputs,
  selectedNode,
  onSelectNode,
}: {
  /** Whether a calculation currently exists. Asking about a decision that
   * hasn't been calculated yet doesn't make sense, so the whole panel
   * stays disabled until this is true — same gating logic as the rest of
   * the workspace. */
  result: CalcResult | null;
  calcInputs: {
    current_major: string;
    prospective_major: string;
    credits_completed: number;
    credits_transferable: number;
  };
  selectedNode: SelectedNodeInfo | null;
  onSelectNode: (id: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<ExplainResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);

  const disabled = result === null;

  async function ask(text: string) {
    const trimmed = text.trim();
    // Guards against both an empty question AND a duplicate submission —
    // `loading` being true blocks a second request from firing while one
    // is already in flight, whether that's a fast second click or the
    // starter buttons (which are also disabled while loading, but this
    // is the real gate; the disabled attribute is the visible signal).
    if (!trimmed || disabled || loading) return;

    setLoading(true);
    setError(null);
    setLastQuestion(trimmed);
    // Deliberately does NOT clear the previous answer while loading, and
    // does NOT touch `result` at all — the calculation and map stay
    // exactly as they are regardless of what happens to this request.
    // Same preserve-on-failure principle as the main calculation form.
    try {
      const req: ExplainRequest = {
        ...calcInputs,
        question: trimmed,
        selected_node_id: selectedNode?.id,
        selected_node_label: selectedNode?.label,
        selected_node_question: selectedNode?.question,
        available_nodes: availableNodesList(),
      };
      const res = await explainDecision(req);
      setAnswer(res);
      setQuestion("");
    } catch (e) {
      // Technical detail goes to the dev console; the UI always shows the
      // same concise, reassuring message regardless of what actually
      // failed (network, provider, validation) — there's no specific
      // field to focus for a free-text question the way the credits form
      // has, so a fixed message is the right call here.
      if (e instanceof ApiError) {
        console.error("Fork: /explain failed:", e.message);
      } else {
        console.error("Fork: /explain failed with an unexpected error:", e);
      }
      setError(FAILURE_MESSAGE);
    } finally {
      setLoading(false);
    }
  }

  function retry() {
    if (lastQuestion) ask(lastQuestion);
  }

  return (
    <section className="space-y-3 rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[12.5px] font-semibold text-slate-200">
          Ask Fork about this decision
        </h2>
        {selectedNode && (
          <span className="text-[11px] text-slate-500">
            Focused on: <span className="text-slate-400">{selectedNode.label}</span>
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STARTER_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            disabled={disabled || loading}
            onClick={() => ask(prompt)}
            className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11.5px] text-slate-400 transition hover:border-cyan-400/40 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {prompt}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="flex gap-2"
      >
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={disabled}
          placeholder={
            disabled
              ? "Calculate a comparison first to ask about it"
              : "Ask Fork about this decision…"
          }
          className="flex-1 rounded-lg border border-white/10 bg-[#0e141f] px-3 py-2 text-[13px] text-slate-200 outline-none placeholder:text-slate-600 focus:border-cyan-400/50 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || loading || !question.trim()}
          className="shrink-0 rounded-lg bg-cyan-500/90 px-3.5 py-2 text-[12.5px] font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "Asking…" : "Ask"}
        </button>
      </form>

      {loading && (
        <p className="flex items-center gap-1.5 text-[11.5px] text-slate-500">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
          Thinking…
        </p>
      )}

      {error && (
        <div
          role="alert"
          className="flex items-center justify-between gap-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-[12px] leading-relaxed text-rose-300"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={retry}
            className="shrink-0 rounded-md border border-rose-400/30 px-2 py-1 text-[11px] font-medium text-rose-200 transition hover:bg-rose-400/10"
          >
            Retry
          </button>
        </div>
      )}

      {answer && <AnswerCard answer={answer} onSelectNode={onSelectNode} />}
    </section>
  );
}

function AnswerCard({
  answer,
  onSelectNode,
}: {
  answer: ExplainResponse;
  onSelectNode: (id: string) => void;
}) {
  const [showLimitations, setShowLimitations] = useState(false);

  return (
    <div className="space-y-3 rounded-lg border border-white/[0.07] bg-white/[0.02] px-3.5 py-3.5">
      {/* Direct answer: visually dominant, everything else quieter. This
          is the one thing rendered unconditionally — every other section
          is optional and only appears when the response actually has
          content for it, per "do not show an empty section". */}
      <p className="text-[13px] font-medium leading-relaxed text-slate-100">
        {answer.direct_answer}
      </p>

      {answer.key_points.length > 0 && (
        <ul className="space-y-2">
          {answer.key_points.map((kp) => (
            <li key={kp.title} className="text-[12.5px] leading-relaxed">
              <span className="font-medium text-slate-300">{kp.title}: </span>
              <span className="text-slate-400">{kp.explanation}</span>
            </li>
          ))}
        </ul>
      )}

      {answer.still_useful_for.length > 0 && (
        <div className="rounded-md border border-emerald-500/20 bg-emerald-500/[0.06] px-3 py-2.5">
          <p className="text-[10.5px] uppercase tracking-[0.12em] text-emerald-400/80">
            Still useful for
          </p>
          <ul className="mt-1.5 space-y-1">
            {answer.still_useful_for.map((item) => (
              <li key={item} className="text-[12px] leading-relaxed text-emerald-200/90">
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.next_step && (
        <div className="rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] px-3 py-2.5">
          <p className="text-[10.5px] uppercase tracking-[0.12em] text-cyan-300/80">
            Next step
          </p>
          <p className="mt-1 text-[12.5px] font-medium text-slate-100">
            {answer.next_step.action}
          </p>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-400">
            {answer.next_step.reason}
          </p>
        </div>
      )}

      {answer.limitations.length > 0 && (
        <div className="border-t border-white/[0.06] pt-3">
          <button
            type="button"
            onClick={() => setShowLimitations((v) => !v)}
            aria-expanded={showLimitations}
            className="flex w-full items-center justify-between text-left"
          >
            <span className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
              Limitations ({answer.limitations.length})
            </span>
            <span className="text-[13px] text-slate-500">{showLimitations ? "−" : "+"}</span>
          </button>
          {showLimitations && (
            <ul className="mt-2 space-y-2">
              {answer.limitations.map((lim) => (
                <li key={lim.title} className="text-[12px] leading-relaxed">
                  <span className="font-medium text-slate-400">{lim.title}: </span>
                  <span className="text-slate-500">{lim.explanation}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* used_fallback: a quiet note, not an error. The deterministic
          template is fully grounded and trustworthy — just plainer than
          a model-generated answer — so this shouldn't read as a
          degraded or failed state. */}
      {answer.used_fallback && (
        <p className="text-[11px] text-slate-600">
          Simplified summary — built directly from the calculation.
        </p>
      )}

      {answer.related_node_ids.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {answer.related_node_ids.map((id) => {
            // Defensive even though the backend already filtered this
            // list against real ids — a node set changing between
            // request and render (unlikely, but not impossible) should
            // never render a broken chip.
            const node = NODES_BY_ID.get(id);
            if (!node) return null;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onSelectNode(id)}
                className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2.5 py-1 text-[11px] text-cyan-300 transition hover:bg-cyan-400/20"
              >
                Related: {node.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}