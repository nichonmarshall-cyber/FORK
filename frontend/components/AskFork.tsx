"use client";

import { useState } from "react";
import { NODES_BY_ID } from "@/lib/nodes";
import { ApiError, CalcResult, ExplainRequest, explainDecision } from "@/lib/types";

const STARTER_PROMPTS = [
  "Explain the biggest difference",
  "Why will graduation take longer?",
  "Break down the additional cost",
  "Compare the career outlook",
  "What does this data not tell me?",
];

interface SelectedNodeInfo {
  id: string;
  label: string;
  question: string;
}

interface Answer {
  text: string;
  usedFallback: boolean;
  /** Node ids whose label appears verbatim in the answer text — offered
   * as "open this node" chips. Matched against real node labels only, so
   * this can never point at something that doesn't exist on the map. */
  referencedNodeIds: string[];
}

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
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const disabled = result === null;

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || disabled || loading) return;

    setLoading(true);
    setError(null);
    // Deliberately does NOT clear the previous answer while loading, and
    // does NOT touch `result` at all — the calculation on screen stays
    // exactly as it is regardless of what happens to this request. Same
    // preserve-on-failure principle as the main calculation form.
    try {
      const req: ExplainRequest = {
        ...calcInputs,
        question: trimmed,
        selected_node_id: selectedNode?.id,
        selected_node_label: selectedNode?.label,
        selected_node_question: selectedNode?.question,
      };
      const res = await explainDecision(req);
      setAnswer({
        text: res.answer,
        usedFallback: res.used_fallback,
        referencedNodeIds: findReferencedNodeIds(res.answer),
      });
      setQuestion("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
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

      {error && (
        <p role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12px] leading-relaxed text-rose-300">
          {error}
        </p>
      )}

      {answer && (
        <div className="space-y-2 rounded-lg border border-white/[0.07] bg-white/[0.02] px-3.5 py-3">
          <p className="text-[12.5px] leading-relaxed text-slate-300">{answer.text}</p>

          {/* used_fallback means the deterministic template answered
              instead of the model — still fully grounded, just plainer.
              Shown as a quiet note rather than an error, since it's not
              one: the requirement is showing when data is limited, and a
              fallback answer IS a form of limited (if reliable) response. */}
          {answer.usedFallback && (
            <p className="text-[11px] text-slate-500">
              Simplified summary — built directly from the calculation.
            </p>
          )}

          {answer.referencedNodeIds.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {answer.referencedNodeIds.map((id) => {
                const node = NODES_BY_ID.get(id);
                if (!node) return null;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onSelectNode(id)}
                    className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2.5 py-1 text-[11px] text-cyan-300 transition hover:bg-cyan-400/20"
                  >
                    Open {node.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** Matches real node labels appearing verbatim in the answer text. Never
 * trusts the model to name a node id directly — only ever offers
 * navigation to a node that genuinely exists and is genuinely named in
 * the text, so this can't be used to reference something fabricated. */
function findReferencedNodeIds(text: string): string[] {
  const found: string[] = [];
  for (const [id, node] of NODES_BY_ID) {
    if (node.label.length > 3 && text.includes(node.label)) {
      found.push(id);
    }
  }
  return found;
}