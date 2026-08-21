"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CorrectionRequest, ReviewCourse, ReviewSummary } from "@/lib/audit";

/**
 * The course review dialog.
 *
 * Thirty-six courses do not fit in a 320px sidebar. Expanding them inline
 * produced a scroll region inside a scroll region, cropped titles, and a
 * horizontal scrollbar — so this lifts the whole list into a centered dialog
 * with room to read and edit.
 *
 * The edits staged here are NOT authoritative. They live in local state until
 * the student saves, at which point they go to the backend and the corrected
 * record comes back with recomputed totals. This component never adds up
 * hours itself: doing so would put a second, unverified arithmetic path next
 * to the parser's reconciled one, and the two would disagree eventually.
 *
 * Closing is deliberately awkward when there are unsaved edits. Escape and a
 * backdrop click are easy to hit by accident, and silently discarding
 * someone's corrections to a 36-row form is worse than one extra prompt.
 */

/** A staged edit, keyed by course and field. Flat rather than a patched copy
 * of the record so what's changed stays obvious and only real edits are
 * sent. */
type Draft = Record<string, Record<string, string>>;

const EDITABLE_STATUSES = [
  { value: "completed", label: "Completed" },
  { value: "in_progress", label: "In progress" },
  { value: "attempted_no_credit", label: "No credit earned" },
  { value: "not_counted", label: "Not counted toward hours" },
  { value: "unknown", label: "Can't confirm" },
];

