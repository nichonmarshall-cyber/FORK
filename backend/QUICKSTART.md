# Quick Start

## 1. Install

```bash
cd backend
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Run tests (no API key required)

```bash
pytest decision_paths/change_major/tests/ -v
```

All 8 should pass. This is the engine working — no AI, no network, pure math.

## 3. Run the server

```bash
uvicorn main:app --reload
```

Open **http://localhost:8000/docs** — that's your free Swagger/OpenAPI UI, generated automatically.

## 4. Test the calculation endpoint (no AI key required)

```bash
curl -X POST http://localhost:8000/decision-paths/change-major/calculate \
  -H "Content-Type: application/json" \
  -d '{"current_major": "computer_science", "prospective_major": "information_technology", "credits_completed": 72, "credits_transferable": 60}'
```

This is your **demo backup path** if the AI conversation flow has issues live — the structured endpoint bypasses the AI entirely and always works if the engine works.

## 5. Enable the AI conversation flow

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Then:

```bash
curl -X POST http://localhost:8000/decision-paths/change-major/converse \
  -H "Content-Type: application/json" \
  -d '{"message": "I have completed 72 credits in Computer Science and I am thinking about switching to Information Technology. Around 60 of those credits should transfer."}'
```

## Before you demo or submit: replace the placeholder data

`data_sources/change_major_reference.json` is currently filled with **illustrative numbers, not real data**. Every field marked `"PLACEHOLDER"` needs to become:

- `institution.tuition_per_credit_hour` → your university's published tuition/fee schedule
- `majors.*.median_starting_salary` → College Scorecard (collegescorecard.ed.gov), filtered by your institution + field of study
- `majors.*.credits_required` → your university's degree catalog
- `source` / `source_date` on each → the actual URL and date you pulled the number, so the "Why am I seeing this?" panel cites something real

This is the single highest-leverage thing left to do — the whole pitch is "every number is real and traceable," so the demo data has to actually be real before you present it.

## What's not built yet

- Frontend (Next.js) — not started
- Live data adapters (Scorecard/BLS API calls) — v1 uses the static JSON file above by design; see `ARCHITECTURE.md`
- The numeric-provenance check in `ai/interface.py::_verify_no_invented_numbers` is a stub — see the TODO comment in that file
- Second Decision Path (Graduate Now vs. Stay) — cut from v1 build scope; only add back if time remains
