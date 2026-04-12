"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
});

/* ── Constants ── */

/** Ordered list of graph nodes matching graph.py topology. */
const NODE_ORDER = [
  "greeting",
  "cv_intake",
  "collect_job",
  "extract_info",
  "fill_missing_info",
  "confirm_info",
  "research_company",
  "classify_flow",
  "strategy",
  "cl_loop",
  "cl_review",
  "qa_menu",
  "qa_answer",
  "export",
];

/** Map LLM task names to the graph node that triggers them. */
const TASK_TO_NODE: Record<string, string> = {
  candidate_profile: "cv_intake",
  scrape: "collect_job",
  extract_info: "extract_info",
  extract_job_and_company_information: "extract_info",
  research_company: "research_company",
  infer_role: "strategy",
  position_candidate: "strategy",
  alignment_strategy: "strategy",
  generate_alignment_strategy: "strategy",
  cover_letter_generation: "cl_loop",
  generate_cover_letter: "cl_loop",
  simulate_hiring_manager: "cl_loop",
  compare_cover_letters: "cl_loop",
  refine_cover_letter: "cl_review",
  qa_answer: "qa_answer",
  qa: "qa_answer",
  salary_search: "qa_answer",
  chat: "qa_answer",
  export_pdf: "export",
  export_md: "export",
  export_json: "export",
  export_sheets: "export",
};

/** Nodes that use `interrupt()` for human-in-the-loop. */
const INTERRUPT_NODES = new Set([
  "greeting",
  "cv_intake",
  "collect_job",
  "fill_missing_info",
  "confirm_info",
  "classify_flow",
  "cl_review",
  "qa_menu",
  "export",
]);

/** Map graph phase value → the node that is active during that phase. */
const PHASE_TO_NODE: Record<string, string> = {
  greeting: "greeting",
  cv_intake: "cv_intake",
  collect_job: "collect_job",
  extract_info: "extract_info",
  fill_missing_info: "fill_missing_info",
  confirm_info: "confirm_info",
  research_company: "research_company",
  classify_flow: "classify_flow",
  strategy: "strategy",
  cl_loop: "cl_loop",
  cl_review: "cl_review",
  qa_menu: "qa_menu",
  qa_answer: "qa_answer",
  export: "export",
  done: "__done__",
};

/** Human-readable node labels. */
const NODE_LABELS: Record<string, string> = {
  __start__: "Start",
  __end__: "End",
  greeting: "Greeting",
  cv_intake: "CV Intake",
  collect_job: "Collect Job",
  extract_info: "Extract Info",
  fill_missing_info: "Fill Missing Info",
  confirm_info: "Confirm Info",
  research_company: "Research Company",
  classify_flow: "Classify Flow",
  strategy: "Strategy",
  cl_loop: "Cover Letter Loop",
  cl_review: "Cover Letter Review",
  qa_menu: "Q&A Menu",
  qa_answer: "Q&A Answer",
  export: "Export",
};

/** Colors per status for direct DOM application. */
const STATUS_COLORS = {
  completed: { fill: "#1a2e1a", stroke: "#4a9" },
  active: { fill: "#1a2a3a", stroke: "#5b9bd5" },
  pending: { fill: "#2d2d3d", stroke: "#555" },
} as const;

const TASK_LABELS: Record<string, string> = {
  candidate_profile: "Candidate profile",
  extract_job_and_company_information: "Extract job info",
  extract_info: "Extract job info",
  generate_alignment_strategy: "Alignment strategy",
  alignment_strategy: "Alignment strategy",
  infer_role: "Infer role",
  position_candidate: "Positioning strategy",
  cover_letter_generation: "Cover letter",
  generate_cover_letter: "Cover letter",
  simulate_hiring_manager: "Hiring manager review",
  refine_cover_letter: "Refine cover letter",
  compare_cover_letters: "Compare versions",
  research_company: "Company research",
  qa: "Q&A answer",
  qa_answer: "Q&A answer",
  salary_search: "Salary research",
  chat: "Chat",
  scrape: "Scrape job page",
};

