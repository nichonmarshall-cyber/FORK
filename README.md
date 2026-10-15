# Fork

**A fork in the road, priced.**

Evidence-based academic and financial decision support for college students.

## Overview

Fork helps college students understand the long-term academic and financial consequences of major decisions—changing majors, delaying graduation, or taking on additional debt—before they make them.

It is not a chatbot, and it is not an advisor.

The AI in this system is strictly an **interface layer**:

- It gathers information from students in natural language.
- It translates that information into structured inputs.
- It explains results in plain language.

Every number shown to the student is produced by a **deterministic calculation engine** operating on trusted public datasets.

## Problem Statement

Many college students—especially first-generation students—make life-changing academic and financial decisions without anyone experienced to guide them.

Examples include:

- Should I change my major after completing 72 credits?
- How many of my credits actually count toward the new degree?
- How much longer will this take, and what will it cost?
- Is the earnings difference worth the additional time?

## How It Works

### 1. Collects

Fork collects academic information two ways: entered directly by the student, or read from an uploaded UNT degree audit.

### 2. Structures

Uploaded documents are parsed into a normalized academic record. Manual entry is validated into the same shape.

### 3. Confirms

Nothing is calculated from a document until the student has reviewed Fork's reading of it and confirmed it is correct.

### 4. Calculates

Deterministic algorithms calculate projections using public data.

### 5. Explains

The AI explains the results, assumptions, limitations, and data sources in plain language.

## Core Principles

- AI explains results but does not make decisions.
- Deterministic calculations power every result.
- Every assumption is transparent.
- Every result is explainable.
- Public datasets are preferred.
- Confirmation is not verification—Fork checks its own reading with the student, not with the university.

## What Fork Does

### Change My Major

Compares the student's current major against up to four alternatives at once, projecting for each:

- Credits that carry over, and credits lost
- Additional semesters
- Tuition difference
- Expected earnings difference

Every figure carries its source and the date that source was accurate.

### Degree Audit Upload

A student can optionally upload their UNT degree audit instead of estimating.

Fork reads the document, normalizes it, and shows what it found—completed hours, hours in progress, catalog year, and every course—before any of it is used. The student confirms or corrects that reading first.

The parser separates completed coursework from work in progress, keeps repeated attempts visible without counting them twice, and checks its own arithmetic against the totals the audit states about itself. When those disagree, Fork says so rather than serving a figure it can't stand behind.

### What-If Audits

A degree audit establishes what a student has earned. It does not establish how much of that counts toward a *different* degree.

A What-If audit does. When a student uploads one for the major they're considering, Fork resolves it to that specific program and uses its figures for that comparison only—never for another major, and never as a universal transfer number. Options without a matching What-If keep manual estimation.

When two confirmed documents disagree, Fork shows the disagreement and asks the student how to read them together before calculating.

### Decision Map

Results are laid out as a map of what Fork can answer, what it still needs, and what it cannot determine. Every node opens to show the figure, where it came from, and what it does not tell you.

### Ask Fork

Follow-up questions in plain language, answered against the last calculation the student actually ran. The AI never recomputes a number and never sees an input the engine rejected.

### Academic Notebook

A signed-in student's home. It keeps their academic record and shows where every figure in it came from:

- **Snapshot** — major, catalog year, GPA, completed and in-progress credits, degree progress, and credits that would apply to another program. Each figure is labelled as one of four kinds: *from a document you confirmed*, *you reported*, *calculated by Fork*, or *What-If*.
- **Academic record** — the documents behind those figures. A degree audit or What-If audit is added after the student confirms Fork's reading of it; other documents (transcripts, catalog pages, advising notes) can be recorded but are marked as not read by Fork.
- **Paths explored** — saved comparisons, recalculated by the engine when saved, with the provenance of each input checked against the record rather than taken from the client. A student can mark which way they're leaning.
- **Academic journey** — a timeline of meaningful changes: documents added, details updated, comparisons saved, plans chosen.
- **Before you meet your advisor** — next steps triggered by specific gaps in the record, such as a transfer figure that is still an estimate.

A figure backed by a confirmed document can't be overwritten by a typed one; the student adds a newer document or removes the old one. The compare tool still works without an account.

- **Brain map** — the notebook as an Obsidian-style graph: documents, the figures they established, majors, comparisons, the chosen plan, and optionally every journey event. Click a node to open it with its linked mentions.

**GPA** is read from the UNT degree audit and used only when the audit's own arithmetic holds: grade points divided by attempted hours must give the printed average (UNT truncates to three decimals), and the header GPA must match.

**Read, not kept.** Each upload records the moment Fork read it ("Read Oct 14, 2026 at 10:36 PM"); the file itself is discarded right after parsing.

### Demo notebook

"Try the demo notebook" on the home page opens a read-only notebook for a fictional student, Jordan, with a year of documents, comparisons, a change of mind, and a final plan. The story is made up; every comparison in it is calculated by the real engine when the demo is built. It's rebuilt at each startup, refuses every change, and can be turned off with `FORK_DEMO=false`.

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React, Next.js, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI |
| Documents | pypdf, deterministic UNT audit parser |
| AI | Provider-agnostic LLM interface |
| Calculations | Python Decision Path modules |
| Accounts & notebook | PostgreSQL in production (SQLite locally), SQLAlchemy, Alembic migrations |
| Audit review | In-memory sessions |

Uploaded audits are parsed in memory and never written to disk, and the review step (correct, confirm) still lives in a short-lived in-memory session. Nothing becomes part of a student's durable record until they are signed in and choose to add a confirmed audit to their notebook. Even then Fork stores a summary of what it read and the student confirmed — hours, program, catalog year, requirement counts — not the course-by-course grade history or the PDF.

**Retention:** Fork keeps a student's notebook until they delete it. Deleting an account from the account page permanently removes the account, every document record and fact, saved comparisons, the timeline, sign-in sessions, and any original files held in document storage.

Original files are stored only for documents the student records themselves, and only when document storage is configured (`FORK_DOCUMENT_STORAGE`). Without it, Fork says so rather than accepting a file it won't keep.

## Repository Structure

```text
fork/
├── README.md
├── ARCHITECTURE.md
├── frontend/
│   ├── app/              # / (notebook), /compare, /account
│   ├── components/
│   │   └── notebook/
│   └── lib/
├── backend/
│   ├── main.py
│   ├── accounts/         # registration, sign-in, sessions, deletion
│   ├── db/               # models and DATABASE_URL configuration
│   ├── migrations/       # Alembic
│   ├── notebook/         # record, documents, scenarios, timeline
│   ├── ai/
│   ├── academic_record/
│   ├── audit_import/
│   │   └── unt/
│   ├── documents/
│   ├── session/
│   ├── conversation/
│   ├── decision_paths/
│   │   └── change_major/
│   ├── data_loading/
│   └── data_sources/
└── tools/
```

## Data Sources

| Data | Source |
|---|---|
| Degree requirements | UNT Registrar transfer guides |
| Tuition and fees | UNT published rates |
| Earnings by field | U.S. Department of Education, College Scorecard |
| Occupational outlook | U.S. Bureau of Labor Statistics |

Every figure Fork displays names its source and that source's date. Where Fork does not have verified data, it says so rather than estimating.

## Status

Working. The Change My Major path runs end to end—manual entry, degree audit upload, What-If comparison, deterministic calculation, and AI explanation—covered by 687 automated tests (546 backend, 141 frontend). Students can keep it all in an academic notebook.

Fork is currently built for the University of North Texas. Document parsing is tested against real UNT degree audit formats; other institutions would need their own parser and reference data.