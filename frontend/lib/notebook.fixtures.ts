/**
 * Notebook payloads for tests. Figures mirror the backend's redacted UNT
 * fixtures (81 completed, 18 in progress, a Psychology B.S. What-If at 81)
 * so frontend and backend tests describe the same student. Test-only.
 */

import type { Notebook, SavedScenario, Snapshot, Student } from "./notebook";

export const AUDIT_SOURCE = "UNT Degree Audit, confirmed by you";
export const WHAT_IF_SOURCE =
  "UNT What-If Audit — Bachelor of Science in Psychology, Fall 2026, confirmed by you";

export const STUDENT: Student = {
  id: "s1",
  email: "sam@example.edu",
  display_name: "Sam",
  institution_id: "unt",
  created_at: "2026-10-01T15:00:00+00:00",
};

const LABELS = {
  confirmed_document: "From a document you confirmed",
  student_reported: "You reported this",
  derived: "Calculated by Fork",
  what_if: "What-If scenario",
} as const;

function fact<T>(key: string, value: T, provenance: keyof typeof LABELS, source: string, extra = {}) {
  return {
    key,
    scope: null,
    value,
    provenance,
    provenance_label: LABELS[provenance],
    source_label: source,
    source_date: provenance === "student_reported" ? null : "08/20/2026 04:20 PM",
    document_id: provenance === "student_reported" ? null : "doc1",
    updated_at: "2026-10-02T15:00:00+00:00",
    ...extra,
  };
}

export const EMPTY_SNAPSHOT: Snapshot = {
  institution: { id: "unt", name: "University of North Texas" },
  current_major: null,
  program: null,
  catalog_year: null,
  gpa: null,
  credits_completed: null,
  credits_in_progress: null,
  applicable_credits: [],
  requirements: null,
  degree_hours: null,
  credits_remaining_current: null,
  graduation: {
    status: "not_projected",
    message: "Fork doesn't predict a graduation date.",
  },
};

export const RECORD_SNAPSHOT: Snapshot = {
  ...EMPTY_SNAPSHOT,
  current_major: fact("current_major", "computer_science", "confirmed_document", AUDIT_SOURCE, {
    display: "Computer Science",
  }),
  program: fact("program", "Bachelor of Science in Computer Science", "confirmed_document", AUDIT_SOURCE),
  catalog_year: fact("catalog_year", "Fall 2024", "confirmed_document", AUDIT_SOURCE),
  gpa: fact("gpa", 3.42, "student_reported", "Entered by you"),
  credits_completed: fact("credits_completed", 81, "confirmed_document", AUDIT_SOURCE),
  credits_in_progress: fact("credits_in_progress", 18, "confirmed_document", AUDIT_SOURCE),
  applicable_credits: [
    fact("applicable_credits", 81, "what_if", WHAT_IF_SOURCE, {
      scope: "psychology_bs",
      display: "Psychology (B.S.)",
      document_id: "doc2",
    }),
  ],
  requirements: fact(
    "requirements_summary",
    { complete: 7, in_progress: 3, unfulfilled: 4, unknown: 0, total: 14 },
    "confirmed_document",
    AUDIT_SOURCE,
  ),
  degree_hours: fact(
    "degree_hours",
    { earned: 81, needed: 21, in_progress: 18 },
    "confirmed_document",
    AUDIT_SOURCE,
  ),
  credits_remaining_current: {
    key: "credits_remaining_current",
    value: 39,
    provenance: "derived",
    provenance_label: LABELS.derived,
    source_label: "120 credits required for Computer Science minus 81 completed",
    source_date: "2025-08-26",
    inputs_provenance: ["confirmed_document", "confirmed_document"],
  },
};

