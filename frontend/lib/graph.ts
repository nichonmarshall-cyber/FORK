/**
 * The notebook as a graph: what the brain map draws.
 *
 * Built purely from the notebook payload, so the map can never show a
 * connection the record doesn't contain. Every edge says why it exists:
 * a document established a figure, a comparison weighed a major, a plan
 * chose one, an event touched a document or comparison.
 */

import type { Notebook, Provenance } from "./notebook";
import { majorLabel } from "./majors";

export type GraphNodeKind =
  | "student"
  | "major"
  | "document"
  | "fact"
  | "comparison"
  | "event";

export type GraphEdgeKind =
  | "has_document"
  | "established"
  | "reported"
  | "compares"
  | "anchor"
  | "plan"
  | "applies_to"
  | "touched"
  | "in_journey";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  /** A second line in the details panel. */
  detail?: string;
  provenance?: Provenance;
  /** Dimmed: a superseded document, a past event. */
  faded?: boolean;
  /** The student's current plan. */
  highlighted?: boolean;
  href?: string;
  when?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: GraphEdgeKind;
}

export interface NotebookGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const EDGE_MEANING: Record<GraphEdgeKind, string> = {
  has_document: "in your record",
  established: "established by",
  reported: "you reported",
  compares: "compared",
  anchor: "measured from",
  plan: "your plan",
  applies_to: "would apply to",
  touched: "changed",
  in_journey: "part of your journey",
};

const FACT_LABELS: Record<string, (v: unknown) => string> = {
  current_major: (v) => `Major: ${majorLabel(String(v))}`,
  catalog_year: (v) => `Catalog ${v}`,
  gpa: (v) => `GPA ${v}`,
  credits_completed: (v) => `${v} credits completed`,
  credits_in_progress: (v) => `${v} in progress`,
};

/** Short names, so a comparison reads "vs IT & BBA" on the map. */
const SHORT: Record<string, string> = {
  computer_science: "CS",
  information_technology: "IT",
  business_administration: "BBA",
  psychology_ba: "Psych B.A.",
  psychology_bs: "Psych B.S.",
  mechanical_energy_engineering: "MEEN",
};

export function comparisonLabel(majorKeys: string[]): string {
  const names = majorKeys.map((k) => SHORT[k] ?? majorLabel(k));
  if (names.length === 0) return "Comparison";
  if (names.length === 1) return `vs ${names[0]}`;
  return `vs ${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}`;
}

export function buildNotebookGraph(
  notebook: Notebook,
  options: { includeEvents?: boolean } = {},
): NotebookGraph {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const edgeKeys = new Set<string>();

  const add = (node: GraphNode) => {
    if (!nodes.has(node.id)) nodes.set(node.id, node);
    return node.id;
  };
  const link = (source: string, target: string, kind: GraphEdgeKind) => {
    if (source === target || !nodes.has(source) || !nodes.has(target)) return;
    const key = `${source}>${target}>${kind}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    edges.push({ source, target, kind });
  };

  const student = add({
    id: "student",
    kind: "student",
    label: notebook.student.display_name || "You",
    detail: notebook.snapshot.institution.name,
  });

  const majorNode = (key: string) =>
    add({ id: `major:${key}`, kind: "major", label: majorLabel(key) });

  // Documents.
  for (const d of notebook.documents) {
    const id = add({
      id: `doc:${d.id}`,
      kind: "document",
      label: d.status === "superseded" ? `${d.type_label} (replaced)` : d.type_label,
      detail: `${d.title}${d.document_date ? ` · ${d.document_date}` : ""}`,
      provenance: d.read_by_fork
        ? d.doc_type === "what_if_audit"
          ? "what_if"
          : "confirmed_document"
        : undefined,
      faded: d.status === "superseded",
      href: "/#record",
      when: d.added_at,
    });
    link(student, id, "has_document");
  }

  // Facts from the snapshot, linked to the document behind them -- or to
  // the student when they typed it.
  const snap = notebook.snapshot;
  const singleFacts = [
    snap.current_major,
    snap.catalog_year,
    snap.gpa,
    snap.credits_completed,
    snap.credits_in_progress,
  ];
  for (const f of singleFacts) {
    if (!f) continue;
    const id = add({
      id: `fact:${f.key}`,
      kind: "fact",
      label: FACT_LABELS[f.key]?.(f.value) ?? `${f.key}: ${String(f.value)}`,
      detail: f.source_label,
      provenance: f.provenance,
    });
    if (f.document_id && nodes.has(`doc:${f.document_id}`)) {
      link(`doc:${f.document_id}`, id, "established");
    } else {
      link(student, id, "reported");
    }
  }
  if (snap.current_major) {
    link(`fact:current_major`, majorNode(snap.current_major.value), "anchor");
  }
  for (const f of snap.applicable_credits) {
    if (!f.scope) continue;
    const id = add({
      id: `fact:applicable:${f.scope}`,
      kind: "fact",
      label: `${f.value} hrs apply`,
      detail: f.source_label,
      provenance: f.provenance,
    });
    if (f.document_id && nodes.has(`doc:${f.document_id}`)) {
      link(`doc:${f.document_id}`, id, "established");
    }
    link(id, majorNode(f.scope), "applies_to");
  }

  // Comparisons and the majors they weighed.
  for (const s of notebook.scenarios) {
    const id = add({
      id: `cmp:${s.id}`,
      kind: "comparison",
      label: comparisonLabel(s.outcome.options.map((o) => o.major_key)),
      detail: s.title,
      provenance: "derived",
      highlighted: s.decision !== null,
      href: `/compare?scenario=${s.id}`,
      when: s.created_at,
    });
    link(id, majorNode(s.outcome.anchor.major_key), "anchor");
    for (const o of s.outcome.options) link(id, majorNode(o.major_key), "compares");
    if (s.decision) {
      const chosen = majorNode(s.decision);
      nodes.get(chosen)!.highlighted = true;
      link(id, chosen, "plan");
    }
  }

  // Majors hang off the student only through what touches them; give any
  // stray one a link so nothing floats away.
  for (const node of nodes.values()) {
    if (node.kind === "major" && !edges.some((e) => e.target === node.id || e.source === node.id)) {
      link(student, node.id, "compares");
    }
  }

  if (options.includeEvents) {
    for (const e of notebook.timeline) {
      const id = add({
        id: `evt:${e.id}`,
        kind: "event",
        label: e.summary.length > 42 ? `${e.summary.slice(0, 40)}…` : e.summary,
        detail: e.summary,
        faded: true,
        when: e.occurred_at,
        href: e.scenario_id ? `/compare?scenario=${e.scenario_id}` : undefined,
      });
      let linked = false;
      if (e.document_id && nodes.has(`doc:${e.document_id}`)) {
        link(id, `doc:${e.document_id}`, "touched");
        linked = true;
      }
      if (e.scenario_id && nodes.has(`cmp:${e.scenario_id}`)) {
        link(id, `cmp:${e.scenario_id}`, "touched");
        linked = true;
      }
      if (!linked) link(id, student, "in_journey");
    }
  }

  return { nodes: [...nodes.values()], edges };
}

/** Each node's neighbours, for hover highlighting. */
export function neighbours(graph: NotebookGraph): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const n of graph.nodes) map.set(n.id, new Set());
  for (const e of graph.edges) {
    map.get(e.source)?.add(e.target);
    map.get(e.target)?.add(e.source);
  }
  return map;
}
