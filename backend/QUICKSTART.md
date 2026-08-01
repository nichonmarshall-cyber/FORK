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

84 tests should pass across the engine, data loader, major-key resolution, earnings import, and API layer. The calculation engine uses local data and fixed rules, so its tests do not need AI access or a network connection.

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

Fork now uses real, sourced data for degree requirements, tuition, and graduate earnings:

- **Degree requirements:** UNT Registrar Transfer Guides for the 2025-2026 catalog year
- **Tuition:** UNT Financial Aid & Scholarships for 2025-2026
- **Graduate earnings:** U.S. Department of Education College Scorecard, *Most Recent Cohorts — Field of Study*, released June 10, 2026

The academic and tuition data is stored in `data_sources/institutions/unt.json`. The College Scorecard download is converted into the small processed `unt_field_of_study.json` file used by the app.

The app does not need the original 153 MB federal CSV to run. The raw CSV and ZIP should stay out of Git because they are large and can be downloaded again from the government source. The processed JSON should be committed because it is small and required for a fresh clone to work.

### Regenerating the earnings data

1. Download the latest College Scorecard **Most Recent Cohorts — Field of Study** CSV.
2. Extract the CSV into `backend/data_raw/`.
3. From the `backend` folder, run the importer with the CSV path:

```bash
python scripts/import_scorecard.py data_raw/Most-Recent-Cohorts-Field-of-Study_06102026.csv
```

4. Run the tests again:

```bash
pytest -v
```

5. Commit the updated processed JSON, but do not commit the raw CSV or ZIP.

### How earnings are used

Fork uses the **median annual earnings one year after graduation** for the delayed-income estimate. This is the closest available measure of the income a student may postpone by graduating later.

The calculation uses the student's **current major**, because it compares switching majors with finishing the current degree sooner. Four-year and five-year earnings are kept for additional career context, but they are not used to calculate the cost of delayed graduation.

The result is described as **estimated early-career income delayed**. It is an estimate, not a guaranteed salary or guaranteed financial loss.

College Scorecard earnings have important limits that must remain visible in the app:

- The data covers students who received federal financial aid.
- Earnings are measured only for graduates who were working and not enrolled in school at the time.
- College Scorecard groups programs into broad fields. At UNT, Computer Science and Information Technology share one earnings group, and the Psychology B.A. and B.S. share another. Their displayed earnings are not unique to one exact degree.
- Privacy-suppressed data and unavailable data are different conditions. Neither should ever be changed to `$0`.

### Supported majors

Six majors are currently supported:

- `computer_science`
- `information_technology`
- `business_administration`
- `psychology_ba`
- `psychology_bs`
- `mechanical_energy_engineering`

Three older or unsupported keys are handled separately in `decision_paths/change_major/major_resolution.py`:

- `mechanical_engineering` automatically resolves to `mechanical_energy_engineering`, with a warning in the response.
- `psychology` returns a 422 response asking the caller to choose `psychology_ba` or `psychology_bs`.
- `nursing` returns a 422 response explaining that UNT's BSN is administered through UNT Health, a separate institution in the UNT System, and is not modeled by this Decision Path yet.

Tuition is projected by full-time **semester**, not by multiplying every credit by one flat rate. UNT charges a flat amount across the 12-15 credit full-time range and charges by credit below that range. See `_project_tuition_cost` in `engine.py` and the `institution.tuition` section of `unt.json` for the calculation and source details.

## What's not built yet

- Live Scorecard or BLS API refreshes — v1 uses the checked-in processed JSON by design; see `ARCHITECTURE.md`
- The numeric-provenance check in `ai/interface.py::_verify_no_invented_numbers` is a stub — see the TODO comment in that file
- Second Decision Path (Graduate Now vs. Stay) — cut from v1 build scope; only add back if time remains