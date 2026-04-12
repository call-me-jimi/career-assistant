"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

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

function fmtTokens(n: number): string {
  return n.toLocaleString();
}

function UsageView() {
  const params = useSearchParams();
  const sessionId = params.get("id") || "";
  const [traces, setTraces] = useState<Trace[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    fetch(`/api/sessions/${sessionId}/traces`)
      .then((r) => r.json())
      .then((data) => {
        setTraces(data.traces || []);
        setLoaded(true);
      })
      .catch((e) => setError(`Could not load traces: ${e}`));
  }, [sessionId]);

  const totals = useMemo(() => {
    let calls = 0,
      inTok = 0,
      outTok = 0,
      ms = 0,
      cost = 0;
    for (const t of traces) {
      calls += 1;
      inTok += t.input_tokens;
      outTok += t.output_tokens;
      ms += t.duration_ms;
      cost += t.cost_usd;
    }
    return { calls, inTok, outTok, ms, cost };
  }, [traces]);

  const byTask = useMemo(() => groupBy(traces, (t) => taskLabel(t.task)), [traces]);
  const byModel = useMemo(() => groupBy(traces, (t) => t.model || "(unknown)"), [traces]);

  if (!sessionId) return <main className="p-8 text-subtle">Missing session id.</main>;
  if (error) return <main className="p-8 text-err">{error}</main>;
  if (!loaded) return <main className="p-8 text-subtle">Loading usage…</main>;

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="font-semibold">Session usage</div>
        <a href={`/session?id=${sessionId}`} className="text-xs text-accent hover:underline">
          ← Back to chat
        </a>
      </header>
      <div className="max-w-4xl mx-auto p-6 space-y-8">
        <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Stat label="LLM calls" value={String(totals.calls)} />
          <Stat label="Input tokens" value={fmtTokens(totals.inTok)} />
          <Stat label="Output tokens" value={fmtTokens(totals.outTok)} />
          <Stat label="LLM time" value={`${(totals.ms / 1000).toFixed(1)}s`} />
          <Stat label="Total cost" value={fmtCost(totals.cost)} />
        </section>

        <Section title="By task">
          <BreakdownTable rows={byTask} />
        </Section>

        <Section title="By model">
          <BreakdownTable rows={byModel} />
        </Section>

        <Section title="All calls">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-subtle text-xs">
                <tr>
                  <th className="text-left py-1">time</th>
                  <th className="text-left py-1">task</th>
                  <th className="text-left py-1">model</th>
                  <th className="text-right py-1">in</th>
                  <th className="text-right py-1">out</th>
                  <th className="text-right py-1">dur</th>
                  <th className="text-right py-1">cost</th>
                </tr>
              </thead>
              <tbody>
                {traces.map((t) => (
                  <tr key={t.card_id} className="border-t border-border">
                    <td className="py-1 text-xs text-subtle">
                      {new Date(t.created_at * 1000).toLocaleTimeString()}
                    </td>
                    <td className="py-1">{taskLabel(t.task)}</td>
                    <td className="py-1 text-xs text-subtle">{t.model}</td>
                    <td className="py-1 text-right">{fmtTokens(t.input_tokens)}</td>
                    <td className="py-1 text-right">{fmtTokens(t.output_tokens)}</td>
                    <td className="py-1 text-right">{(t.duration_ms / 1000).toFixed(2)}s</td>
                    <td className="py-1 text-right">{fmtCost(t.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-panel p-3">
      <div className="text-xs uppercase tracking-widest text-subtle">{label}</div>
      <div className="text-lg font-semibold mt-1">{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

type GroupRow = {
  key: string;
  calls: number;
  inTok: number;
  outTok: number;
  ms: number;
  cost: number;
};

function groupBy(traces: Trace[], keyFn: (t: Trace) => string): GroupRow[] {
  const map = new Map<string, GroupRow>();
  for (const t of traces) {
    const k = keyFn(t);
    const r = map.get(k) || { key: k, calls: 0, inTok: 0, outTok: 0, ms: 0, cost: 0 };
    r.calls += 1;
    r.inTok += t.input_tokens;
    r.outTok += t.output_tokens;
    r.ms += t.duration_ms;
    r.cost += t.cost_usd;
    map.set(k, r);
  }
  return [...map.values()].sort((a, b) => b.cost - a.cost);
}

function BreakdownTable({ rows }: { rows: GroupRow[] }) {
  if (rows.length === 0) return <div className="text-sm text-subtle">No data yet.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-subtle text-xs">
          <tr>
            <th className="text-left py-1"> </th>
            <th className="text-right py-1">calls</th>
            <th className="text-right py-1">in</th>
            <th className="text-right py-1">out</th>
            <th className="text-right py-1">dur</th>
            <th className="text-right py-1">cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border">
              <td className="py-1">{r.key}</td>
              <td className="py-1 text-right">{r.calls}</td>
              <td className="py-1 text-right">{fmtTokens(r.inTok)}</td>
              <td className="py-1 text-right">{fmtTokens(r.outTok)}</td>
              <td className="py-1 text-right">{(r.ms / 1000).toFixed(1)}s</td>
              <td className="py-1 text-right">{fmtCost(r.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function UsagePage() {
  return (
    <Suspense fallback={<main className="p-8 text-subtle">Loading…</main>}>
      <UsageView />
    </Suspense>
  );
}
