import { describe, expect, it } from "vitest";
import { optionSourceFor, recordSources, sharedProvenanceFor } from "./compareProvenance";
import { AUDIT_SOURCE, EMPTY_SNAPSHOT, RECORD_SNAPSHOT, WHAT_IF_SOURCE } from "./notebook.fixtures";

const SESSION = {
  completed: 81,
  credits_source: AUDIT_SOURCE,
  credits_source_date: "08/18/2026 03:18 PM",
  credits_in_progress: 18,
};

describe("sharedProvenanceFor", () => {
  it("labels the figure only while it equals the document's", () => {
    expect(sharedProvenanceFor(81, [SESSION])).toEqual({
      credits_source: AUDIT_SOURCE,
      credits_source_date: "08/18/2026 03:18 PM",
      credits_in_progress: 18,
    });
    // Typed over: the student's number must not keep the audit's label.
    expect(sharedProvenanceFor(80, [SESSION])).toEqual({});
  });

  it("falls back to the notebook when this visit has no audit", () => {
    const { shared } = recordSources(RECORD_SNAPSHOT);
    expect(sharedProvenanceFor(81, [null, shared])).toMatchObject({
      credits_source: AUDIT_SOURCE,
      credits_in_progress: 18,
    });
  });

  it("sends nothing for an empty field", () => {
    expect(sharedProvenanceFor(null, [SESSION])).toEqual({});
  });
});

describe("optionSourceFor", () => {
  const options = recordSources(RECORD_SNAPSHOT).options;

  it("applies a What-If to its own program at its own value only", () => {
    expect(optionSourceFor("psychology_bs", 81, options)).toBe(WHAT_IF_SOURCE);
    expect(optionSourceFor("psychology_bs", 75, options)).toBeUndefined();
    expect(optionSourceFor("information_technology", 81, options)).toBeUndefined();
    expect(optionSourceFor("psychology_bs", null, options)).toBeUndefined();
  });
});

describe("recordSources", () => {
  it("never treats the student's own notebook figures as documents", () => {
    const typed = {
      ...EMPTY_SNAPSHOT,
      credits_completed: { ...RECORD_SNAPSHOT.credits_completed!, provenance: "student_reported" as const },
    };
    expect(recordSources(typed).shared).toBeNull();
  });

  it("is empty without a snapshot", () => {
    expect(recordSources(null)).toEqual({ shared: null, options: [] });
  });
});
