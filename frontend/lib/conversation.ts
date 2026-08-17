/**
 * The chat's state model, kept separate from the components that render
 * it so the rules can be unit-tested without mounting React.
 *
 * The important rule this file encodes: conversation history is UI
 * history ONLY. A Fork turn stores its structured answer purely so the
 * screen can redraw it — none of it is ever sent back to the model as
 * factual context. Trusted facts come exclusively from the server-side
 * recalculation on each request. See the `question`-only field on
 * `buildDecisionFingerprint`'s sibling request builder in DecisionChat.
 */

import { ExplainResponse } from "./types";

export interface UserTurn {
  kind: "user";
  id: string;
  text: string;
}

export interface ForkTurn {
  kind: "fork";
  id: string;
  answer: ExplainResponse;
}

export interface ErrorTurn {
  kind: "error";
  id: string;
  /** The question that failed, so Retry can resend exactly it. */
  failedQuestion: string;
  /** Overrides the generic failure copy — used for "Ask Fork is
   * temporarily unavailable" (the intent-classification provider itself
   * failed) so it reads differently from a generic explanation failure,
   * which degrades to a deterministic answer instead of erroring at all. */
  message?: string;
}

/**
 * A visible marker that the underlying calculation changed mid-thread.
 * Inserted rather than clearing history, so a student can still see what
 * they asked before — but with an unmistakable line showing that answers
 * above it describe a different set of numbers than answers below it.
 */
export interface DecisionBoundaryTurn {
  kind: "decision_boundary";
  id: string;
  /**
   * Immutable snapshot of the major pair AT THE MOMENT this boundary was
   * created. Stored as data on the turn rather than re-derived at render
   * time from live state — a historical divider has to keep describing
   * the calculation it actually separated, even after the student runs
   * three more comparisons.
   */
  currentMajorLabel: string;
  prospectiveMajorLabel: string;
}

export type Turn = UserTurn | ForkTurn | ErrorTurn | DecisionBoundaryTurn;

let counter = 0;
/** Monotonic ids. Not crypto — these only need to be unique within one
 * mounted conversation for React's key prop. */
export function nextTurnId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

export interface DecisionInputs {
  current_major: string;
  prospective_major: string;
  credits_completed: number;
  credits_transferable: number;
}

/**
 * Identifies "which decision are we talking about" as a single comparable
 * string, derived from a COMPLETED calculation result.
 *
 * Deliberately built from the result rather than from the form's live
 * inputs. Those two sources update at different times: the dropdowns
 * change the instant a student picks a different major, while `result`
 * only changes once they actually click "Show me the difference". Keying
 * the boundary off the inputs meant a divider could be created during
 * that gap and labelled from the still-previous result — which is
 * exactly the stale-label bug this shape prevents. One source for both
 * the trigger and the label makes them incapable of disagreeing.
 */
export function buildDecisionFingerprint(summary: {
  current_major: string;
  prospective_major: string;
  incremental_semesters?: number;
  incremental_total_cost?: number;
  credits_lost?: number;
}): string {
  return [
    summary.current_major,
    summary.prospective_major,
    summary.incremental_semesters ?? "",
    summary.incremental_total_cost ?? "",
    summary.credits_lost ?? "",
  ].join("|");
}

/** Renders a boundary's own stored snapshot. Takes the turn, not live
 * state, so there is no code path that could render a historical divider
 * from the current decision. */
export function decisionBoundaryLabel(turn: DecisionBoundaryTurn): string {
  if (turn.currentMajorLabel && turn.prospectiveMajorLabel) {
    return `Decision updated · ${turn.currentMajorLabel} → ${turn.prospectiveMajorLabel}`;
  }
  return "Decision updated";
}

/**
 * Appends a boundary marker capturing the major pair passed in, and
 * returns the new turn list. A boundary is only added when there's
 * actually prior history to separate — a fresh conversation doesn't need
 * one, and two boundaries never stack back to back.
 *
 * Note there's no "have we seen this pair before" check on purpose:
 * going A -> B, then B -> C, then back to A -> B is three distinct
 * calculations and deserves three dividers. Deduplicating by pair would
 * silently drop the third.
 */
export function withDecisionBoundary(
  turns: Turn[],
  currentMajorLabel: string,
  prospectiveMajorLabel: string,
): Turn[] {
  if (turns.length === 0) return turns;
  const last = turns[turns.length - 1];
  if (last.kind === "decision_boundary") return turns;
  return [
    ...turns,
    {
      kind: "decision_boundary",
      id: nextTurnId("boundary"),
      currentMajorLabel,
      prospectiveMajorLabel,
    },
  ];
}