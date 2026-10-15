import { describe, expect, it } from "vitest";
import { NODES_BY_ID, provenanceOf } from "./nodes";
import { CalcResult } from "./types";

/**
 * Confirmed-document provenance, end to end through the node layer.
 *
 * The bug these cover: Fork used the 81 applicable credits from a
 * confirmed Psychology What-If while simultaneously labelling them
 * "Student-reported", leaving the Degree Audit node stuck on "Needs info"
 * and asking for a document that had already been confirmed. Two causes —
 * the calculation request never carried credits_transferable_source, and
 * the Degree Audit resolver was a constant that ignored the result
 * entirely.
 *
 * Ground-truth figures come from the real fixtures (81 completed, 18 in
 * progress) but nothing here asserts on them as production behaviour;
 * they're just realistic values.
 */

const CURRENT_AUDIT_SOURCE = "UNT Degree Audit, confirmed by you";
const WHAT_IF_SOURCE =
  "UNT What-If Audit — Psychology, B.S., 2024-2025, confirmed by you";
const STUDENT_SOURCE = "Student-reported";

function line(label: string, value: number, source: string) {
  return { label, value, source, source_date: "08/18/2026" };
}

function result({
  completedSource = STUDENT_SOURCE,
  transferableSource = STUDENT_SOURCE,
  prospective = "Psychology (B.S.)",
}: {
  completedSource?: string;
  transferableSource?: string;
  prospective?: string;
} = {}): CalcResult {
  return {
    summary: {
      current_major: "Computer Science",
      prospective_major: prospective,
      incremental_semesters: 1,
      incremental_total_cost: 8000,
      annual_salary_delta: -2000,
    },
    comparison: {
      staying: {
        major: "Computer Science",
        line_items: [
          line("Credits required", 120, "UNT catalog"),
          line("Credits already completed", 81, completedSource),
        ],
      },
      switching: {
        major: prospective,
        line_items: [
          line(`Credits required — ${prospective}`, 120, "UNT catalog"),
          // Real production label. The node matches on a fragment, so the
          // fixture uses the full string the backend actually emits rather
          // than the fragment -- otherwise the test would pass against a
          // label that doesn't exist.
          line("Credits that transfer to prospective major", 81, transferableSource),
        ],
      },
    },
    line_items: [],
    earnings_context: [],
    career_context: [],
    why_am_i_seeing_this: { assumptions: [], limitations: [] },
  } as unknown as CalcResult;
}

const creditTransfer = NODES_BY_ID.get("credit_transfer")!;
const degreeAudit = NODES_BY_ID.get("degree_audit")!;

describe("provenanceOf", () => {
  it("recognizes a confirmed current audit", () => {
    expect(provenanceOf(CURRENT_AUDIT_SOURCE)).toBe("current_audit");
  });

  it("recognizes a confirmed What-If", () => {
    expect(provenanceOf(WHAT_IF_SOURCE)).toBe("what_if");
  });

  it("treats a What-If as a What-If, not a plain audit", () => {
    // A What-If source also contains the word "audit"; the more specific
    // match has to win or every What-If reads as a current audit.
    expect(provenanceOf(WHAT_IF_SOURCE)).not.toBe("current_audit");
  });

  it("treats the backend default as a student estimate", () => {
    expect(provenanceOf(STUDENT_SOURCE)).toBe("student");
    expect(provenanceOf(undefined)).toBe("student");
    expect(provenanceOf("")).toBe("student");
  });
});

describe("Credit Transfer node", () => {
  it("does not call What-If credits student-reported", () => {
    const node = creditTransfer.resolve(
      result({ transferableSource: WHAT_IF_SOURCE }),
    );
    expect(node.state).toBe("completed");
    expect(node.reason ?? "").not.toMatch(/your own estimate/i);
    expect(node.reason ?? "").toMatch(/confirmed What-If/i);
  });

  it("does not ask for a What-If that is already confirmed", () => {
    const node = creditTransfer.resolve(
      result({ transferableSource: WHAT_IF_SOURCE }),
    );
    expect(node.stillNeed).toBeUndefined();
  });

  it("still flags a genuine student estimate", () => {
    const node = creditTransfer.resolve(result());
    expect(node.state).toBe("needs_info");
    expect(node.stillNeed?.join(" ")).toMatch(/what-if/i);
  });
});

describe("Degree Audit node", () => {
  it("asks for documents when none are confirmed", () => {
    const node = degreeAudit.resolve(result());
    expect(node.state).toBe("needs_info");
    expect(node.stillNeed?.join(" ")).toMatch(/upload/i);
  });

  it("recognizes a confirmed current audit", () => {
    const node = degreeAudit.resolve(
      result({ completedSource: CURRENT_AUDIT_SOURCE }),
    );
    expect(node.known?.join(" ")).toMatch(/current degree audit confirmed/i);
    expect(node.stillNeed?.join(" ") ?? "").not.toMatch(/upload your degree audit/i);
  });

  it("recognizes both documents and reports each truthfully", () => {
    const node = degreeAudit.resolve(
      result({
        completedSource: CURRENT_AUDIT_SOURCE,
        transferableSource: WHAT_IF_SOURCE,
      }),
    );
    expect(node.state).toBe("completed");
    const known = node.known?.join(" ") ?? "";
    expect(known).toMatch(/current degree audit confirmed/i);
    expect(known).toMatch(/what-if audit confirmed for psychology/i);
    expect(known).toMatch(/81/);
    // Nothing left to ask for.
    expect(node.stillNeed).toBeUndefined();
  });

  it("order of upload does not matter", () => {
    // Whichever document arrived first, the confirmed state is the same —
    // the node reads the calculated result, not an upload sequence.
    const a = degreeAudit.resolve(
      result({
        completedSource: CURRENT_AUDIT_SOURCE,
        transferableSource: WHAT_IF_SOURCE,
      }),
    );
    const b = degreeAudit.resolve(
      result({
        transferableSource: WHAT_IF_SOURCE,
        completedSource: CURRENT_AUDIT_SOURCE,
      }),
    );
    expect(a.state).toBe(b.state);
    expect(a.known).toEqual(b.known);
  });

  it("stays partial when only the current audit is confirmed", () => {
    // A confirmed audit plus an estimated transfer figure is genuinely
    // incomplete; calling it complete would overstate the registrar.
    const node = degreeAudit.resolve(
      result({ completedSource: CURRENT_AUDIT_SOURCE }),
    );
    expect(node.state).toBe("needs_info");
    expect(node.stillNeed?.join(" ")).toMatch(/what-if/i);
  });

  it("names the major a What-If is still needed for", () => {
    const node = degreeAudit.resolve(
      result({
        completedSource: CURRENT_AUDIT_SOURCE,
        prospective: "Information Technology",
      }),
    );
    expect(node.stillNeed?.join(" ")).toMatch(/information technology/i);
  });

  it("a Psychology What-If does not describe an IT comparison", () => {
    // Switching to a major the document doesn't cover means the transfer
    // figure is the student's own again, so the node must say so rather
    // than carrying Psychology's provenance across.
    const node = degreeAudit.resolve(
      result({
        completedSource: CURRENT_AUDIT_SOURCE,
        transferableSource: STUDENT_SOURCE,
        prospective: "Information Technology",
      }),
    );
    expect(node.known?.join(" ") ?? "").not.toMatch(/what-if/i);
    expect(node.stillNeed?.join(" ")).toMatch(/information technology/i);
  });
});
