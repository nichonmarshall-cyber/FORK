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

/** One staged edit. Mirrors the backend CorrectionRequest exactly -- there
 * is no separate frontend academic-record model, and corrections are the
 * only way the record changes. */
export interface CorrectionRequest {
  field: string;
  value: string | number | null;
  course_key?: string;
}

export interface CorrectionOutcome {
  applied: boolean;
  field: string;
  course_key: string | null;
  previous_value: string | null;
  new_value: string | null;
  message: string | null;
}

export interface CorrectionResponse extends AuditSession {
  corrections: CorrectionOutcome[];
  applied_count: number;
  rejected: CorrectionOutcome[];
}

/** Where a document's program resolved to, or why it didn't.
 *
 * `ambiguous` covers both "matches nothing" and "matches several". Both mean
 * the document supplies no credits: picking one of two Psychology degrees
 * would attach a B.A.'s applicable hours to a B.S. comparison and label the
 * guess document-derived.
 */
export interface ProgramMatch {
  quality: "exact" | "ambiguous";
  program_key: string | null;
  candidates: string[];
  reason: string | null;
}

export interface DocumentClassification {
  role: "current_audit" | "what_if_audit" | "transcript" | "unsupported";
  program_name: string | null;
  program_code: string | null;
  catalog_year: string | null;
  prepared_at: string | null;
  match: ProgramMatch | null;
}

/** A genuine disagreement between two confirmed documents.
 *
 * Not raised for a gap between completed and applicable hours -- those
 * measure different things, and the difference is ordinary non-transferable
 * credit rather than a contradiction.
 */
export interface Discrepancy {
  code: "document_date_gap" | "shared_fact_contradiction";
  user_message: string;
  technical_detail: string;
  magnitude: string;
}

/** Applicable credits for exactly one comparison option. */
export interface OptionCredits {
  program_key: string;
  credits_transferable: number;
  source: string;
  source_date: string;
}

export interface ResolvedDocuments {
  credits_completed: number | null;
  credits_in_progress: number | null;
  credits_source: string | null;
  credits_source_date: string | null;
  option_credits: OptionCredits | null;
  /** What the student typed before a document took over an option, so
   * reverting restores their figure rather than an empty field. */
  manual_restore: Record<string, number>;
  discrepancies: Discrepancy[];
  /** True while confirmed documents disagree and the student hasn't said how
   * to read them together. Blocks the option figure, not the shared facts. */
  requires_acknowledgement: boolean;
  unresolved: string[];
}

export interface DocumentsState {
  current_audit: { present: boolean; confirmed: boolean };
  what_if: {
    present: boolean;
    confirmed: boolean;
    classification: DocumentClassification | null;
  };
  transcript: { present: boolean; supported: boolean; message: string };
  resolved: ResolvedDocuments;
  /** Identifies exactly the documents an acknowledgement would apply to.
   * Sent back on acknowledge so a stale screen can't grant permission for
   * documents that have since changed. */
  evidence_fingerprint: string | null;
}

export interface AuditSession {
  session_id: string;
  active_mode: "manual" | "confirmed_upload";
  uploaded_source: UploadedSourceState;
  active_source_label: string;
  review?: ReviewSummary;
  change_major_inputs?: ChangeMajorInputsFromAudit;
  documents?: DocumentsState;
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

/** Submit every staged edit at once.
 *
 * Batched because the backend reconciles the totals after the whole set. One
 * request per field would re-check against intermediate states that never
 * existed on screen, and could report a mismatch that resolves itself two
 * fields later.
 *
 * A rejected field does not reject the batch -- valid corrections apply and
 * `rejected` says which didn't and why.
 */
export async function saveCorrections(
  sessionId: string,
  corrections: CorrectionRequest[],
): Promise<CorrectionResponse> {
  return request(`/audit/session/${sessionId}/corrections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corrections }),
  }) as Promise<CorrectionResponse>;
}

/** Reopen a confirmed record for another look. The server stays the source
 * of truth, so this just refetches rather than trusting local state. */
export async function fetchSession(sessionId: string): Promise<AuditSession> {
  return request(`/audit/session/${sessionId}`, { method: "GET" });
}

/** Upload a second document into an existing session.
 *
 * The backend routes on the parser's own is_what_if rather than asking the
 * student to categorise their upload -- UNT's not-finalized banner already
 * says which kind it is.
 */
export async function uploadWhatIf(
  sessionId: string,
  file: File,
): Promise<AuditSession> {
  const form = new FormData();
  form.append("file", file);
  return request(`/audit/unt/upload?session_id=${sessionId}`, {
    method: "POST",
    body: form,
  });
}

/** Confirm one specific document.
 *
 * Per-document because confirmation asks whether Fork read THIS PDF
 * correctly. Whether several confirmed documents can be used together is a
 * different question, answered by acknowledgeDiscrepancies.
 */
export async function confirmDocument(
  sessionId: string,
  document: "current" | "what_if",
): Promise<AuditSession> {
  return request(`/audit/session/${sessionId}/confirm?document=${document}`, {
    method: "POST",
  });
}

/** Accept that confirmed documents disagree, and proceed.
 *
 * The fingerprint is the one that was on screen. If the documents changed
 * since, the backend refuses with 409 rather than granting permission for
 * facts the student never saw.
 */
export async function acknowledgeDiscrepancies(
  sessionId: string,
  evidenceFingerprint: string,
): Promise<AuditSession> {
  return request(`/audit/session/${sessionId}/acknowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ evidence_fingerprint: evidenceFingerprint }),
  });
}

/** Switch back to manual entry, discarding every uploaded document.
 *
 * The discard is the point: leaving a confirmed record in place while manual
 * values drive the calculation is how two sources end up competing. Clears
 * the What-If too -- reverting is a statement about the whole academic
 * source, not just the current audit.
 *
 * Distinct from removing a comparison option, which leaves the What-If
 * stored but dormant. That is a change to what's being compared, not a
 * decision to stop using documents. */
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