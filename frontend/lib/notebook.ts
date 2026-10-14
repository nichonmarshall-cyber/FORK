/**
 * Client for /account and /notebook.
 *
 * Every call goes through the frontend's own origin (/api/fork, proxied to
 * the backend by next.config.ts) so the session cookie is first-party, and
 * every state-changing call carries the X-Fork-CSRF header the backend
 * requires.
 *
 * Types mirror backend/notebook/*.py. Provenance is a closed set of four
 * values; nothing here invents a fifth.
 */

import { ApiError } from "@/lib/types";

export const NOTEBOOK_API = "/api/fork";

export type Provenance =
  | "confirmed_document"
  | "student_reported"
  | "derived"
  | "what_if";

export interface Student {
  id: string;
  email: string;
  display_name: string | null;
  institution_id: string;
  created_at: string | null;
}

export interface Fact<T = unknown> {
  key: string;
  scope: string | null;
  value: T;
  provenance: Provenance;
  provenance_label: string;
  source_label: string;
  source_date: string | null;
  document_id: string | null;
  updated_at: string | null;
  display?: string | null;
}

export interface DerivedFact {
  key: string;
  value: number;
  provenance: "derived";
  provenance_label: string;
  source_label: string;
  source_date: string | null;
  inputs_provenance: Provenance[];
}

export interface RequirementCounts {
  complete: number;
  in_progress: number;
  unfulfilled: number;
  unknown: number;
  total: number;
}

export interface DegreeHours {
  earned: number | null;
  needed: number | null;
  in_progress: number | null;
}

export interface Snapshot {
  institution: { id: string; name: string };
  current_major: Fact<string> | null;
  program: Fact<string> | null;
  catalog_year: Fact<string> | null;
  gpa: Fact<number> | null;
  credits_completed: Fact<number> | null;
  credits_in_progress: Fact<number> | null;
  applicable_credits: Fact<number>[];
  requirements: Fact<RequirementCounts> | null;
  degree_hours: Fact<DegreeHours> | null;
  credits_remaining_current: DerivedFact | null;
  graduation: { status: string; message: string };
}

export interface NotebookDocument {
  id: string;
  doc_type: string;
  type_label: string;
  title: string;
  source: "parsed_by_fork" | "student_recorded";
  status: "confirmed" | "recorded" | "superseded";
  status_label: string;
  read_by_fork: boolean;
  program: string | null;
  program_key: string | null;
  catalog_year: string | null;
  document_date: string | null;
  summary: {
    completed_hours?: number;
    in_progress_hours?: number;
    totals_reconciled?: boolean | null;
    course_count?: number;
    corrected_by_student?: number;
    requirements?: RequirementCounts;
    degree_hours?: DegreeHours | null;
    supplies_applicable_credits?: boolean;
    applicable_credits?: number;
    unresolved?: string[];
  };
  note: string | null;
  file: {
    stored: boolean;
    filename: string | null;
    content_type: string | null;
    size_bytes: number | null;
  };
  linked_facts: Fact[];
  added_at: string | null;
}

export interface LineItem {
  label: string;
  value: number | null;
  source: string;
  source_date: string;
  status?: string;
  status_note?: string;
}

export interface ScenarioOptionOutcome {
  major_key: string;
  major: string;
  status: "calculated" | "pending" | "failed";
  summary?: {
    current_major: string;
    prospective_major: string;
    credits_lost: number;
    incremental_semesters: number;
    incremental_tuition: number;
    incremental_total_cost: number;
    annual_salary_delta: number | null;
  };
  line_items?: Record<string, LineItem>;
  missing_fields?: string[];
  error?: string;
}

export interface CheckedInput {
  provenance: Provenance | null;
  provenance_label: string | null;
  source_label: string | null;
  source_date: string | null;
  document_id: string | null;
  note?: string;
}

export interface SavedScenario {
  id: string;
  title: string;
  kind: string;
  current_major: string;
  inputs: {
    current_major: string;
    credits_completed: CheckedInput & { value: number };
    credits_in_progress: number;
    options: (CheckedInput & { major: string; credits_transferable: number | null })[];
  };
  outcome: {
    anchor: { major_key: string; major: string };
    credits_completed: number;
    options: ScenarioOptionOutcome[];
    assumptions: string[];
    limitations: string[];
  };
  outcome_provenance: "derived";
  outcome_provenance_label: string;
  decision: string | null;
  note: string | null;
  calculated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TimelineEvent {
  id: string;
  event_type: string;
  summary: string;
  detail: Record<string, unknown>;
  document_id: string | null;
  scenario_id: string | null;
  occurred_at: string | null;
}

export interface NextStep {
  id: string;
  title: string;
  detail: string;
  reason: string;
  action: { label: string; href: string };
  optional?: boolean;
}

export interface Notebook {
  student: Student;
  snapshot: Snapshot;
  documents: NotebookDocument[];
  scenarios: SavedScenario[];
  timeline: TimelineEvent[];
  next_steps: NextStep[];
  storage: { raw_files_enabled: boolean; backend: string | null; message: string };
  provenance_labels: Record<Provenance, string>;
  has_record: boolean;
}

export class NotSignedIn extends Error {
  constructor() {
    super("Please sign in to continue.");
    this.name = "NotSignedIn";
  }
}

async function call<T>(
  path: string,
  init: { method?: string; body?: unknown; form?: FormData } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-Fork-CSRF"] = "1";
  let body: BodyInit | undefined;
  if (init.form) {
    body = init.form;
  } else if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }

