import { describe, expect, it } from "vitest";
import { buildNotebookGraph, neighbours } from "./graph";
import { EMPTY_NOTEBOOK, FULL_NOTEBOOK } from "./notebook.fixtures";

describe("buildNotebookGraph", () => {
  it("has just the student for an empty notebook", () => {
    const g = buildNotebookGraph(EMPTY_NOTEBOOK);
    expect(g.nodes.map((n) => n.kind)).toEqual(["student"]);
    expect(g.edges).toEqual([]);
  });

  it("links documents to the figures they established", () => {
    const g = buildNotebookGraph(FULL_NOTEBOOK);
    const edge = g.edges.find((e) => e.target === "fact:credits_completed");
    expect(edge).toEqual({ source: "doc:doc1", target: "fact:credits_completed", kind: "established" });
  });

  it("links a typed figure to the student, not to any document", () => {
    const g = buildNotebookGraph(FULL_NOTEBOOK);
    expect(g.edges.find((e) => e.target === "fact:gpa")).toEqual({
      source: "student",
      target: "fact:gpa",
      kind: "reported",
    });
  });

  it("connects comparisons to every major they weighed and marks the plan", () => {
    const plan = {
      ...FULL_NOTEBOOK,
      scenarios: [{ ...FULL_NOTEBOOK.scenarios[0], decision: "psychology_bs" }],
    };
    const g = buildNotebookGraph(plan);
    const kinds = g.edges.filter((e) => e.source === "cmp:sc1").map((e) => `${e.kind}:${e.target}`);
    expect(kinds).toEqual(
      expect.arrayContaining(["anchor:major:computer_science", "compares:major:psychology_bs", "plan:major:psychology_bs"]),
    );
    expect(g.nodes.find((n) => n.id === "major:psychology_bs")?.highlighted).toBe(true);
    expect(g.nodes.find((n) => n.id === "cmp:sc1")?.highlighted).toBe(true);
  });

  it("scopes What-If credits to their own major", () => {
    const g = buildNotebookGraph(FULL_NOTEBOOK);
    expect(g.edges).toContainEqual({
      source: "fact:applicable:psychology_bs",
      target: "major:psychology_bs",
      kind: "applies_to",
    });
  });

  it("adds journey events only when asked, each linked to what it touched", () => {
    expect(buildNotebookGraph(FULL_NOTEBOOK).nodes.some((n) => n.kind === "event")).toBe(false);
    const g = buildNotebookGraph(FULL_NOTEBOOK, { includeEvents: true });
    expect(g.edges).toContainEqual({ source: "evt:e1", target: "doc:doc1", kind: "touched" });
    expect(g.edges).toContainEqual({ source: "evt:e2", target: "cmp:sc1", kind: "touched" });
    expect(g.edges).toContainEqual({ source: "evt:e0", target: "student", kind: "in_journey" });
  });

  it("never draws an edge to a node that doesn't exist, or a duplicate", () => {
    const g = buildNotebookGraph(FULL_NOTEBOOK, { includeEvents: true });
    const ids = new Set(g.nodes.map((n) => n.id));
    for (const e of g.edges) {
      expect(ids.has(e.source)).toBe(true);
      expect(ids.has(e.target)).toBe(true);
    }
    const keys = g.edges.map((e) => `${e.source}>${e.target}>${e.kind}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("leaves no node unconnected", () => {
    const g = buildNotebookGraph(FULL_NOTEBOOK, { includeEvents: true });
    const adj = neighbours(g);
    for (const n of g.nodes) expect(adj.get(n.id)!.size).toBeGreaterThan(0);
  });
});
