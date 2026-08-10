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
  label: string;
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
 * string. Used to detect that the student changed their inputs and re-ran
 * the calculation, so the chat can mark the boundary instead of letting
 * old answers silently appear to describe the new numbers.
 */
export function buildDecisionFingerprint(inputs: DecisionInputs): string {
  return [
    inputs.current_major,
    inputs.prospective_major,
    inputs.credits_completed,
    inputs.credits_transferable,
  ].join("|");
}

/** Human-readable label for the boundary marker, e.g. "Computer Science →
 * Psychology (B.S.)". Falls back to a generic label when display names
 * aren't available. */
export function decisionBoundaryLabel(
  currentMajorLabel?: string,
  prospectiveMajorLabel?: string,
): string {
  if (currentMajorLabel && prospectiveMajorLabel) {
    return `Decision updated · ${currentMajorLabel} → ${prospectiveMajorLabel}`;
  }
  return "Decision updated";
}

/**
 * Appends a boundary marker if the decision changed since the last turn,
 * and returns the new turn list. A boundary is only added when there's
 * actually prior history to separate — a fresh conversation doesn't need
 * one, and two boundaries never stack back to back.
 */
export function withDecisionBoundary(
  turns: Turn[],
  label: string,
): Turn[] {
  if (turns.length === 0) return turns;
  const last = turns[turns.length - 1];
  if (last.kind === "decision_boundary") return turns;
  return [...turns, { kind: "decision_boundary", id: nextTurnId("boundary"), label }];
}