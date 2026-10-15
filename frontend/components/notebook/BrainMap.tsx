"use client";

/**
 * The brain map: the notebook as an Obsidian-style graph.
 *
 * Every node and link comes from lib/graph.ts, which builds them from the
 * notebook payload alone -- so the map can't show a connection the record
 * doesn't contain. Layout is a d3-force simulation; rendering is plain SVG.
 *
 * Interaction mirrors Obsidian's graph view: hover lights a node's
 * neighbourhood and dims the rest, scroll zooms, dragging the background
 * pans, dragging a node moves it, and clicking opens it as a note with its
 * linked mentions. Every node is also reachable by keyboard.
 */

import Link from "next/link";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import { dateTime } from "@/lib/format";
import {
  EDGE_MEANING,
  GraphEdge,
  GraphNode,
  GraphNodeKind,
  buildNotebookGraph,
  neighbours,
} from "@/lib/graph";
import type { Notebook } from "@/lib/notebook";
import ProvenanceBadge from "./ProvenanceBadge";

type SimNode = GraphNode & SimulationNodeDatum;
type SimLink = SimulationLinkDatum<SimNode> & { kind: GraphEdge["kind"] };

const KIND_STYLE: Record<GraphNodeKind, { fill: string; label: string }> = {
  student: { fill: "#e2e8f0", label: "You" },
  major: { fill: "#a78bfa", label: "Majors" },
  document: { fill: "#34d399", label: "Documents" },
  fact: { fill: "#94a3b8", label: "Figures" },
  comparison: { fill: "#22d3ee", label: "Comparisons" },
  event: { fill: "#64748b", label: "Journey" },
};

const LINK_DISTANCE: Partial<Record<GraphEdge["kind"], number>> = {
  has_document: 90,
  established: 70,
  reported: 70,
  compares: 80,
  anchor: 70,
  plan: 70,
  applies_to: 60,
  touched: 55,
  in_journey: 120,
};

interface Position {
  x: number;
  y: number;
}

function radius(node: GraphNode, degree: number): number {
  if (node.kind === "student") return 11;
  return Math.min(4 + Math.sqrt(degree) * 2.2, 11);
}

