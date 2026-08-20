/**
 * Degree-audit upload, review, and confirmation.
 *
 * Mirrors what the backend returns from /audit/unt/*, the same way types.ts
 * mirrors the Change Major endpoints. Error handling reuses parseApiError
 * from types.ts rather than growing a second message-building path — there
 * should be exactly one place that decides what a person reads when a
 * request fails.
 *
 * The shape worth understanding before reading the rest: `active_mode` and
 * `uploaded_source` are separate on purpose. A parsed record awaiting review
 * exists WHILE manual entry is still driving the calculation, and that state
 * is invisible to any client that derives one from the other. It is also the
 * entire review step.
 */

import { ApiError, parseApiError } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface ReviewCourse {
  key: string;
  course_code: string;
  title: string | null;
  hours: number;
  grade: string | null;
  term: string | null;
  status: string;
  status_label: string;
  note: string | null;
  source_label: string;
}

/** One figure for the student to eyeball. `kind` is supplied so the UI can
 * treat an hour count differently from a program name without inspecting
 * the string. */
export interface Checkpoint {
  key: string;
  label: string;
  value: string;
  kind: string;
  unit: string | null;
}

export interface ReviewSummary {
  program: string | null;
  catalog_year: string | null;
  prepared_at: string | null;
  is_what_if: boolean;
  completed_hours: number;
  in_progress_hours: number;
  course_count: number;
  headline: string;
  checkpoints: Checkpoint[];
  notices: string[];
  /** False when the hours Fork added up don't match the totals printed on
   * the audit. Not an error — a reason to look more carefully. */
  totals_confirmed: boolean;
  courses: ReviewCourse[];
  excluded_courses: ReviewCourse[];
}

export interface UploadedSourceState {
  present: boolean;
  confirmation_status: string | null;
  is_active: boolean;
  awaiting_review: boolean;
}

/** An engine input the confirmed record deliberately does not supply. */
export interface UnavailableInput {
  field: string;
  reason_code: string;
  technical_detail: string;
  user_message: string;
}

/** Present only once the record is confirmed. Partial by design: the fields
 * it omits are ones a degree audit doesn't establish. */
export interface ChangeMajorInputsFromAudit {
  credits_completed: number;
  credits_in_progress: number;
  credits_source: string;
  credits_source_date: string;
  catalog_year: string | null;
  program: string | null;
  totals_confirmed: boolean;
  unavailable: UnavailableInput[];
}

export interface AuditSession {
  session_id: string;
  active_mode: "manual" | "confirmed_upload";
  uploaded_source: UploadedSourceState;
  active_source_label: string;
  review?: ReviewSummary;
  change_major_inputs?: ChangeMajorInputsFromAudit;
}

async function request(path: string, init: RequestInit): Promise<AuditSession> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (networkError) {
    const parsed = parseApiError({ networkError });
    throw new ApiError(parsed.message, parsed.field);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const parsed = parseApiError({ status: res.status, body });
    throw new ApiError(parsed.message, parsed.field);
  }

  return res.json();
}

/** Upload a PDF. Opens a session holding the parsed record — it is NOT
 * active yet, and the session stays in manual mode until confirmed. */
export async function uploadAudit(file: File): Promise<AuditSession> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type header on purpose: the browser has to set it itself so
  // the multipart boundary is included.
  return request("/audit/unt/upload", { method: "POST", body: form });
}

/** Accept the extracted record as the session's academic source.
 *
 * Confirmation means the student agrees Fork read the document correctly.
 * It is not verification — nothing has been checked with UNT. */
export async function confirmAudit(sessionId: string): Promise<AuditSession> {
  return request(`/audit/session/${sessionId}/confirm`, { method: "POST" });
}

/** Switch back to manual entry, discarding the uploaded record.
 *
 * The discard is the point: leaving a confirmed record in place while manual
 * values drive the calculation is how two sources end up competing. */
export async function revertToManual(sessionId: string): Promise<AuditSession> {
  return request(`/audit/session/${sessionId}/mode?mode=manual`, {
    method: "POST",
  });
}

/** Cheap client-side check so an obviously wrong file never leaves the
 * browser. The backend validates independently — this is about a faster,
 * more specific message, not about trust. */
export function looksLikePdf(file: File): boolean {
  return (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  );
}