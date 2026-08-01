/**
 * Mirrors what the backend actually returns. If formatter.py changes shape,
 * this file changes with it — that's the only coupling between frontend and
 * backend, and it's deliberate.
 */

export interface LineItem {
  label: string;
  // null when the underlying figure genuinely isn't available (federal
  // privacy suppression, or no data reported). Render "not available" plus
  // status_note — never 0, and never a blank cell.
  value: number | null;
  source: string;
  source_date: string;
  // Only present when something is off; absent means the value is good.
  status?: "privacy_suppressed" | "unavailable" | "partial";
  status_note?: string | null;
}

export interface EarningsTrajectoryPoint {
  period: "1yr" | "4yr" | "5yr";
  label: string;
  value: number | null;
  status: "available" | "privacy_suppressed" | "unavailable";
  status_note: string | null;
  graduates_measured: number | null;
}

export interface EarningsContext {
  major: string;
  field_of_study: string | null;
  degrees_awarded_in_field: number | null;
  degrees_awarded_label: string;
  // Present when the federal category is broader than the single program
  // (e.g. CS and IT share one category), explaining what the number covers.
  covers: string | null;
  population_note: string | null;
  trajectory: EarningsTrajectoryPoint[];
  source: string;
  source_date: string;
}

export interface PathComparison {
  major: string;
  line_items: LineItem[];
  // Present when the reference data supplies them (real institution data
  // does; older or synthetic reference data may not).
  official_program_name?: string;
  degree_type?: string;
}

export interface CalcResult {
  summary: {
    current_major: string;
    prospective_major: string;
    credits_lost: number;
    incremental_semesters: number;
    incremental_tuition: number;
    incremental_total_cost: number;
    annual_salary_delta: number;
  };
  comparison: {
    staying: PathComparison;
    switching: PathComparison;
  };
  line_items: LineItem[];
  // Display-only career context: the 1/4/5-year earnings trajectory per
  // program. Never feeds a calculation.
  earnings_context: EarningsContext[];
  why_am_i_seeing_this: {
    assumptions: string[];
    limitations: string[];
  };
  // Non-fatal notes about the request itself — e.g. a caller used a
  // renamed major key and the request was still processed under the new
  // one. Absent when there's nothing to flag.
  warnings?: string[];
}

export interface CalcRequest {
  current_major: string;
  prospective_major: string;
  credits_completed: number;
  credits_transferable: number;
  credits_source?: string;
  credits_transferable_source?: string;
  credits_source_date?: string;
  credits_in_progress?: number;
  // Which school to calculate against. Optional because the backend
  // defaults to "unt" when omitted — only send this once there's more
  // than one supported institution to choose from.
  institution_id?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function calculateChangeMajor(
  body: CalcRequest,
): Promise<CalcResult> {
  const res = await fetch(`${API_BASE}/decision-paths/change-major/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    // The backend sends real validation messages. Show them rather than a
    // generic failure — "credits_transferable cannot exceed credits_completed"
    // is more useful than "something went wrong".
    //
    // As of Stage 3, `detail` can also be a structured object rather than
    // a string, for the two major-resolution special cases:
    //   { status: "clarification_required", message, options }
    //   { status: "unsupported_program", message }
    // Both carry a human-readable `message`, so surface that instead of
    // stringifying the whole object.
    const errorBody = await res.json().catch(() => null);
    const detail = errorBody?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail?.message === "string"
          ? detail.message
          : `Request failed (${res.status})`;
    throw new Error(message);
  }

  return res.json();
}

/** Find a line item by a distinctive fragment of its label. */
export function findLineItem(
  result: CalcResult,
  fragment: string,
): LineItem | undefined {
  const all = [
    ...result.line_items,
    ...result.comparison.staying.line_items,
    ...result.comparison.switching.line_items,
  ];
  return all.find((li) =>
    li.label.toLowerCase().includes(fragment.toLowerCase()),
  );
}