export default function BrainMap({ notebook }: { notebook: Notebook }) {
  const [showEvents, setShowEvents] = useState(false);
  const graph = useMemo(
    () => buildNotebookGraph(notebook, { includeEvents: showEvents }),
    [notebook, showEvents],
  );
  const adjacency = useMemo(() => neighbours(graph), [graph]);
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());

  const [size, setSize] = useState({ width: 900, height: 560 });
  // The layout effect fits to the canvas when it settles, which can be after
  // a resize; it reads the latest size from here.
  const sizeRef = useRef(size);
  const [positions, setPositions] = useState<Map<string, Position>>(new Map());
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [hovered, setHovered] = useState<string | null>(null);
  // Once the student pans or zooms, the map stops re-fitting itself.
  const userMovedView = useRef(false);
  const [selected, setSelected] = useState<string | null>("student");

  // Fit the canvas to its container.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.max(320, Math.round(entry.contentRect.width));
      const next = { width, height: width < 640 ? 420 : 560 };
      sizeRef.current = next;
      setSize(next);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Run the layout. Rebuilt when the graph changes; positions of nodes that
  // survive the change are kept so toggling journey events doesn't reshuffle
  // everything.
  useEffect(() => {
    const previous = simNodesRef.current;
    const degree = (id: string) => adjacency.get(id)?.size ?? 0;
    const nodes: SimNode[] = graph.nodes.map((n) => {
      const old = previous.get(n.id);
      return old ? { ...n, x: old.x, y: old.y, vx: 0, vy: 0 } : { ...n };
    });
    const links: SimLink[] = graph.edges.map((e) => ({ ...e }));
    simNodesRef.current = new Map(nodes.map((n) => [n.id, n]));

    const sim = forceSimulation<SimNode, SimLink>(nodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => LINK_DISTANCE[l.kind] ?? 70)
          .strength(0.6),
      )
      .force("charge", forceManyBody<SimNode>().strength(-320))
      .force("collide", forceCollide<SimNode>((d) => radius(d, degree(d.id)) + 22).strength(0.9))
      .force("x", forceX<SimNode>(0).strength(0.04))
      .force("y", forceY<SimNode>(0).strength(0.05))
      .force("center", forceCenter(0, 0));

    const publish = () =>
      setPositions(new Map(nodes.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }])));

    const fit = () => {
      if (userMovedView.current || nodes.length === 0) return;
      const xs = nodes.map((n) => n.x ?? 0);
      const ys = nodes.map((n) => n.y ?? 0);
      const pad = 60;
      const w = Math.max(...xs) - Math.min(...xs) + pad * 2;
      const h = Math.max(...ys) - Math.min(...ys) + pad * 2;
      const { width, height } = sizeRef.current;
      const k = Math.min(1.6, Math.max(0.35, Math.min(width / w, height / h)));
      const cx = (Math.max(...xs) + Math.min(...xs)) / 2;
      const cy = (Math.max(...ys) + Math.min(...ys)) / 2;
      setView({ k, x: -cx * k, y: -cy * k });
    };

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      sim.stop();
      sim.tick(300);
      publish();
      fit();
    } else {
      sim.on("tick", publish);
      sim.on("end", fit);
    }
    simRef.current = sim;
    return () => {
      sim.stop();
    };
  }, [graph, adjacency]);

  // --- pointer interaction ------------------------------------------------

  const drag = useRef<
    | { mode: "pan"; startX: number; startY: number; origin: { x: number; y: number } }
    | { mode: "node"; id: string; moved: boolean }
    | null
  >(null);

  function toGraph(clientX: number, clientY: number): Position {
    const rect = svgRef.current!.getBoundingClientRect();
    return {
      x: (clientX - rect.left - size.width / 2 - view.x) / view.k,
      y: (clientY - rect.top - size.height / 2 - view.y) / view.k,
    };
  }

  function onBackgroundDown(e: React.PointerEvent) {
    userMovedView.current = true;
    drag.current = { mode: "pan", startX: e.clientX, startY: e.clientY, origin: { x: view.x, y: view.y } };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }

  function onNodeDown(e: React.PointerEvent, id: string) {
    e.stopPropagation();
    drag.current = { mode: "node", id, moved: false };
    (e.target as Element).setPointerCapture?.(e.pointerId);
    simRef.current?.alphaTarget(0.25).restart();
  }

  function onMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    if (d.mode === "pan") {
      setView((v) => ({ ...v, x: d.origin.x + e.clientX - d.startX, y: d.origin.y + e.clientY - d.startY }));
      return;
    }
    const node = simNodesRef.current.get(d.id);
    if (!node) return;
    const p = toGraph(e.clientX, e.clientY);
    node.fx = p.x;
    node.fy = p.y;
    d.moved = true;
  }

  function onUp() {
    const d = drag.current;
    drag.current = null;
    if (d?.mode === "node") {
      const node = simNodesRef.current.get(d.id);
      if (node) {
        node.fx = null;
        node.fy = null;
      }
      simRef.current?.alphaTarget(0);
      if (!d.moved) setSelected(d.id);
    }
  }

  function onWheel(e: React.WheelEvent) {
    userMovedView.current = true;
    const rect = svgRef.current!.getBoundingClientRect();
    const px = e.clientX - rect.left - size.width / 2;
    const py = e.clientY - rect.top - size.height / 2;
    setView((v) => {
      const k = Math.min(3, Math.max(0.35, v.k * Math.exp(-e.deltaY * 0.0015)));
      // Zoom toward the pointer, like Obsidian.
      return { k, x: px - ((px - v.x) * k) / v.k, y: py - ((py - v.y) * k) / v.k };
    });
  }

  function focus(id: string) {
    setSelected(id);
    const p = positions.get(id);
    if (p) setView((v) => ({ ...v, x: -p.x * v.k, y: -p.y * v.k }));
  }

  // Wheel events on an SVG are passive by default in React, so the page
  // would scroll as well as zoom. Prevent that natively.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const stop = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  // --- render ---------------------------------------------------------------

  const active = hovered ?? null;
  const lit = active ? new Set([active, ...(adjacency.get(active) ?? [])]) : null;
  const degree = (id: string) => adjacency.get(id)?.size ?? 0;
  const selectedNode = selected ? nodesById.get(selected) ?? null : null;
  const kindsPresent = [...new Set(graph.nodes.map((n) => n.kind))];

  return (
    <section
      aria-labelledby="map-heading"
      className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0a0e17]"
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-3.5">
        <div>
          <h2 id="map-heading" className="text-[15px] font-semibold text-slate-100">
            Brain map
          </h2>
          <p className="text-[12px] text-slate-500">
            Everything in your notebook and how it connects. Drag, scroll to zoom, click to open.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500" aria-label="Legend">
            {kindsPresent.map((k) => (
              <li key={k} className="flex items-center gap-1.5">
                <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: KIND_STYLE[k].fill }} />
                {KIND_STYLE[k].label}
              </li>
            ))}
          </ul>
          <label className="flex cursor-pointer items-center gap-1.5 text-[11.5px] text-slate-400">
            <input
              type="checkbox"
              checked={showEvents}
              onChange={(e) => setShowEvents(e.target.checked)}
              className="accent-cyan-400"
            />
            Show journey
          </label>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div ref={containerRef} className="relative min-w-0 bg-[radial-gradient(ellipse_at_center,#0d1424_0%,#060911_70%)]">
          <svg
            ref={svgRef}
            width={size.width}
            height={size.height}
            viewBox={`${-size.width / 2} ${-size.height / 2} ${size.width} ${size.height}`}
            className="block w-full touch-none select-none"
            role="group"
            aria-label="Brain map of your notebook"
            onPointerDown={onBackgroundDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
            onWheel={onWheel}
          >
            <defs>
              <filter id="map-glow" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="3.5" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
              <g>
                {graph.edges.map((e, i) => {
                  const a = positions.get(e.source);
                  const b = positions.get(e.target);
                  if (!a || !b) return null;
                  const on = lit ? lit.has(e.source) && lit.has(e.target) && (e.source === active || e.target === active) : false;
                  return (
                    <line
                      key={i}
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke={e.kind === "plan" ? "#fbbf24" : on ? "#67e8f9" : "#94a3b8"}
                      strokeOpacity={lit ? (on ? 0.85 : 0.05) : e.kind === "plan" ? 0.7 : 0.22}
                      strokeWidth={(e.kind === "plan" ? 1.6 : on ? 1.3 : 0.8) / Math.sqrt(view.k)}
                    />
                  );
                })}
              </g>
              <g>
                {graph.nodes.map((n) => {
                  const p = positions.get(n.id);
                  if (!p) return null;
                  const r = radius(n, degree(n.id));
                  const dim = lit ? !lit.has(n.id) : false;
                  const isSelected = n.id === selected;
                  // While hovering, only the lit neighbourhood is labelled, so
                  // its labels never sit on top of dimmed ones.
                  const showLabel = lit
                    ? lit.has(n.id)
                    : graph.nodes.length <= 30 ||
                      n.kind === "student" ||
                      n.kind === "major" ||
                      view.k > 1.25 ||
                      isSelected;
                  return (
                    <g
                      key={n.id}
                      transform={`translate(${p.x} ${p.y})`}
                      opacity={dim ? 0.15 : n.faded && !lit ? 0.55 : 1}
                      style={{ cursor: "pointer", transition: "opacity 120ms", outline: "none" }}
                      tabIndex={0}
                      role="button"
                      aria-label={`${KIND_STYLE[n.kind].label}: ${n.label}`}
                      aria-pressed={isSelected}
                      onPointerDown={(e) => onNodeDown(e, n.id)}
                      onPointerEnter={() => setHovered(n.id)}
                      onPointerLeave={() => setHovered(null)}
                      onFocus={() => setHovered(n.id)}
                      onBlur={() => setHovered(null)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          focus(n.id);
                        }
                      }}
                    >
                      {/* Invisible, larger hit area: the dots are small, and
                          a pointer or finger shouldn't have to land exactly. */}
                      <circle r={Math.max(r + 9, 14)} fill="transparent" />
                      {hovered === n.id && !isSelected && !n.highlighted && (
                        <circle r={r + 5} fill="none" stroke="#67e8f9" strokeOpacity={0.5} strokeWidth={1} />
                      )}
                      {(n.highlighted || isSelected) && (
                        <circle
                          r={r + 5}
                          fill="none"
                          stroke={n.highlighted ? "#fbbf24" : "#67e8f9"}
                          strokeOpacity={0.7}
                          strokeWidth={1.2}
                        />
                      )}
                      <circle
                        r={r}
                        fill={n.highlighted && n.kind === "major" ? "#fbbf24" : KIND_STYLE[n.kind].fill}
                        filter={n.kind === "student" || n.highlighted || (lit && lit.has(n.id)) ? "url(#map-glow)" : undefined}
                      />
                      {showLabel && (
                        <text
                          y={r + 12}
                          textAnchor="middle"
                          fontSize={11 / Math.sqrt(view.k)}
                          fill={n.kind === "student" ? "#f1f5f9" : "#cbd5e1"}
                          fillOpacity={0.9}
                          style={{ pointerEvents: "none", paintOrder: "stroke" }}
                          stroke="#060911"
                          strokeWidth={3 / Math.sqrt(view.k)}
                        >
                          {n.label.length > 30 ? `${n.label.slice(0, 28)}…` : n.label}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            </g>
          </svg>
          <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-black/40 px-2 py-1 text-[10.5px] text-slate-500">
            {graph.nodes.length} notes · {graph.edges.length} links
          </div>
          <div className="absolute bottom-3 right-3 flex gap-1">
            <MapButton label="Zoom in" onClick={() => setView((v) => ({ ...v, k: Math.min(3, v.k * 1.25) }))}>+</MapButton>
            <MapButton label="Zoom out" onClick={() => setView((v) => ({ ...v, k: Math.max(0.35, v.k / 1.25) }))}>−</MapButton>
            <MapButton
              label="Fit to view"
              onClick={() => {
                userMovedView.current = false;
                const pts = [...positions.values()];
                if (pts.length === 0) return;
                const xs = pts.map((p) => p.x);
                const ys = pts.map((p) => p.y);
                const w = Math.max(...xs) - Math.min(...xs) + 120;
                const h = Math.max(...ys) - Math.min(...ys) + 120;
                const k = Math.min(1.6, Math.max(0.35, Math.min(size.width / w, size.height / h)));
                setView({
                  k,
                  x: (-(Math.max(...xs) + Math.min(...xs)) / 2) * k,
                  y: (-(Math.max(...ys) + Math.min(...ys)) / 2) * k,
                });
              }}
            >
              ⟲
            </MapButton>
          </div>
        </div>

        <NotePanel
          node={selectedNode}
          graph={graph.edges}
          nodesById={nodesById}
          onSelect={focus}
        />
      </div>
    </section>
  );
}

function MapButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="h-7 w-7 rounded-md border border-white/10 bg-[#0a0e17]/90 text-[13px] text-slate-300 hover:border-cyan-400/40 hover:text-cyan-200"
    >
      {children}
    </button>
  );
}

/** The selected node as a note: what it is, where it came from, and every
 * link in and out -- Obsidian's "linked mentions". */
function NotePanel({
  node,
  graph,
  nodesById,
  onSelect,
}: {
  node: GraphNode | null;
  graph: GraphEdge[];
  nodesById: Map<string, GraphNode>;
  onSelect: (id: string) => void;
}) {
  if (!node) {
    return (
      <aside className="border-t border-white/[0.07] p-5 text-[12.5px] text-slate-500 lg:border-l lg:border-t-0">
        Click a node to open it.
      </aside>
    );
  }
  const mentions = graph
    .filter((e) => e.source === node.id || e.target === node.id)
    .map((e) => {
      const otherId = e.source === node.id ? e.target : e.source;
      return { edge: e, other: nodesById.get(otherId)! };
    })
    .filter((m) => m.other);

  return (
    <aside
      aria-live="polite"
      className="themed-scroll max-h-[560px] overflow-y-auto border-t border-white/[0.07] p-5 lg:border-l lg:border-t-0"
    >
      <p className="text-[10.5px] uppercase tracking-[0.15em]" style={{ color: KIND_STYLE[node.kind].fill }}>
        {KIND_STYLE[node.kind].label}
      </p>
      <h3 className="mt-1 text-[15px] font-semibold leading-snug text-slate-100">{node.label}</h3>
      {node.provenance && (
        <div className="mt-2">
          <ProvenanceBadge provenance={node.provenance} title={node.detail} />
        </div>
      )}
      {node.detail && node.detail !== node.label && (
        <p className="mt-2 text-[12.5px] leading-relaxed text-slate-400">{node.detail}</p>
      )}
      {node.when && <p className="mt-1 text-[11.5px] text-slate-500">{dateTime(node.when)}</p>}
      {node.highlighted && (
        <p className="mt-2 text-[12px] text-amber-300">Part of your current plan.</p>
      )}
      {node.href && (
        <Link href={node.href} className="mt-3 inline-block text-[12.5px] font-medium text-cyan-300 hover:underline">
          Open →
        </Link>
      )}

      <h4 className="mt-5 text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        Linked mentions · {mentions.length}
      </h4>
      <ul className="mt-2 space-y-1">
        {mentions.map(({ edge, other }, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => onSelect(other.id)}
              className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/[0.04]"
            >
              <span
                aria-hidden
                className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: KIND_STYLE[other.kind].fill }}
              />
              <span className="min-w-0">
                <span className="block truncate text-[12.5px] text-slate-200">{other.label}</span>
                <span className="block text-[10.5px] text-slate-500">{EDGE_MEANING[edge.kind]}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
