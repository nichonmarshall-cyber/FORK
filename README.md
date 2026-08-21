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

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React, Next.js, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI |
| Documents | pypdf, deterministic UNT audit parser |
| AI | Provider-agnostic LLM interface |
| Calculations | Python Decision Path modules |
| State | In-memory sessions; no student data is stored |

Uploaded documents are parsed in memory and never written to disk. Sessions live in the running process and clear on restart. A degree audit is an education record, and Fork keeps one only as long as the visit.

## Repository Structure

```text
fork/
├── README.md
├── ARCHITECTURE.md
├── frontend/
│   ├── app/
│   ├── components/
│   └── lib/
├── backend/
│   ├── main.py
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

Working. The Change My Major path runs end to end—manual entry, degree audit upload, What-If comparison, deterministic calculation, and AI explanation—covered by 570 automated tests.

Fork is currently built for the University of North Texas. Document parsing is tested against real UNT degree audit formats; other institutions would need their own parser and reference data.