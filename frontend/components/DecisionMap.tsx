"use client";

/**
 * The decision map.
 *
 * Fixed coordinates rather than a force-directed layout — the shape of this
 * decision doesn't change between students, so computing it every render
 * would be work for no benefit, and a stable layout is easier to read.
 */

import { useMemo } from "react";
import { BRANCH_COLOR, NODES, NODES_BY_ID, NodeDef, NodeState } from "@/lib/nodes";
import { CalcResult } from "@/lib/types";

const RADIUS = { center: 66, hub: 44, leaf: 29 } as const;

/** Locked and idle nodes recede; answered nodes carry their branch colour. */
function nodeTone(state: NodeState, branch: string) {
  const color = BRANCH_COLOR[branch as keyof typeof BRANCH_COLOR];
  switch (state) {
    case "completed":
    case "at_risk":
      return { stroke: color, fill: "#080d16", opacity: 1, bloom: true };
    case "needs_info":
      return { stroke: color, fill: "#080d16", opacity: 0.92, bloom: false };
    case "locked":
      return { stroke: "#39445a", fill: "#0a0e18", opacity: 0.5, bloom: false };
    default:
      return { stroke: "#28324a", fill: "#0a0e18", opacity: 0.38, bloom: false };
  }
}

/** Glyphs drawn inside hub nodes. Paths are centred on 0,0. */
const ICONS: Record<string, string> = {
  leaf: "M0 7c0-6 4-10 9-11-1 6-4 10-9 11z M0 7c0-6-4-10-9-11 1 6 4 10 9 11z M0 7v-4",
  book: "M-8-6h6a2 2 0 0 1 2 2v10a2 2 0 0 0-2-2h-6z M8-6h-6a2 2 0 0 0-2 2v10a2 2 0 0 1 2-2h6z",
  dollar: "M0-9v18 M4-5c0-2-2-3-4-3s-4 1-4 3 2 3 4 3.5 4 1.5 4 3.5-2 3-4 3-4-1-4-3",
  briefcase: "M-9-3h18v10h-18z M-4-3v-3a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v3",
  calendar: "M-8-6h16v14h-16z M-8-1h16 M-4-9v5 M4-9v5",
  check: "M-6 0l4 4 8-9",
};