function taskLabel(task: string | null | undefined): string {
  if (!task) return "Unknown";
  return TASK_LABELS[task] ?? task.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtCost(n: number): string {
  if (n === 0) return "—";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(3)}`;
}

/* ── Types ── */

type Trace = {
  card_id: string;
  task: string | null;
  provider: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  cost_usd: number;
  created_at: number;
};

type NodeStatus = "completed" | "active" | "pending";

type NodeStats = {
  llmCalls: number;
  inputTokens: number;
  outputTokens: number;
  totalMs: number;
  totalCost: number;
  traces: Trace[];
};

/* ── SVG patching ── */

function patchSvg(
  svg: string,
  activeNode: string | null,
  completedNodes: Set<string>,
): string {
  // 1. Remove the .default/.first/.last CSS rules that force light fills
  svg = svg.replace(/\.default\s*>\s*\*\s*\{[^}]*\}/g, "");
  svg = svg.replace(/\.default\s+span\s*\{[^}]*\}/g, "");
  svg = svg.replace(/\.first\s*>\s*\*\s*\{[^}]*\}/g, "");
  svg = svg.replace(/\.first\s+span\s*\{[^}]*\}/g, "");
  svg = svg.replace(/\.last\s*>\s*\*\s*\{[^}]*\}/g, "");
  svg = svg.replace(/\.last\s+span\s*\{[^}]*\}/g, "");

  // 2. Strip inline style fill/fill-opacity !important on shape elements
  svg = svg.replace(/style="fill:[^"]*!important[^"]*"/g, "");

  // 3. Replace fill attributes on shapes with dark color
  svg = svg.replace(/fill="#f2f0ff"/g, 'fill="#2d2d3d"');
  svg = svg.replace(/fill="#bfb6fc"/g, 'fill="#2d2d3d"');

  // 4. Inject dark theme CSS + status colors
  const darkCss = `
    .node rect, .node polygon, .node circle, .node ellipse {
      fill: #2d2d3d !important;
      stroke: #555 !important;
      transition: fill 0.2s, stroke 0.2s;
    }
    .node .label-container, .node .outer-path {
      fill: #2d2d3d !important;
      stroke: #555 !important;
    }
    .node path {
      fill: #2d2d3d !important;
      stroke: #555 !important;
    }
    .node.first path, .node.first rect {
      fill: #1a3a2a !important;
      stroke: #4a9 !important;
    }
    .node.last path, .node.last rect {
      fill: #3a1a2a !important;
      stroke: #a49 !important;
    }
    .node .label path {
      fill: none !important;
      stroke: none !important;
    }
    text, tspan {
      fill: #e0e0e0 !important;
      font-family: ui-sans-serif, system-ui, sans-serif !important;
    }
    .nodeLabel, .nodeLabel p {
      color: #e0e0e0 !important;
      font-family: ui-sans-serif, system-ui, sans-serif !important;
    }
    .edgePath path, .flowchart-link {
      stroke: #888 !important;
      fill: none !important;
    }
    marker path {
      fill: #888 !important;
      stroke: #888 !important;
    }
    .edgeLabel .labelBkg {
      background-color: transparent !important;
    }
    /* Status: completed nodes */
    .node-completed rect, .node-completed polygon, .node-completed circle, .node-completed ellipse,
    .node-completed path {
      fill: #1a2e1a !important;
      stroke: #4a9 !important;
    }
    .node-completed .label path {
      fill: none !important;
      stroke: none !important;
    }
    /* Status: active node */
    .node-active rect, .node-active polygon, .node-active circle, .node-active ellipse,
    .node-active path {
      fill: #1a2a3a !important;
      stroke: #5b9bd5 !important;
      stroke-width: 2.5px !important;
    }
    .node-active .label path {
      fill: none !important;
      stroke: none !important;
    }
    /* Clickable cursor */
    .node { cursor: pointer; }
    .node:hover rect, .node:hover polygon, .node:hover circle, .node:hover ellipse,
    .node:hover path {
      stroke-width: 2px !important;
      filter: brightness(1.2);
    }
    .node:hover .label path {
      filter: none !important;
      stroke-width: 0 !important;
    }
    /* Interrupt indicator */
    .interrupt-badge {
      font-size: 8px;
      fill: #d4a017 !important;
    }
  `;
  svg = svg.replace("</style>", darkCss + "</style>");

  return svg;
}

/** Resolve status for any node (including __start__/__end__). */
function resolveNodeStatus(
  nodeName: string,
  activeNode: string | null,
  completedNodes: Set<string>,
): NodeStatus {
  if (nodeName === "__start__") {
    // __start__ is completed once any phase is active
    return activeNode ? "completed" : "pending";
  }
  if (nodeName === "__end__") {
    return activeNode === "__done__" ? "completed" : "pending";
  }
  if (nodeName === activeNode) return "active";
  if (completedNodes.has(nodeName)) return "completed";
  return "pending";
}

/** After the SVG is in the DOM, apply status colors directly and add badges. */
function decorateNodes(
  container: HTMLDivElement,
  activeNode: string | null,
  completedNodes: Set<string>,
) {
  const svgEl = container.querySelector("svg");
  if (!svgEl) return;

  const nodeGroups = Array.from(svgEl.querySelectorAll<SVGGElement>(".node"));
  for (const g of nodeGroups) {
    const id = g.id || "";
    // Extract node name from id: "flowchart-greeting-123" → "greeting"
    const match = id.match(/flowchart-(\w+)-\d+/);
    if (!match) continue;
    const nodeName = match[1];

    // Store node name as data attribute for click handling
    g.setAttribute("data-node", nodeName);

    const status = resolveNodeStatus(nodeName, activeNode, completedNodes);
    const colors = STATUS_COLORS[status];

    // Apply fill/stroke directly to all shape elements (rect, path, polygon, circle, ellipse)
    // This overrides Mermaid's inline styles reliably
    const shapes = Array.from(
      g.querySelectorAll<SVGElement>("rect, path, polygon, circle, ellipse"),
    );
    for (const shape of shapes) {
      // Skip shapes inside .label (text underlines etc.)
      if (shape.closest(".label")) continue;
      shape.style.setProperty("fill", colors.fill, "important");
      shape.style.setProperty("stroke", colors.stroke, "important");
      if (status === "active") {
        shape.style.setProperty("stroke-width", "2.5px", "important");
      }
    }

    // Add interrupt badge
    if (INTERRUPT_NODES.has(nodeName)) {
      const bbox = g.getBBox();
      const badge = document.createElementNS("http://www.w3.org/2000/svg", "text");
      badge.setAttribute("x", String(bbox.x + bbox.width - 4));
      badge.setAttribute("y", String(bbox.y + 12));
      badge.setAttribute("class", "interrupt-badge");
      badge.setAttribute("text-anchor", "end");
      badge.textContent = "\u23F8";
      g.appendChild(badge);
    }
  }
}

/* ── Components ── */

function GraphView() {
  const params = useSearchParams();
  const sessionId = params.get("id") || "";
  const [mermaidSrc, setMermaidSrc] = useState("");
  const [phase, setPhase] = useState<string>("");
  const [error, setError] = useState("");
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Derive active node and completed set from phase
  const activeNode = useMemo(() => {
    if (!phase) return null;
    return PHASE_TO_NODE[phase] || null;
  }, [phase]);

  const completedNodes = useMemo(() => {
    const set = new Set<string>();
    if (!activeNode || activeNode === "__done__") {
      // All done
      if (activeNode === "__done__") NODE_ORDER.forEach((n) => set.add(n));
      return set;
    }
    const idx = NODE_ORDER.indexOf(activeNode);
    if (idx > 0) {
      for (let i = 0; i < idx; i++) set.add(NODE_ORDER[i]);
    }
    return set;
  }, [activeNode]);

  // Group traces by node
  const nodeStats = useMemo(() => {
    const map = new Map<string, NodeStats>();
    for (const node of NODE_ORDER) {
      map.set(node, { llmCalls: 0, inputTokens: 0, outputTokens: 0, totalMs: 0, totalCost: 0, traces: [] });
    }
    for (const t of traces) {
      const node = TASK_TO_NODE[t.task || ""];
      if (!node) continue;
      const s = map.get(node);
      if (!s) continue;
      s.llmCalls += 1;
      s.inputTokens += t.input_tokens;
      s.outputTokens += t.output_tokens;
      s.totalMs += t.duration_ms;
      s.totalCost += t.cost_usd;
      s.traces.push(t);
    }
    return map;
  }, [traces]);

  // Fetch graph source
  useEffect(() => {
    fetch("/api/graph/mermaid")
      .then((r) => r.json())
      .then((d) => setMermaidSrc(d.mermaid || ""))
      .catch((e) => setError(`Could not load graph: ${e}`));
  }, []);

  // Fetch session state + traces
  useEffect(() => {
    if (!sessionId) return;
    fetch(`/api/sessions/${sessionId}/state`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setPhase(d.phase || ""))
      .catch(() => undefined);
    fetch(`/api/sessions/${sessionId}/traces`)
      .then((r) => r.json())
      .then((d) => setTraces(d.traces || []))
      .catch(() => undefined);
  }, [sessionId]);

  // Click handler for nodes
  const handleSvgClick = useCallback((e: MouseEvent) => {
    const target = e.target as SVGElement;
    const nodeGroup = target.closest<SVGGElement>(".node[data-node]");
    if (nodeGroup) {
      const name = nodeGroup.getAttribute("data-node");
      if (name) setSelectedNode((prev) => (prev === name ? null : name));
    }
  }, []);

  // Render mermaid SVG
  useEffect(() => {
    if (!mermaidSrc || !containerRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const { svg } = await mermaid.render(`graph-${Date.now()}`, mermaidSrc);
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = patchSvg(svg, activeNode, completedNodes);
          decorateNodes(containerRef.current, activeNode, completedNodes);
          containerRef.current.addEventListener("click", handleSvgClick as EventListener);
        }
      } catch (e) {
        if (!cancelled) setError(`Could not render diagram: ${e}`);
      }
    })();
    return () => {
      cancelled = true;
      containerRef.current?.removeEventListener("click", handleSvgClick as EventListener);
    };
  }, [mermaidSrc, activeNode, completedNodes, handleSvgClick]);

  return (
    <main className="min-h-screen flex flex-col">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border shrink-0">
        <div className="font-semibold">Agent graph</div>
        <div className="flex items-center gap-4 text-xs">
          {phase && (
            <span className="text-subtle">
              current phase: <span className="text-accent">{phase}</span>
            </span>
          )}
          <a href={`/session?id=${sessionId}`} className="text-accent hover:underline">
            &larr; Back to chat
          </a>
        </div>
      </header>
      <div className="flex flex-1 min-h-0">
        {/* Graph area */}
        <div className="flex-1 p-6 space-y-4 overflow-y-auto">
          <p className="text-sm text-subtle">
            The LangGraph state machine driving this session. Click a node for details.
          </p>
          {/* Legend */}
          <div className="flex items-center gap-4 text-xs text-subtle">
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "#1a2a3a", border: "2px solid #5b9bd5" }} />
              Active
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "#1a2e1a", border: "1px solid #4a9" }} />
              Completed
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "#2d2d3d", border: "1px solid #555" }} />
              Pending
            </span>
            <span className="flex items-center gap-1">
              <span className="text-yellow-500">&#x23F8;</span>
              Interrupt point
            </span>
          </div>
          {error && <div className="text-err text-sm">{error}</div>}
          <div
            ref={containerRef}
            className="bg-panel border border-border rounded-xl p-6 overflow-x-auto"
          />
          {mermaidSrc && (
            <details className="text-xs text-subtle">
              <summary className="cursor-pointer">Mermaid source</summary>
              <pre className="mt-2 bg-panel2 border border-border rounded p-3 whitespace-pre-wrap">
                {mermaidSrc}
              </pre>
            </details>
          )}
        </div>
        {/* Detail panel — aligned with graph, shares the flex row */}
        {selectedNode && (
          <NodeDetailPanel
            nodeName={selectedNode}
            status={resolveNodeStatus(selectedNode, activeNode, completedNodes)}
            stats={nodeStats.get(selectedNode) || null}
            hasInterrupt={INTERRUPT_NODES.has(selectedNode)}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </div>
    </main>
  );
}

/* ── Detail panel ── */

function NodeDetailPanel({
  nodeName,
  status,
  stats,
  hasInterrupt,
  onClose,
}: {
  nodeName: string;
  status: NodeStatus;
  stats: NodeStats | null;
  hasInterrupt: boolean;
  onClose: () => void;
}) {
  const statusColor =
    status === "active"
      ? "text-blue-400"
      : status === "completed"
        ? "text-green-400"
        : "text-subtle";
  const statusLabel = status.charAt(0).toUpperCase() + status.slice(1);

  const isSpecial = nodeName === "__start__" || nodeName === "__end__";

  return (
    <aside className="w-[35%] min-w-[300px] border-l border-border bg-panel2/60 p-6 space-y-5 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{NODE_LABELS[nodeName] || nodeName}</h2>
        <button onClick={onClose} className="text-subtle hover:text-text text-sm">
          &times;
        </button>
      </div>

      {/* Status */}
      <div className="flex items-center gap-3">
        <div className="text-xs uppercase tracking-widest text-subtle">Status</div>
        <span className={`text-sm font-medium ${statusColor}`}>{statusLabel}</span>
      </div>

      {/* Interrupt indicator */}
      {hasInterrupt && (
        <div className="flex items-center gap-2 text-sm text-yellow-500/80">
          <span>&#x23F8;</span>
          <span>Human-in-the-loop interrupt point</span>
        </div>
      )}

      {/* LLM stats */}
      {stats && stats.llmCalls > 0 ? (
        <section className="space-y-3">
          <h3 className="text-xs uppercase tracking-widest text-subtle">LLM calls</h3>
          <div className="grid grid-cols-2 gap-3">
            <StatBox label="Calls" value={String(stats.llmCalls)} />
            <StatBox label="Cost" value={fmtCost(stats.totalCost)} />
            <StatBox label="Input tokens" value={stats.inputTokens.toLocaleString()} />
            <StatBox label="Output tokens" value={stats.outputTokens.toLocaleString()} />
            <StatBox label="Total time" value={`${(stats.totalMs / 1000).toFixed(1)}s`} />
          </div>

          {/* Individual traces */}
          <div className="space-y-2 mt-2">
            <h4 className="text-xs text-subtle">Call details</h4>
            {stats.traces.map((t) => (
              <div
                key={t.card_id}
                className="rounded-lg border border-border bg-panel p-3 text-xs space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{taskLabel(t.task)}</span>
                  <span className="text-subtle">
                    {new Date(t.created_at * 1000).toLocaleTimeString()}
                  </span>
                </div>
                <div className="text-subtle">
                  {t.model || "—"} &middot; {t.provider || "—"}
                </div>
                <div className="grid grid-cols-3 gap-1 text-subtle">
                  <span>
                    in <span className="text-text">{t.input_tokens.toLocaleString()}</span>
                  </span>
                  <span>
                    out <span className="text-text">{t.output_tokens.toLocaleString()}</span>
                  </span>
                  <span>
                    <span className="text-text">{(t.duration_ms / 1000).toFixed(2)}</span>s
                  </span>
                </div>
                {t.cost_usd > 0 && (
                  <div className="text-subtle">
                    cost <span className="text-text">{fmtCost(t.cost_usd)}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="space-y-2">
          <h3 className="text-xs uppercase tracking-widest text-subtle">LLM calls</h3>
          <div className="text-sm text-subtle">
            {status === "pending" ? "No calls yet — this node hasn't run." : "No LLM calls for this node."}
          </div>
        </section>
      )}

      {/* Node position info */}
      <section className="text-xs text-subtle space-y-1">
        <div>
          Node: <code className="text-text">{nodeName}</code>
        </div>
        {!isSpecial && (
          <div>
            Position: {NODE_ORDER.indexOf(nodeName) + 1} of {NODE_ORDER.length}
          </div>
        )}
        {isSpecial && (
          <div>{nodeName === "__start__" ? "Graph entry point" : "Graph exit point"}</div>
        )}
      </section>
    </aside>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-panel p-2">
      <div className="text-[10px] uppercase tracking-widest text-subtle">{label}</div>
      <div className="text-sm font-semibold mt-0.5">{value}</div>
    </div>
  );
}

export default function GraphPage() {
  return (
    <Suspense fallback={<main className="p-8 text-subtle">Loading&hellip;</main>}>
      <GraphView />
    </Suspense>
  );
}
