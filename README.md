# Fork
**A fork in the road, priced.** Evidence-based academic and financial decision support for college students.


## Overview

Fork helps college students understand the long-term academic and financial consequences of major decisions — changing majors, delaying graduation, taking on additional debt — before they make them.

It is not a chatbot and it is not an advisor. The AI in this system is strictly an **interface layer**: it gathers information from students in natural language, translates it into structured inputs, and explains results in plain language. Every number a student sees is produced by a **deterministic calculation engine** operating on trusted public datasets. The AI never calculates, never estimates, and never recommends.

The guiding philosophy: **show the data, not opinions.**

## Problem Statement

Many college students — especially first-generation students — make life-changing academic and financial decisions without anyone experienced to guide them:

- Should I change my major after 72 credits?
- Should I graduate now or stay another semester?
- Should I work more hours during the school year?
- Is a master's degree worth the additional debt?
- How much additional student debt is financially reasonable?

These decisions have consequences measured in years and tens of thousands of dollars, and they are typically made with incomplete information, on short timelines, under pressure. Academic advisors exist, but advising capacity is limited, meetings are short, and the financial dimension of academic decisions often goes unexamined entirely.

## What This Platform Does

Students describe their situation in plain language:

> "I've completed 72 credits in Computer Science and I'm thinking about switching to Information Technology."

The platform then:

1. **Collects** the relevant details conversationally (AI layer)
2. **Structures** the conversation into validated inputs (AI layer)
3. **Calculates** projections using deterministic math and public data (calculation engine)
4. **Explains** the results in plain language, with every assumption visible (AI layer)

The output is an objective, side-by-side projection of the student's options — not a recommendation. The student decides. The platform's job is to make sure they decide with the numbers in front of them.

## Guiding Principles

- **AI is the interface, not the decision maker.** The AI never invents calculations, estimates, or recommendations.
- **Deterministic calculations power every result.** Identical inputs always produce identical outputs.
- **Every assumption is transparent.** Students see what the projection assumes and where data comes from.
- **Every result is explainable.** Students should understand *why* they are seeing a particular outcome.
- **Public datasets are preferred.** Projections are grounded in sources anyone can verify.
- **Modularity over monoliths.** The platform scales by adding Decision Paths, not by rewriting existing code.

## What Is a Decision Path?

A **Decision Path** is a self-contained workflow that analyzes one specific academic or financial decision. Each Decision Path defines:

- **Purpose** — the single decision it addresses
- **Required inputs** — what the student must provide
- **Validation rules** — what constitutes complete, sane input
- **Deterministic calculation engine** — the math, isolated and unit-testable
- **Result formatter** — structured output for the frontend
- **Plain-language explanation** — AI-generated narration of deterministic results
- **Data source references** — where every number comes from

Decision Paths are fully independent. Adding a new one never requires modifying an existing one. See `ARCHITECTURE.md` for details.

## Version 1 Scope

Version 1 supports exactly **two** Decision Paths:

1. **Change My Major** — projects lost credits, added semesters, cost delta, and earnings differences between the current and prospective major.
2. **Graduate Now vs. Stay Another Semester** — projects the cost of an additional semester (tuition, fees, foregone earnings) against the student's stated reason for staying.

Both paths ship with **"Why am I seeing this?"** — every result includes an expandable explanation showing the data sources used, the assumptions made, the calculations performed, and the limitations of the analysis. This is not a bolt-on: the calculation engine attaches provenance to every value it produces, and this panel simply renders it. It is the visible proof of the platform's core promise.

Everything else is roadmap. See `PROJECT_ROADMAP.md`.

## Version 1 Limitations (Intentional)

Version 1 will **not** include:

- Personalized recommendations of any kind
- University integrations or live financial aid synchronization
- Authentication or saved student profiles
- Transcript imports or automatic degree audits
- Predictive AI models

These are deliberate exclusions, not oversights. A narrow, fully-tested core with two well-built Decision Paths is worth more than eight half-built ones. Limiting scope keeps the calculation engines auditable, the test surface small, and the architecture honest — every future feature must plug into the framework rather than bend it.

## Planned Data Sources

Future integrations, documented here as intent (not yet implemented):

- U.S. Department of Education **College Scorecard** (earnings by institution and field of study)
- University tuition and fee schedules
- Federal student loan interest rates and repayment calculators
- **Bureau of Labor Statistics** / Occupational Outlook Handbook
- Published peer-reviewed educational research
- University degree requirement catalogs

These sources allow the platform to generate objective projections rather than subjective recommendations.

## Planned Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React, Next.js, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI |
| Database | PostgreSQL (or Supabase) |
| AI | LLM provider, abstracted behind an internal interface (Anthropic API for v1) |

The AI layer is provider-agnostic **by design**. Because the AI never calculates and never recommends, it is replaceable by construction: the rest of the system talks to a single internal interface, and the underlying provider is a configuration value, not an architectural commitment. Version 1 targets the Anthropic API; swapping providers requires changing one module.

## Repository Structure (Planned)

```
fork/
├── README.md
├── ARCHITECTURE.md
├── PROJECT_ROADMAP.md
├── frontend/                  # Next.js application
├── backend/
│   ├── api/                   # FastAPI routes
│   ├── ai/                    # LLM interface layer (provider-agnostic)
│   ├── decision_paths/
│   │   ├── change_major/
│   │   │   ├── metadata.py
│   │   │   ├── inputs.py      # Schema + validation
│   │   │   ├── engine.py      # Deterministic calculations
│   │   │   ├── formatter.py
│   │   │   └── tests/
│   │   └── graduate_now_vs_stay/
│   │       └── (same structure)
│   └── data_sources/          # Dataset adapters
└── docs/
```

## Development Philosophy

This project prioritizes maintainability, scalability, explainability, transparency, modularity, and testability — in roughly that order. Documentation avoids marketing language. If a claim in these docs can't be traced to a calculation or a data source, it doesn't belong in the product either.

## Long-Term Vision

The long-term goal is a platform universities could adopt as a **student advising companion** — not a replacement for advisors, but a tool that lets students walk into an advising meeting already understanding the financial and academic consequences of the decision on the table. See `PROJECT_ROADMAP.md`.

## Status

Pre-implementation. This repository currently contains planning documentation only.
#   F O R K  
 