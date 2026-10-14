/**
 * Which document, if any, stands behind each figure the compare form sends.
 *
 * A figure carries a document's label only while the field still holds the
 * number that document established. The earlier rule -- "an audit is
 * active, so the completed field is from the audit" -- kept the label after
 * a student typed over the figure, and reported their own number as the
 * audit's. Same for a What-If: the label applies to one program AND one
 * value.
 *
 * Candidates come from two places: the audit confirmed in this visit (the
 * in-memory review session) and the student's saved notebook. Either may
 * back a figure; neither is assumed.
 *
 * Pure functions, so these rules are tested without rendering a page.
 */

import type { Snapshot } from "@/lib/notebook";

export interface SharedSource {
  completed: number;
  credits_source: string;
  credits_source_date: string;
  credits_in_progress: number;
}

export interface OptionSource {
  major: string;
  value: number;
  source: string;
}

export interface SharedProvenanceFields {
  credits_source?: string;
  credits_source_date?: string;
  credits_in_progress?: number;
}

/** Provenance for the shared completed-credits figure, or nothing (the
 * backend's "Student-reported" default) when no document backs this value. */
export function sharedProvenanceFor(
  completed: number | null,
  candidates: (SharedSource | null | undefined)[],
): SharedProvenanceFields {
  if (completed === null) return {};
  const match = candidates.find((c) => c && c.completed === completed);
  if (!match) return {};
  return {
    credits_source: match.credits_source,
    credits_source_date: match.credits_source_date,
    credits_in_progress: match.credits_in_progress,
  };
}

/** The document source for one option's transfer figure, or undefined. */
export function optionSourceFor(
  major: string,
  value: number | null,
  candidates: (OptionSource | null | undefined)[],
): string | undefined {
  if (value === null) return undefined;
  return candidates.find((c) => c && c.major === major && c.value === value)?.source;
}

/** What the saved notebook can back. Only document-confirmed and What-If
 * facts qualify -- a figure the student typed into their notebook is still
 * their own figure here. */
export function recordSources(snapshot: Snapshot | null): {
  shared: SharedSource | null;
  options: OptionSource[];
} {
  if (!snapshot) return { shared: null, options: [] };
  const completed = snapshot.credits_completed;
  const inProgress = snapshot.credits_in_progress;
  const shared =
    completed && completed.provenance === "confirmed_document"
      ? {
          completed: completed.value,
          credits_source: completed.source_label,
          credits_source_date: completed.source_date ?? "Not stated",
          credits_in_progress:
            inProgress && inProgress.provenance === "confirmed_document" ? inProgress.value : 0,
        }
      : null;
  const options = snapshot.applicable_credits
    .filter((f) => f.provenance === "what_if" && f.scope)
    .map((f) => ({ major: f.scope as string, value: f.value, source: f.source_label }));
  return { shared, options };
}