export default function CourseReviewDialog({
  review,
  open,
  saving,
  fieldErrors,
  onClose,
  onSave,
}: {
  review: ReviewSummary;
  open: boolean;
  saving: boolean;
  /** Per-field messages from the backend, keyed `${courseKey}:${field}`.
   * Rendered beside the offending input rather than as one banner, so a
   * student doesn't have to hunt through 36 rows for the bad one. */
  fieldErrors: Record<string, string>;
  onClose: () => void;
  onSave: (corrections: CorrectionRequest[]) => void;
}) {
  const [draft, setDraft] = useState<Draft>({});
  const [editing, setEditing] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const dirty = Object.keys(draft).length > 0;

  // Staged edits are dropped when the dialog closes, so reopening always
  // starts from the server's version rather than a stale local one. Handled
  // by remounting from AuditPanel (a `key` tied to open state) rather than
  // resetting in an effect, which would setState during render.

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      attemptClose();
    }
    document.addEventListener("keydown", onKey);
    // The page behind a modal shouldn't scroll with it.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dirty]);

  function attemptClose() {
    if (dirty) {
      setConfirmingDiscard(true);
      return;
    }
    onClose();
  }

  function setField(courseKey: string, field: string, value: string) {
    setDraft((d) => ({ ...d, [courseKey]: { ...d[courseKey], [field]: value } }));
  }

  /** Staged value if the student has touched this field, otherwise the
   * server's. `field` is the BACKEND field name (term_code, number, hours),
   * which is not always the name the review view uses for display. */
  function valueFor(courseKey: string, field: string, current: string | null): string {
    const staged = draft[courseKey]?.[field];
    return staged !== undefined ? staged : (current ?? "");
  }

  const corrections = useMemo<CorrectionRequest[]>(
    () =>
      Object.entries(draft).flatMap(([course_key, fields]) =>
        Object.entries(fields).map(([field, value]) => ({
          field,
          value: field === "hours" ? Number(value) : value,
          course_key,
        })),
      ),
    [draft],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        // mousedown rather than click: a click that STARTS inside the dialog
        // and drifts onto the backdrop while selecting text shouldn't close it.
        if (e.target === e.currentTarget) attemptClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Review the courses Fork read"
        className="flex max-h-[85vh] w-full max-w-[880px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-950 shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.07] px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-slate-100">
              Courses Fork read from your audit
            </h2>
            {/* Program names run long. Wrapping beats truncating -- a
                cropped program name is exactly the sort of thing someone
                needs to read in full to spot a wrong document. */}
            <p className="mt-0.5 break-words text-[12px] leading-relaxed text-slate-500">
              {review.program}
              {review.catalog_year ? ` · Catalog year ${review.catalog_year}` : ""}
              {review.prepared_at ? ` · Prepared ${review.prepared_at}` : ""}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={attemptClose}
            aria-label="Close"
            className="shrink-0 cursor-pointer rounded-lg border border-white/10 px-2.5 py-1 text-[12px] text-slate-400 transition hover:border-white/25 hover:text-slate-100"
          >
            Close
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[12px] text-slate-500">
              {review.course_count} courses · {review.completed_hours} completed ·{" "}
              {review.in_progress_hours} in progress
            </p>
            {!editing ? (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="cursor-pointer rounded-lg border border-white/10 px-3 py-1.5 text-[12px] text-slate-300 transition hover:border-white/25 hover:text-slate-100"
              >
                Edit
              </button>
            ) : (
              <span className="text-[11.5px] text-cyan-300/80">
                Editing — nothing changes until you save.
              </span>
            )}
          </div>

          {/* Notices stay visible in here too. They explain things a student
              would otherwise read as parser mistakes -- particularly the
              repeated-attempt rows below. */}
          {review.notices.map((n) => (
            <p
              key={n}
              className="mb-2 rounded-lg border border-amber-400/25 bg-amber-400/[0.07] px-3 py-2 text-[11.5px] leading-relaxed text-amber-200/90"
            >
              {n}
            </p>
          ))}

          <CourseTable
            courses={review.courses}
            editing={editing}
            valueFor={valueFor}
            setField={setField}
            fieldErrors={fieldErrors}
          />

          {review.excluded_courses.length > 0 && (
            <>
              <h3 className="mt-5 mb-1.5 text-[10.5px] uppercase tracking-[0.15em] text-slate-600">
                Repeated attempts — not counted toward hours
              </h3>
              {/* Kept as their own rows rather than folded into the counted
                  attempt. The audit lists them separately and so does Fork;
                  collapsing them would hide the student's repeat history. */}
              <CourseTable
                courses={review.excluded_courses}
                editing={false}
                valueFor={valueFor}
                setField={setField}
                fieldErrors={fieldErrors}
              />
            </>
          )}
        </div>

        {editing && (
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] px-5 py-3.5">
            <p className="text-[11.5px] text-slate-500">
              {dirty
                ? `${corrections.length} change${corrections.length === 1 ? "" : "s"} not yet saved`
                : "No changes yet"}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setDraft({});
                  setEditing(false);
                }}
                className="cursor-pointer rounded-lg border border-white/10 px-3 py-1.5 text-[12px] text-slate-300 transition hover:border-white/25"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!dirty || saving}
                onClick={() => onSave(corrections)}
                className="cursor-pointer rounded-lg bg-cyan-500/90 px-3 py-1.5 text-[12px] font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saving ? "Saving…" : "Save corrections"}
              </button>
            </div>
          </footer>
        )}

        {confirmingDiscard && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/70 p-4">
            <div className="max-w-sm rounded-xl border border-white/10 bg-slate-900 p-4">
              <p className="text-[13px] leading-relaxed text-slate-200">
                You have unsaved corrections. Close without saving them?
              </p>
              <div className="mt-3 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmingDiscard(false)}
                  className="cursor-pointer rounded-lg border border-white/10 px-3 py-1.5 text-[12px] text-slate-300"
                >
                  Keep editing
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmingDiscard(false);
                    onClose();
                  }}
                  className="cursor-pointer rounded-lg bg-rose-500/90 px-3 py-1.5 text-[12px] font-semibold text-slate-950"
                >
                  Discard
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Table on wide screens, stacked cards on narrow ones.
 *
 * Both are rendered and one is hidden by breakpoint rather than measuring
 * the viewport, so there's no layout flash and it works before hydration.
 */
