"use client";

/**
 * "Your academic record": the documents behind the notebook.
 *
 * Each document says what it is, how it got here (read by Fork and
 * confirmed by you, or recorded by you and not read), when, and which facts
 * in the snapshot rest on it. Removing one removes those facts too, and the
 * confirmation says so before it happens.
 */

import Link from "next/link";
import { useId, useRef, useState } from "react";
import { hours, readAtLabel, shortDate } from "@/lib/format";
import { majorLabel } from "@/lib/majors";
import { ApiError } from "@/lib/types";
import {
  Notebook,
  NotebookDocument,
  attachDocumentFile,
  documentFileUrl,
  getNotebook,
  recordDocument,
  removeDocument,
} from "@/lib/notebook";
import ProvenanceBadge from "./ProvenanceBadge";
import { Field, INPUT } from "./AuthPanel";
import { useReadOnly } from "./readOnly";

const FACT_NAMES: Record<string, string> = {
  credits_completed: "Credits completed",
  credits_in_progress: "Credits in progress",
  catalog_year: "Catalog year",
  program: "Program",
  current_major: "Major",
  requirements_summary: "Requirement progress",
  degree_hours: "Degree hours",
  applicable_credits: "Applicable credits",
};

export default function RecordSection({
  notebook,
  onNotebook,
}: {
  notebook: Notebook;
  onNotebook: (next: Notebook) => void;
}) {
  const [adding, setAdding] = useState(false);
  const readOnly = useReadOnly();
  const current = notebook.documents.filter((d) => d.status !== "superseded");
  const older = notebook.documents.filter((d) => d.status === "superseded");

  return (
    <section
      id="record"
      aria-labelledby="record-heading"
      className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5"
    >
      <h2 id="record-heading" className="text-[15px] font-semibold text-slate-100">
        Your academic record
      </h2>
      <p className="mt-1 text-[12.5px] leading-relaxed text-slate-500">
        The documents your notebook rests on.
      </p>

      {current.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-white/10 p-4">
          <p className="text-[13px] text-slate-300">No documents yet.</p>
          <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
            Start with your UNT degree audit. Fork reads it, you check what it found, and
            the figures you confirm become your record.
          </p>
        </div>
      ) : (
        <ul className="mt-4 space-y-3">
          {current.map((d) => (
            <DocumentItem key={d.id} document={d} onNotebook={onNotebook} storageOn={notebook.storage.raw_files_enabled} />
          ))}
        </ul>
      )}

      {!readOnly && <div className="mt-4 flex flex-wrap gap-2">
        <Link
          href="/compare?panel=audit"
          className="rounded-lg bg-cyan-500/90 px-3 py-1.5 text-[12.5px] font-semibold text-slate-950 hover:bg-cyan-400"
        >
          Add a degree audit
        </Link>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          aria-expanded={adding}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-[12.5px] text-slate-300 hover:border-cyan-400/40 hover:text-cyan-200"
        >
          {adding ? "Cancel" : "Record another document"}
        </button>
      </div>}

      {adding && (
        <RecordDocumentForm
          storageOn={notebook.storage.raw_files_enabled}
          storageMessage={notebook.storage.message}
          onDone={async () => {
            setAdding(false);
            onNotebook(await getNotebook());
          }}
        />
      )}

      {older.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-[12px] text-slate-500 hover:text-slate-300">
            {older.length} replaced document{older.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-1.5">
            {older.map((d) => (
              <li key={d.id} className="text-[12px] text-slate-500">
                {d.title}
                {d.document_date ? ` · ${d.document_date}` : ""} — {d.status_label}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function DocumentItem({
  document: d,
  onNotebook,
  storageOn,
}: {
  document: NotebookDocument;
  onNotebook: (next: Notebook) => void;
  storageOn: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const readOnly = useReadOnly();

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      onNotebook(await removeDocument(d.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove that document.");
      setBusy(false);
    }
  }

  async function attach(file: File) {
    setBusy(true);
    setError(null);
    try {
      await attachDocumentFile(d.id, file);
      onNotebook(await getNotebook());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't attach that file.");
    } finally {
      setBusy(false);
    }
  }

  const isWhatIf = d.doc_type === "what_if_audit";
  const summary = d.summary;

  return (
    <li className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">{d.type_label}</p>
          <p className="mt-0.5 text-[13.5px] font-medium text-slate-100">{d.title}</p>
        </div>
        {d.read_by_fork ? (
          <ProvenanceBadge provenance={isWhatIf ? "what_if" : "confirmed_document"} title={d.status_label} />
        ) : (
          <span className="rounded-full border border-white/10 px-1.5 py-0.5 text-[9.5px] uppercase tracking-[0.1em] text-slate-500">
            Not read by Fork
          </span>
        )}
      </div>

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11.5px]">
        <dt className="text-slate-600">Status</dt>
        <dd className="text-slate-400">{d.status_label}</dd>
        <dt className="text-slate-600">Source</dt>
        <dd className="text-slate-400">
          {d.read_by_fork ? "Uploaded and read by Fork" : "Recorded by you"}
        </dd>
        {d.document_date && (
          <>
            <dt className="text-slate-600">Document date</dt>
            <dd className="text-slate-400">{d.document_date}</dd>
          </>
        )}
        <dt className="text-slate-600">Added</dt>
        <dd className="text-slate-400">{shortDate(d.added_at)}</dd>
        {d.catalog_year && (
          <>
            <dt className="text-slate-600">Catalog year</dt>
            <dd className="text-slate-400">{d.catalog_year}</dd>
          </>
        )}
      </dl>

      {d.read_by_fork && summary.read_at && (
        <p className="mt-2 text-[11.5px] text-slate-500">
          {`Read by Fork ${readAtLabel(summary.read_at)} · the file wasn’t kept`}
        </p>
      )}
      {d.read_by_fork && summary.completed_hours !== undefined && (
        <p className="mt-2 text-[12px] text-slate-400">
          Fork read {hours(summary.completed_hours)} completed and{" "}
          {hours(summary.in_progress_hours)} in-progress hours across {summary.course_count}{" "}
          courses
          {summary.corrected_by_student ? `, with ${summary.corrected_by_student} of your corrections` : ""}
          {summary.gpa?.reconciled ? `, and a cumulative GPA of ${summary.gpa.cumulative_gpa.toFixed(3)}` : ""}
          .
          {summary.totals_reconciled === false && (
            <span className="text-amber-300/90">
              {" "}
              Its totals didn&rsquo;t match the audit&rsquo;s own printed figures.
            </span>
          )}
        </p>
      )}
      {isWhatIf && summary.supplies_applicable_credits === false && (
        <p className="mt-2 text-[12px] text-amber-300/90">
          Fork isn&rsquo;t using this What-If for applicable credits:{" "}
          {(summary.unresolved ?? []).join(" ") || "its program couldn't be matched."}
        </p>
      )}

      {d.linked_facts.length > 0 && (
        <div className="mt-2">
          <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-600">
            Used in your record
          </p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {d.linked_facts.map((f) => (
              <li
                key={`${f.key}:${f.scope ?? ""}`}
                className="rounded-md border border-white/[0.07] px-1.5 py-0.5 text-[11px] text-slate-400"
              >
                {FACT_NAMES[f.key] ?? f.key}
                {typeof f.value === "number" || typeof f.value === "string"
                  ? `: ${f.key === "current_major" ? majorLabel(String(f.value)) : f.value}`
                  : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.note && <p className="mt-2 text-[12px] italic text-slate-500">{d.note}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
        {d.file.stored ? (
          <a
            href={documentFileUrl(d.id)}
            className="text-cyan-300 hover:underline"
          >
            Download {d.file.filename ?? "file"}
          </a>
        ) : d.source === "student_recorded" && storageOn && !readOnly ? (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,image/png,image/jpeg,text/plain"
              className="sr-only"
              aria-label={`Attach a file to ${d.title}`}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) attach(f);
              }}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="text-cyan-300 hover:underline disabled:opacity-60"
            >
              Attach the original file
            </button>
          </>
        ) : (
          <span className="text-slate-600">Original file not stored</span>
        )}

        {!readOnly && <span className="text-slate-700" aria-hidden>
          ·
        </span>}
        {readOnly ? null : confirming ? (
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-slate-400">
              {d.linked_facts.length > 0
                ? "Remove it and the figures that come from it?"
                : "Remove this document?"}
            </span>
            <button
              type="button"
              onClick={remove}
              disabled={busy}
              className="rounded-md border border-rose-500/40 px-2 py-0.5 text-rose-300 hover:bg-rose-500/10"
            >
              Remove
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-slate-500 hover:text-slate-300"
            >
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="text-slate-500 hover:text-rose-300"
          >
            Remove from record
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-[12px] text-rose-300">
          {error}
        </p>
      )}
    </li>
  );
}

const RECORDABLE = [
  { value: "transcript", label: "Transcript" },
  { value: "catalog", label: "Catalog / degree requirements" },
  { value: "advising_note", label: "Advising notes" },
  { value: "other", label: "Other academic document" },
];

function RecordDocumentForm({
  storageOn,
  storageMessage,
  onDone,
}: {
  storageOn: boolean;
  storageMessage: string;
  onDone: () => void;
}) {
  const [docType, setDocType] = useState("transcript");
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const noteId = useId();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setError("Give the document a title.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { document } = await recordDocument({
        doc_type: docType,
        title,
        document_date: date || null,
        note: note || null,
      });
      if (file && storageOn) await attachDocumentFile(document.id, file);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record that document.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="mt-4 space-y-3 border-t border-white/[0.07] pt-4">
      <p id={noteId} className="text-[12px] leading-relaxed text-slate-400">
        Fork won&rsquo;t read this document or take any figures from it. It sits in your
        record so you have everything in one place, marked as recorded by you.
      </p>
      <Field label="Type">
        <select value={docType} onChange={(e) => setDocType(e.target.value)} className={INPUT}>
          {RECORDABLE.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Title">
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={INPUT} />
      </Field>
      <Field label="Document date (optional)">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={INPUT} />
      </Field>
      <Field label="Note (optional)">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={2000}
          rows={2}
          className={INPUT}
        />
      </Field>
      {storageOn ? (
        <Field label="Original file (optional)" hint="PDF, PNG, JPEG, or text, up to 10 MB.">
          <input
            type="file"
            accept="application/pdf,image/png,image/jpeg,text/plain"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1.5 block text-[12px] text-slate-400"
          />
        </Field>
      ) : (
        <p className="text-[11.5px] leading-relaxed text-slate-500">{storageMessage}</p>
      )}
      {error && (
        <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-300">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="rounded-xl bg-cyan-500/90 px-4 py-2 text-[13px] font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
      >
        {busy ? "Saving…" : "Add to my record"}
      </button>
    </form>
  );
}
