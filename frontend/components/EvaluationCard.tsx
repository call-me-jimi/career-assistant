"use client";

import { useState } from "react";
import type { InterviewEvaluation } from "../lib/types";

const DECISION_STYLES: Record<string, string> = {
  YES: "bg-ok/20 text-ok border-ok/40",
  MAYBE: "bg-warn/20 text-warn border-warn/40",
  NO: "bg-err/20 text-err border-err/40",
};

const PACE_LABELS: Record<string, string> = {
  too_fast: "Too fast",
  appropriate: "Appropriate",
  too_slow: "Too slow",
};

type Props = {
  evaluation: InterviewEvaluation | null;
};

export default function EvaluationCard({ evaluation }: Props) {
  const [openQ, setOpenQ] = useState<number | null>(0);

  if (!evaluation) {
    return (
      <div className="h-full flex items-center justify-center p-6 text-sm text-subtle text-center">
        Once the recording is transcribed and analysed, your structured
        performance report will appear here.
      </div>
    );
  }

  const decisionClass =
    DECISION_STYLES[evaluation.decision] || "bg-panel border-border text-text";
  const score = Number(evaluation.overall_score ?? 0).toFixed(1);

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div className="flex items-center gap-3">
        <div
          className={`px-3 py-1 rounded-full border text-xs font-semibold ${decisionClass}`}
        >
          {evaluation.decision}
        </div>
        <div className="text-2xl font-semibold">{score}/10</div>
      </div>

      {evaluation.summary && (
        <p className="text-sm leading-relaxed text-text">
          {evaluation.summary}
        </p>
      )}

      <Section title="Strengths" items={evaluation.strengths} variant="ok" />
      <Section
        title="Weaknesses"
        items={evaluation.weaknesses}
        variant="warn"
      />
      <Section
        title="Points to improve"
        items={evaluation.improvements}
        variant="accent"
      />

      <div className="rounded-xl border border-border p-3 space-y-1 text-sm">
        <div className="font-semibold text-subtle text-xs uppercase tracking-wide">
          Communication
        </div>
        <div>
          <span className="text-subtle">Pace:</span>{" "}
          {PACE_LABELS[evaluation.communication?.pace] ??
            evaluation.communication?.pace ??
            "—"}
        </div>
        <div>
          <span className="text-subtle">Filler words:</span>{" "}
          {evaluation.communication?.filler_words?.length
            ? evaluation.communication.filler_words.join(", ")
            : "(none observed)"}
        </div>
        {evaluation.communication?.clarity && (
          <div>
            <span className="text-subtle">Clarity:</span>{" "}
            {evaluation.communication.clarity}
          </div>
        )}
        {evaluation.communication?.structure && (
          <div>
            <span className="text-subtle">Structure:</span>{" "}
            {evaluation.communication.structure}
          </div>
        )}
      </div>

      {evaluation.per_question && evaluation.per_question.length > 0 && (
        <div className="space-y-2">
          <div className="font-semibold text-subtle text-xs uppercase tracking-wide">
            Per-question breakdown
          </div>
          {evaluation.per_question.map((q, i) => {
            const isOpen = openQ === i;
            return (
              <div
                key={i}
                className="rounded-xl border border-border overflow-hidden"
              >
                <button
                  onClick={() => setOpenQ(isOpen ? null : i)}
                  className="w-full px-3 py-2 text-left text-sm flex items-center justify-between hover:bg-panel/70"
                >
                  <span className="font-medium pr-2">
                    Q{i + 1}. {q.question}
                  </span>
                  <span className="text-subtle text-xs">
                    {isOpen ? "▾" : "▸"}
                  </span>
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 space-y-2 text-sm border-t border-border">
                    {q.answer_summary && (
                      <p className="text-subtle">
                        <span className="font-semibold text-text">Answer:</span>{" "}
                        {q.answer_summary}
                      </p>
                    )}
                    {q.strengths?.length > 0 && (
                      <p>
                        <span className="text-ok font-semibold">+ </span>
                        {q.strengths.join("; ")}
                      </p>
                    )}
                    {q.weaknesses?.length > 0 && (
                      <p>
                        <span className="text-warn font-semibold">- </span>
                        {q.weaknesses.join("; ")}
                      </p>
                    )}
                    {q.suggested_improvement && (
                      <p className="text-accent">
                        → {q.suggested_improvement}
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  items,
  variant,
}: {
  title: string;
  items: string[] | undefined;
  variant: "ok" | "warn" | "accent";
}) {
  if (!items || items.length === 0) return null;
  const bullet = { ok: "text-ok", warn: "text-warn", accent: "text-accent" }[
    variant
  ];
  return (
    <div>
      <div className="font-semibold text-subtle text-xs uppercase tracking-wide mb-1">
        {title}
      </div>
      <ul className="space-y-1 text-sm">
        {items.map((x, i) => (
          <li key={i} className="flex gap-2">
            <span className={`${bullet} font-semibold`}>•</span>
            <span>{x}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
