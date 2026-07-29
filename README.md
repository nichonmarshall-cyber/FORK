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
- Should I graduate now or stay another semester?
- Should I work more hours during the school year?
- Is a master's degree worth the additional debt?
- How much additional student debt is financially reasonable?

## How It Works

### 1. Collects

The platform collects relevant information conversationally through the AI interface.

### 2. Structures

The conversation is converted into validated inputs.

### 3. Calculates

Deterministic algorithms calculate projections using public data.

### 4. Explains

The AI explains the results, assumptions, limitations, and data sources in plain language.

## Core Principles

- AI explains results but does not make decisions.
- Deterministic calculations power every result.
- Every assumption is transparent.
- Every result is explainable.
- Public datasets are preferred.
- The platform grows through modular Decision Paths.

## Version 1 Decision Paths

### Change My Major

Projects:

- Lost credits
- Additional semesters
- Tuition differences
- Expected earnings differences

### Graduate Now vs. Stay Another Semester

Projects:

- Additional tuition and fees
- Foregone earnings
- Additional borrowing
- Potential benefits of staying

## Planned Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React, Next.js, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI |
| Database | PostgreSQL or Supabase |
| AI | Provider-agnostic LLM interface |
| Calculations | Python Decision Path modules |
| API format | Anthropic-compatible interface |

## Repository Structure

```text
fork/
├── README.md
├── ARCHITECTURE.md
├── frontend/
├── backend/
│   ├── app/
│   ├── ai/
│   ├── decision_paths/
│   │   ├── change_major/
│   │   └── graduate_now_vs_stay/
│   └── data_sources/
└── docs/
```

## Status

Pre-implementation. This repository currently contains planning documentation only.