  let res: Response;
  try {
    res = await fetch(`${NOTEBOOK_API}${path}`, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (networkError) {
    console.error("Fork: network error calling the notebook API", networkError);
    throw new ApiError("Fork couldn't reach your notebook right now. Please try again.");
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (res.status === 401) throw new NotSignedIn();
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const d = detail as { message: string; field?: string; errors?: { field?: string }[] };
      throw new ApiError(d.message, d.field ?? d.errors?.[0]?.field);
    }
    if (typeof detail === "string") throw new ApiError(detail);
    if (res.status === 429) throw new ApiError("Too many attempts. Please wait a few minutes.");
    throw new ApiError("Something went wrong. Please try again.");
  }
  return data as T;
}

// --- account ----------------------------------------------------------

const HINT_COOKIE = "fork_signed_in";

/** Whether this browser has signed in before. A hint only -- the backend
 * sets it beside the real HttpOnly session cookie so pages can skip an
 * identity request for visitors who never signed in. It proves nothing;
 * getMe() is what actually asks. */
export function hasSignInHint(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.split(";").some((c) => c.trim().startsWith(`${HINT_COOKIE}=1`));
}

function clearSignInHint() {
  if (typeof document !== "undefined") {
    document.cookie = `${HINT_COOKIE}=; Max-Age=0; path=/`;
  }
}

export async function getMe(): Promise<Student | null> {
  try {
    return (await call<{ student: Student }>("/account/me")).student;
  } catch (e) {
    if (e instanceof NotSignedIn) {
      // The session expired or was revoked; stop advertising one.
      clearSignInHint();
      return null;
    }
    throw e;
  }
}

export const register = (email: string, password: string, display_name?: string) =>
  call<{ student: Student }>("/account/register", {
    method: "POST",
    body: { email, password, display_name: display_name || null },
  }).then((r) => r.student);

export const login = (email: string, password: string) =>
  call<{ student: Student }>("/account/login", {
    method: "POST",
    body: { email, password },
  }).then((r) => r.student);

export const logout = () => call<{ status: string }>("/account/logout", { method: "POST" });

export const deleteAccount = (password: string) =>
  call<{ status: string }>("/account", { method: "DELETE", body: { password } });

// --- notebook -----------------------------------------------------------

export const getNotebook = () => call<Notebook>("/notebook");

export interface ProfileEdits {
  current_major?: string | null;
  gpa?: number | null;
  credits_completed?: number | null;
  credits_in_progress?: number | null;
  catalog_year?: string | null;
}

export const updateProfile = (edits: ProfileEdits) =>
  call<Notebook>("/notebook/profile", { method: "PUT", body: edits });

export const saveAuditToRecord = (auditSessionId: string, document: "current" | "what_if") =>
  call<{ created: boolean; document: NotebookDocument }>("/notebook/documents/from-audit", {
    method: "POST",
    body: { audit_session_id: auditSessionId, document },
  });

export interface RecordDocumentInput {
  doc_type: string;
  title: string;
  document_date?: string | null;
  note?: string | null;
}

export const recordDocument = (input: RecordDocumentInput) =>
  call<{ document: NotebookDocument }>("/notebook/documents", { method: "POST", body: input });

export function attachDocumentFile(documentId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return call<{ document: NotebookDocument }>(`/notebook/documents/${documentId}/file`, {
    method: "POST",
    form,
  });
}

export const documentFileUrl = (documentId: string) =>
  `${NOTEBOOK_API}/notebook/documents/${documentId}/file`;

export const removeDocument = (documentId: string) =>
  call<Notebook>(`/notebook/documents/${documentId}`, { method: "DELETE" });

export interface SaveScenarioInput {
  current_major: string;
  credits_completed: number;
  credits_in_progress?: number;
  credits_source?: string;
  options: {
    major: string;
    credits_transferable?: number | null;
    credits_transferable_source?: string;
  }[];
  title?: string;
  audit_session_id?: string | null;
}

export const saveScenario = (input: SaveScenarioInput) =>
  call<{ scenario: SavedScenario }>("/notebook/scenarios", { method: "POST", body: input });

export const updateScenario = (
  id: string,
  edits: { title?: string; note?: string | null; decision?: string | null },
) =>
  call<{ scenario: SavedScenario }>(`/notebook/scenarios/${id}`, {
    method: "PATCH",
    body: edits,
  });

export const refreshScenario = (id: string) =>
  call<{ changed: boolean; scenario: SavedScenario }>(`/notebook/scenarios/${id}/refresh`, {
    method: "POST",
  });

export const removeScenario = (id: string) =>
  call<{ status: string }>(`/notebook/scenarios/${id}`, { method: "DELETE" });