function CourseTable({
  courses,
  editing,
  valueFor,
  setField,
  fieldErrors,
}: {
  courses: ReviewCourse[];
  editing: boolean;
  valueFor: (courseKey: string, field: string, current: string | null) => string;
  setField: (k: string, f: string, v: string) => void;
  fieldErrors: Record<string, string>;
}) {
  return (
    <>
      <table className="hidden w-full table-fixed border-collapse sm:table">
        <thead>
          <tr className="border-b border-white/[0.07] text-left text-[10.5px] uppercase tracking-[0.12em] text-slate-600">
            <th className="w-[15%] py-1.5 pr-2 font-normal">Term</th>
            <th className="w-[16%] py-1.5 pr-2 font-normal">Course</th>
            <th className="py-1.5 pr-2 font-normal">Title</th>
            <th className="w-[9%] py-1.5 pr-2 text-right font-normal">Hrs</th>
            <th className="w-[10%] py-1.5 pr-2 font-normal">Grade</th>
            <th className="w-[19%] py-1.5 font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {courses.map((c) => (
            <tr key={c.key} className="border-b border-white/[0.04] align-top">
              <Cell>
                <Field course={c} field="term_code" current={c.term} display={c.term} editing={editing} valueFor={valueFor} setField={setField} errors={fieldErrors} />
              </Cell>
              <Cell>
                <Field course={c} field="number" current={c.course_code} display={c.course_code} editing={editing} valueFor={valueFor} setField={setField} errors={fieldErrors} />
              </Cell>
              {/* break-words, not truncate: a cropped title is unreviewable. */}
              <Cell className="break-words text-slate-500">
                <Field course={c} field="title" current={c.title} display={c.title ?? "—"} editing={editing} valueFor={valueFor} setField={setField} errors={fieldErrors} />
              </Cell>
              <Cell className="text-right tabular-nums">
                <Field course={c} field="hours" current={String(c.hours)} display={String(c.hours)} editing={editing} valueFor={valueFor} setField={setField} errors={fieldErrors} align="right" />
              </Cell>
              <Cell>
                <Field course={c} field="grade" current={c.grade} display={c.grade ?? "—"} editing={editing} valueFor={valueFor} setField={setField} errors={fieldErrors} />
              </Cell>
              <Cell>
                {editing ? (
                  <select
                    aria-label={`Status for ${c.course_code}`}
                    value={valueFor(c.key, "completion_status", c.status)}
                    onChange={(e) => setField(c.key, "completion_status", e.target.value)}
                    className="w-full rounded border border-white/10 bg-black/30 px-1 py-0.5 text-[11.5px] text-slate-200"
                  >
                    {EDITABLE_STATUSES.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="break-words text-slate-400">{c.status_label}</span>
                )}
              </Cell>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="space-y-2 sm:hidden">
        {courses.map((c) => (
          <div key={c.key} className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-2.5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-[12.5px] font-medium text-slate-200">{c.course_code}</span>
              <span className="text-[11.5px] tabular-nums text-slate-500">
                {c.hours} hrs · {c.grade ?? "—"}
              </span>
            </div>
            <p className="mt-0.5 break-words text-[11.5px] text-slate-500">{c.title}</p>
            <p className="mt-1 text-[11px] text-slate-600">
              {c.term} · {c.status_label}
            </p>
            {c.note && (
              <p className="mt-1 break-words text-[11px] leading-relaxed text-slate-600">{c.note}</p>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`py-1.5 pr-2 text-[11.5px] text-slate-300 ${className}`}>{children}</td>;
}

function Field({
  course,
  field,
  current,
  display,
  editing,
  valueFor,
  setField,
  errors,
  align = "left",
}: {
  course: ReviewCourse;
  /** Backend field name, e.g. "term_code". */
  field: string;
  /** Server value this input starts from. */
  current: string | null;
  display: string | null;
  editing: boolean;
  valueFor: (courseKey: string, field: string, current: string | null) => string;
  setField: (k: string, f: string, v: string) => void;
  errors: Record<string, string>;
  align?: "left" | "right";
}) {
  if (!editing) return <span className="break-words">{display ?? "—"}</span>;

  const error = errors[`${course.key}:${field}`];
  return (
    <>
      <input
        aria-label={`${field} for ${course.course_code}`}
        value={valueFor(course.key, field, current)}
        onChange={(e) => setField(course.key, field, e.target.value)}
        className={`w-full rounded border bg-black/30 px-1 py-0.5 text-[11.5px] text-slate-200 ${
          align === "right" ? "text-right tabular-nums" : ""
        } ${error ? "border-rose-500/60" : "border-white/10"}`}
      />
      {error && (
        <span className="mt-0.5 block break-words text-[10.5px] leading-snug text-rose-300">
          {error}
        </span>
      )}
    </>
  );
}