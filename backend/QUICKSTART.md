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
pytest -v
```

73+ tests should pass across the engine, the data loader, major-key resolution, and the API layer — no AI, no network, pure math for the engine tests specifically.

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

## Data status

`data_sources/institutions/unt.json` now has **real, sourced academic and tuition figures** (UNT Registrar Transfer Guides and UNT Financial Aid & Scholarships, 2025-2026 catalog year). `median_starting_salary` / `salary_source` / `salary_source_date` on each major are still `"PLACEHOLDER"` — College Scorecard integration is Stage 4 and hasn't landed yet, so those numbers are not real and should not be quoted or demoed as such. Check `institutions/index.json`'s `status` field (`"partial_verified_data"`) for the current honest state.

Six majors are currently supported: `computer_science`, `information_technology`, `business_administration`, `psychology_ba`, `psychology_bs`, `mechanical_energy_engineering`. Three older keys are handled specially rather than being real majors — see `decision_paths/change_major/major_resolution.py`:
- `mechanical_engineering` (old key) auto-resolves to `mechanical_energy_engineering` with a warning in the response
- `psychology` (ambiguous — UNT offers both a B.A. and a B.S.) returns a 422 asking the caller to pick `psychology_ba` or `psychology_bs`
- `nursing` returns a 422 explaining that UNT's BSN is administered through UNT Health, a separate institution in the UNT System, and isn't modeled by this Decision Path yet

Tuition is now projected by full-time **semester**, not a flat per-credit rate — UNT bills a flat rate across a 12-15 hour full-time band and hourly below that. See `engine.py`'s `_project_tuition_cost` for the model and `unt.json`'s `institution.tuition` block for the sourced figures.

## What's not built yet

- Live data adapters (Scorecard/BLS API calls) — v1 uses the static JSON file above by design; see `ARCHITECTURE.md`
- The numeric-provenance check in `ai/interface.py::_verify_no_invented_numbers` is a stub — see the TODO comment in that file
- Second Decision Path (Graduate Now vs. Stay) — cut from v1 build scope; only add back if time remains
