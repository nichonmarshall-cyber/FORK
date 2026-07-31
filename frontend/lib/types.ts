/**
 * Mirrors what the backend actually returns. If formatter.py changes shape,
 * this file changes with it — that's the only coupling between frontend and
 * backend, and it's deliberate.
 */

export interface LineItem {
  label: string;
  value: number;
  source: string;
  source_date: string;
}

export interface PathComparison {
  major: string;
  line_items: LineItem[];
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
  why_am_i_seeing_this: {
    assumptions: string[];
    limitations: string[];
  };
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
    const detail = await res.json().catch(() => null);
    throw new Error(
      typeof detail?.detail === "string"
        ? detail.detail
        : `Request failed (${res.status})`,
    );
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
