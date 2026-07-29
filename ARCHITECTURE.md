# Architecture

## Design Goal

One rule governs this entire system: **the AI layer never calculates, and the calculation layer never talks to the user.**

Everything else — the module boundaries, the data flow, the testing strategy — follows from enforcing that rule structurally rather than by convention. It should be *impossible* for an AI-generated number to reach a student, not merely discouraged.

## System Layers

```
┌─────────────────────────────────────────────┐
│  Frontend (Next.js)                         │
│  Loads Decision Paths. Knows nothing about  │
│  how calculations work.                     │
└──────────────────┬──────────────────────────┘
                   │ structured requests/results
┌──────────────────▼──────────────────────────┐
│  API Layer (FastAPI)                        │
│  Routing, session handling, orchestration.  │
└─────┬────────────────────────────┬──────────┘
      │                            │
┌─────▼──────────────┐   ┌─────────▼──────────┐
│  AI Interface       │   │  Decision Path     │
│  Layer              │   │  Framework         │
│                     │   │                    │
│  - Conversation     │   │  - Input schemas   │
│  - Input extraction │   │  - Validation      │
│  - Explanation of   │   │  - Deterministic   │
│    computed results │   │    engines         │
│                     │   │  - Formatters      │
│  NEVER calculates   │   │  NEVER free-text   │
└─────────────────────┘   └─────────┬──────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  Data Source       │
                          │  Adapters          │
                          │  (Scorecard, BLS,  │
                          │  tuition tables…)  │
                          └────────────────────┘
```

## Request Lifecycle

1. **Conversation.** The student describes their situation. The AI layer asks follow-up questions until the Decision Path's input schema can be satisfied.
2. **Extraction.** The AI layer emits a structured input object (JSON) conforming to the Decision Path's schema. This is the AI's *only* output that enters the pipeline.
3. **Validation.** The Decision Path validates the structured inputs. Invalid or incomplete inputs are returned to the AI layer with specific gaps to resolve conversationally — they never reach the engine.
4. **Calculation.** The deterministic engine computes projections from validated inputs and data source adapters. No AI involvement. Identical inputs always produce identical outputs.
5. **Formatting.** The result formatter produces a structured result object: numbers, assumptions, and data source citations. This object directly powers the UI's **"Why am I seeing this?"** panel — an expandable view on every result listing data sources, assumptions, calculations performed, and limitations. Because provenance travels with every value from the engine outward, this panel requires no additional computation; it is a rendering of what the engine already knows.
6. **Explanation.** The AI layer receives the structured result and generates a plain-language narration of it. The prompt constrains the AI to describing values present in the result object; it cannot introduce numbers, comparisons, or recommendations not present in the input.

The structured result object — not the AI's narration — is the source of truth rendered in the UI. The narration is annotation.

## The Decision Path Framework

Each Decision Path is a self-contained module implementing a common contract:

```
decision_paths/change_major/
├── metadata.py     # ID, name, description, version, data source refs
├── inputs.py       # Input schema + validation rules
├── engine.py       # Deterministic calculation engine (pure functions)
├── formatter.py    # Structured result assembly
├── prompts.py      # AI extraction + explanation prompt templates
└── tests/          # Unit tests for engine and validation
```

**Contract requirements:**

- Engines are **pure functions**: validated inputs + data snapshots in, results out. No network calls, no randomness, no shared state.
- Every output value in a result object carries provenance: the formula or data source that produced it.
- A Decision Path may not import from another Decision Path.
- The framework discovers Decision Paths by metadata registration; the frontend renders whatever the registry exposes.

Adding a Decision Path means adding a directory. It never means modifying an existing one.

## Version 1 Decision Paths

### Change My Major

Compares the student's current path against a prospective major:

- Transferable vs. lost credits (user-provided in v1; catalog-derived in future versions)
- Additional semesters required and their tuition/fee cost
- Delayed graduation → delayed earnings (foregone median starting salary for the additional time)
- Median earnings differential between fields of study (College Scorecard, when integrated; static reference tables in v1)

### Graduate Now vs. Stay Another Semester

This path deliberately avoids modeling the *benefit* of staying, because that benefit is personal (a second internship cycle, a higher GPA, a double minor) and not something the platform can honestly quantify. Instead:

- The engine computes the **full cost of staying**: additional tuition and fees + one semester of foregone median starting earnings for the student's field.
- The student states their reason for staying as an input.
- The result presents: "Staying costs approximately $X. You stated you are staying for [reason]. Here is that cost broken down."

The platform prices the decision; the student judges whether the reason is worth the price. This is the "show the data, not opinions" principle applied at the design level.

## The AI Interface Layer

A single module (`backend/ai/`) owns all LLM communication. The rest of the system imports one interface:

```
extract_inputs(conversation, schema) -> StructuredInputs | ClarificationNeeded
explain_results(result_object, template) -> str
```

**Provider abstraction.** Because the AI's responsibilities are limited to extraction and narration, any capable LLM provider is interchangeable. The provider (Anthropic API in v1) is a configuration value. Swapping providers touches exactly one module and zero Decision Paths.

**Guardrails, enforced structurally:**

- Extraction outputs are schema-validated; malformed extractions are rejected, not repaired downstream.
- Explanation prompts receive *only* the result object. The AI cannot reference data it was not given.
- Explanations are post-checked: any numeric value in the narration must appear in the result object, or the narration is regenerated.

## Data Source Adapters

Each external dataset gets an adapter with a common interface: fetch, snapshot, cite. Engines consume **versioned snapshots**, never live queries — this keeps engines pure, results reproducible, and citations stable ("College Scorecard, 2025 release"). Adapter implementation is roadmap; v1 engines run on bundled static reference tables with the same snapshot interface, so swapping in live adapters later changes nothing upstream.

## Testing Strategy

- **Engines:** exhaustive unit tests. Pure functions make this cheap. Golden-file tests pin known input/output pairs so calculation changes are always deliberate and reviewed.
- **Validation:** property-based tests on schemas (garbage in, rejection out).
- **AI layer:** contract tests — extraction outputs must validate against schemas; explanation outputs must pass the numeric-provenance check. The AI's prose quality is evaluated separately and is never a correctness gate.
- **Integration:** one end-to-end test per Decision Path using a mocked AI layer, proving the pipeline works with the AI removed entirely. If the system cannot function with the AI mocked out, the AI has responsibilities it shouldn't have.

## Scalability Strategy

The platform scales along three independent axes:

1. **More Decision Paths** — additive, by contract.
2. **Better data** — adapter swaps, invisible to engines.
3. **Better AI** — provider/model swaps, invisible to everything.

No planned feature on the roadmap requires modifying this architecture. That is the test we will hold future work to: if a feature can't be built as a Decision Path, an adapter, or an AI-layer improvement, the feature — not the architecture — gets re-examined first.