export const SAVED: SavedScenario = {
  id: "sc1",
  title: "Compared Computer Science with Psychology (B.S.)",
  kind: "change_major_comparison",
  current_major: "computer_science",
  inputs: {
    current_major: "computer_science",
    credits_completed: {
      value: 81,
      provenance: "confirmed_document",
      provenance_label: LABELS.confirmed_document,
      source_label: AUDIT_SOURCE,
      source_date: "08/20/2026 04:20 PM",
      document_id: "doc1",
    },
    credits_in_progress: 18,
    options: [
      {
        major: "psychology_bs",
        credits_transferable: 81,
        provenance: "what_if",
        provenance_label: LABELS.what_if,
        source_label: WHAT_IF_SOURCE,
        source_date: "08/20/2026 04:24 PM",
        document_id: "doc2",
      },
    ],
  },
  outcome: {
    anchor: { major_key: "computer_science", major: "Computer Science" },
    credits_completed: 81,
    options: [
      {
        major_key: "psychology_bs",
        major: "Psychology (B.S.)",
        status: "calculated",
        summary: {
          current_major: "Computer Science",
          prospective_major: "Psychology (B.S.)",
          credits_lost: 0,
          incremental_semesters: 0,
          incremental_tuition: 0,
          incremental_total_cost: 0,
          annual_salary_delta: -21000,
        },
      },
    ],
    assumptions: [],
    limitations: [],
  },
  outcome_provenance: "derived",
  outcome_provenance_label: LABELS.derived,
  decision: null,
  note: null,
  calculated_at: "2026-10-03T15:00:00+00:00",
  created_at: "2026-10-03T15:00:00+00:00",
  updated_at: "2026-10-03T15:00:00+00:00",
};

export const EMPTY_NOTEBOOK: Notebook = {
  student: STUDENT,
  snapshot: EMPTY_SNAPSHOT,
  documents: [],
  scenarios: [],
  timeline: [
    {
      id: "e0",
      event_type: "notebook_started",
      summary: "Started your Fork notebook.",
      detail: {},
      document_id: null,
      scenario_id: null,
      occurred_at: "2026-10-01T15:00:00+00:00",
    },
  ],
  next_steps: [
    {
      id: "add_degree_audit",
      title: "Add your UNT degree audit",
      detail: "Your audit is the evidence behind your completed hours.",
      reason: "No confirmed degree audit in your record.",
      action: { label: "Add a degree audit", href: "/compare?panel=audit" },
    },
  ],
  storage: { raw_files_enabled: false, backend: null, message: "Fork isn't set up to keep original files." },
  provenance_labels: LABELS,
  has_record: false,
};

export const FULL_NOTEBOOK: Notebook = {
  ...EMPTY_NOTEBOOK,
  snapshot: RECORD_SNAPSHOT,
  has_record: true,
  scenarios: [SAVED],
  documents: [
    {
      id: "doc1",
      doc_type: "degree_audit",
      type_label: "Degree audit",
      title: "UNT Degree audit — Bachelor of Science in Computer Science",
      source: "parsed_by_fork",
      status: "confirmed",
      status_label: "Read by Fork, confirmed by you",
      read_by_fork: true,
      program: "Bachelor of Science in Computer Science",
      program_key: "computer_science",
      catalog_year: "Fall 2024",
      document_date: "08/20/2026 04:20 PM",
      summary: { completed_hours: 81, in_progress_hours: 18, course_count: 30, totals_reconciled: true },
      note: null,
      file: { stored: false, filename: null, content_type: null, size_bytes: null },
      linked_facts: [RECORD_SNAPSHOT.credits_completed!],
      added_at: "2026-10-02T15:00:00+00:00",
    },
    {
      id: "doc3",
      doc_type: "transcript",
      type_label: "Transcript",
      title: "Unofficial transcript",
      source: "student_recorded",
      status: "recorded",
      status_label: "Recorded by you, not read by Fork",
      read_by_fork: false,
      program: null,
      program_key: null,
      catalog_year: null,
      document_date: "2026-09-01",
      summary: {},
      note: null,
      file: { stored: false, filename: null, content_type: null, size_bytes: null },
      linked_facts: [],
      added_at: "2026-10-02T16:00:00+00:00",
    },
  ],
  timeline: [
    {
      id: "e2",
      event_type: "plan_chosen",
      summary: "Marked staying in Computer Science as your current plan.",
      detail: {},
      document_id: null,
      scenario_id: "sc1",
      occurred_at: "2026-10-03T16:00:00+00:00",
    },
    {
      id: "e1",
      event_type: "audit_added",
      summary: "Added your degree audit for Bachelor of Science in Computer Science: 81 hours completed, 18 in progress.",
      detail: {},
      document_id: "doc1",
      scenario_id: null,
      occurred_at: "2026-10-02T15:00:00+00:00",
    },
    ...EMPTY_NOTEBOOK.timeline,
  ],
  next_steps: [],
};
