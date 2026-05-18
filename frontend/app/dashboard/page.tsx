"use client";

import { useEffect, useState } from "react";

type AssistantStats = {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
};

type StatsResponse = {
  sessions_by_type: Record<string, number>;
  totals: {
    sessions: number;
    llm_calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
  };
  by_assistant_type: Record<string, AssistantStats>;
};

const ASSISTANT_LABELS: Record<string, string> = {
  cover_letter: "Cover Letter",
  interview_prep: "Interview Prep",
  career_advisor: "Career Advisor",
};

const ASSISTANT_ORDER = ["cover_letter", "interview_prep", "career_advisor"];

function fmtCost(n: number): string {
  if (n === 0) return "—";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(3)}`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
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

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch((e) => setError(`Could not load stats: ${e}`));
  }, []);

  if (error) return <main className="p-8 text-err">{error}</main>;
  if (!stats) return <main className="p-8 text-subtle">Loading…</main>;

  const { totals, sessions_by_type, by_assistant_type } = stats;

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="font-semibold">Dashboard</div>
        <a href="/" className="text-xs text-accent hover:underline">← Home</a>
      </header>

      <div className="max-w-3xl mx-auto p-6 space-y-8">
        <p className="text-sm text-subtle">
          Aggregate usage across all sessions — how often you've used each assistant, total LLM
          calls, tokens consumed, and estimated cost.
        </p>

        {/* Assistant session counts */}
        <Section title="Sessions by assistant">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {ASSISTANT_ORDER.map((type) => (
              <div
                key={type}
                className="rounded-xl border border-border bg-panel p-5 flex flex-col gap-2"
              >
                <div className="text-sm text-subtle">{ASSISTANT_LABELS[type] ?? type}</div>
                <div className="text-4xl font-semibold">{sessions_by_type[type] ?? 0}</div>
                <div className="text-xs text-subtle">sessions</div>
              </div>
            ))}
          </div>
        </Section>

        {/* Global totals */}
        <Section title="Overall">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Stat label="Sessions" value={String(totals.sessions)} />
            <Stat label="LLM calls" value={String(totals.llm_calls)} />
            <Stat label="Input tokens" value={fmtTokens(totals.input_tokens)} />
            <Stat label="Output tokens" value={fmtTokens(totals.output_tokens)} />
            <Stat label="Total cost" value={fmtCost(totals.cost_usd)} />
          </div>
        </Section>

        {/* Cost breakdown by assistant */}
        <Section title="Cost by assistant">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-subtle text-xs">
                <tr>
                  <th className="text-left py-1">Assistant</th>
                  <th className="text-right py-1">Sessions</th>
                  <th className="text-right py-1">LLM calls</th>
                  <th className="text-right py-1">Input tokens</th>
                  <th className="text-right py-1">Output tokens</th>
                  <th className="text-right py-1">Cost</th>
                </tr>
              </thead>
              <tbody>
                {ASSISTANT_ORDER.map((type) => {
                  const s = by_assistant_type[type] ?? {
                    llm_calls: 0,
                    input_tokens: 0,
                    output_tokens: 0,
                    cost_usd: 0,
                  };
                  return (
                    <tr key={type} className="border-t border-border">
                      <td className="py-2">{ASSISTANT_LABELS[type] ?? type}</td>
                      <td className="py-2 text-right">{sessions_by_type[type] ?? 0}</td>
                      <td className="py-2 text-right">{s.llm_calls}</td>
                      <td className="py-2 text-right">{fmtTokens(s.input_tokens)}</td>
                      <td className="py-2 text-right">{fmtTokens(s.output_tokens)}</td>
                      <td className="py-2 text-right">{fmtCost(s.cost_usd)}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="text-subtle text-xs font-semibold">
                <tr className="border-t-2 border-border">
                  <td className="py-2">Total</td>
                  <td className="py-2 text-right">{totals.sessions}</td>
                  <td className="py-2 text-right">{totals.llm_calls}</td>
                  <td className="py-2 text-right">{fmtTokens(totals.input_tokens)}</td>
                  <td className="py-2 text-right">{fmtTokens(totals.output_tokens)}</td>
                  <td className="py-2 text-right">{fmtCost(totals.cost_usd)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </Section>
      </div>
    </main>
  );
}