interface Props {
  result: CalcResult | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function DecisionMap({ result, selectedId, onSelect }: Props) {
  const resolved = new Map(NODES.map((n) => [n.id, n.resolve(result)]));

  // Deterministic starfield — a random one would reshuffle on every render
  // and flicker whenever the result changes.
  const stars = useMemo(() => {
    let seed = 1337;
    const rand = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    return Array.from({ length: 130 }, () => ({
      cx: rand() * 1000,
      cy: rand() * 720,
      r: rand() * 1.1 + 0.25,
      o: rand() * 0.5 + 0.08,
    }));
  }, []);

  return (
    <svg
      viewBox="0 0 1000 720"
      className="h-full w-full"
      role="group"
      aria-label="Change major decision map"
    >
      <defs>
        <filter id="bloom" x="-90%" y="-90%" width="280%" height="280%">
          <feGaussianBlur stdDeviation="7" result="b1" />
          <feGaussianBlur stdDeviation="2" result="b2" />
          <feMerge>
            <feMergeNode in="b1" />
            <feMergeNode in="b2" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="softBloom" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="2.5" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <radialGradient id="vignette">
          <stop offset="45%" stopColor="#060a14" stopOpacity="0" />
          <stop offset="100%" stopColor="#03050b" stopOpacity="0.95" />
        </radialGradient>
        <radialGradient id="coreGlow">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect width="1000" height="720" fill="#060911" />
      {stars.map((s, i) => (
        <circle key={i} cx={s.cx} cy={s.cy} r={s.r} fill="#cfe4ff" opacity={s.o} />
      ))}
      <circle cx={500} cy={360} r={280} fill="url(#coreGlow)" />
      <rect width="1000" height="720" fill="url(#vignette)" />

      {/* Connectors, drawn before nodes so nodes sit on top. */}
      {NODES.filter((n) => n.parent).map((n) => {
        const parent = NODES_BY_ID.get(n.parent!)!;
        const state = resolved.get(n.id)!.state;
        const dim = state === "locked" || state === "idle";
        const color = dim ? "#1f2739" : BRANCH_COLOR[n.branch];

        return (
          <g key={`edge-${n.id}`}>
            <path
              d={curve(parent, n)}
              fill="none"
              stroke={color}
              strokeWidth={n.kind === "hub" ? 2.4 : 1.4}
              strokeOpacity={dim ? 0.45 : 0.6}
              strokeDasharray={n.kind === "hub" ? undefined : "1.5 8"}
              strokeLinecap="round"
              filter={dim ? undefined : "url(#softBloom)"}
            />
            {/* Motes along live branches. */}
            {!dim &&
              [0.32, 0.58, 0.8].map((t) => {
                const p = pointOn(parent, n, t);
                return (
                  <circle
                    key={t}
                    cx={p.x}
                    cy={p.y}
                    r={n.kind === "hub" ? 2.1 : 1.5}
                    fill={color}
                    opacity={0.85}
                  />
                );
              })}
          </g>
        );
      })}

      {NODES.map((node) => {
        const r = resolved.get(node.id)!;
        const tone = nodeTone(r.state, node.branch);
        const radius = RADIUS[node.kind];
        const isSelected = selectedId === node.id;
        const hasIcon = Boolean(node.icon) && node.kind !== "leaf";

        return (
          <g
            key={node.id}
            transform={`translate(${node.x} ${node.y})`}
            onClick={() => onSelect(node.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(node.id);
              }
            }}
            tabIndex={0}
            role="button"
            aria-label={`${node.label}. ${r.state.replace("_", " ")}.`}
            className="cursor-pointer outline-none [&:focus-visible>circle:first-of-type]:stroke-white"
            opacity={tone.opacity}
          >
            {isSelected && (
              <circle
                r={radius + 11}
                fill="none"
                stroke={tone.stroke}
                strokeWidth={1.2}
                strokeOpacity={0.45}
              />
            )}

            <circle
              r={radius}
              fill={tone.fill}
              stroke={tone.stroke}
              strokeWidth={node.kind === "leaf" ? 1.6 : 2.4}
              filter={tone.bloom ? "url(#bloom)" : undefined}
            />

            {hasIcon && (
              <path
                d={ICONS[node.icon as string]}
                transform={`translate(0 ${node.kind === "center" ? -20 : -13}) scale(${node.kind === "center" ? 0.85 : 0.62})`}
                fill="none"
                stroke={tone.stroke}
                strokeWidth={node.kind === "center" ? 2 : 2.6}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="pointer-events-none"
              />
            )}

            <text
              textAnchor="middle"
              className="pointer-events-none select-none"
              fill={r.state === "locked" ? "#8493ab" : "#eaf1fb"}
              fontSize={node.kind === "center" ? 15 : node.kind === "hub" ? 11 : 8.5}
              fontWeight={node.kind === "leaf" ? 500 : 600}
            >
              {wrap(node.label, node.kind).map((line, i, arr) => {
                const lh = node.kind === "center" ? 17 : 10.5;
                const shift = hasIcon ? (node.kind === "center" ? 12 : 9) : 0;
                return (
                  <tspan key={line} x={0} y={(i - (arr.length - 1) / 2) * lh + shift}>
                    {line}
                  </tspan>
                );
              })}
            </text>

            {/* State marker, upper-right of the circle. */}
            <g transform={`translate(${radius * 0.71} ${-radius * 0.71})`}>
              {r.state === "completed" && (
                <>
                  <circle r={7.5} fill="#0a1626" stroke="#34d399" strokeWidth={1} />
                  <path
                    d="M -3 0 L -1 2.4 L 3.2 -2.4"
                    fill="none"
                    stroke="#34d399"
                    strokeWidth={1.7}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              )}
              {r.state === "at_risk" && (
                <>
                  <circle r={7.5} fill="#1a1206" stroke="#fbbf24" strokeWidth={1} />
                  <path
                    d="M 0 -3.4 L 3.4 2.6 L -3.4 2.6 Z"
                    fill="none"
                    stroke="#fbbf24"
                    strokeWidth={1.3}
                    strokeLinejoin="round"
                  />
                  <path
                    d="M 0 -0.6 v 1.5"
                    stroke="#fbbf24"
                    strokeWidth={1.2}
                    strokeLinecap="round"
                  />
                </>
              )}
              {r.state === "needs_info" && (
                <>
                  <circle
                    r={7.5}
                    fill="#0a1626"
                    stroke={tone.stroke}
                    strokeWidth={1.1}
                    strokeDasharray="3 2.6"
                  />
                  <text
                    textAnchor="middle"
                    y={3.2}
                    fontSize={9.5}
                    fontWeight={700}
                    fill={tone.stroke}
                  >
                    ?
                  </text>
                </>
              )}
              {r.state === "locked" && (
                <>
                  <circle r={7.5} fill="#0a0e18" stroke="#46536d" strokeWidth={1} />
                  <path
                    d="M -2.3 0.4 h 4.6 v 3.1 h -4.6 z M -1.5 0.4 v -1.7 a 1.5 1.5 0 0 1 3 0 v 1.7"
                    fill="none"
                    stroke="#8493ab"
                    strokeWidth={1}
                    strokeLinejoin="round"
                  />
                </>
              )}
            </g>
          </g>
        );
      })}
    </svg>
  );
}

/**
 * A gentle arc between two nodes. The control point is pushed perpendicular
 * to the line so branches bow outward instead of meeting at hard angles.
 */
function curve(a: NodeDef, b: NodeDef): string {
  const c = control(a, b);
  return `M ${a.x} ${a.y} Q ${c.x} ${c.y} ${b.x} ${b.y}`;
}

function control(a: NodeDef, b: NodeDef) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const bow = len * 0.11;
  return {
    x: (a.x + b.x) / 2 + (-dy / len) * bow,
    y: (a.y + b.y) / 2 + (dx / len) * bow,
  };
}

/** Position along the same quadratic curve, for the motes. */
function pointOn(a: NodeDef, b: NodeDef, t: number) {
  const c = control(a, b);
  const u = 1 - t;
  return {
    x: u * u * a.x + 2 * u * t * c.x + t * t * b.x,
    y: u * u * a.y + 2 * u * t * c.y + t * t * b.y,
  };
}

/** Break long leaf labels onto two lines so they fit inside the circle. */
function wrap(label: string, kind: "center" | "hub" | "leaf"): string[] {
  const words = label.split(" ");
  if (words.length === 1) return words;
  if (kind === "center") return words;
  const mid = Math.ceil(words.length / 2);
  return [words.slice(0, mid).join(" "), words.slice(mid).join(" ")];
}
