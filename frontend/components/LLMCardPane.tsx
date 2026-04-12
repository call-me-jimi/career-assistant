"use client";

import { useEffect, useState } from "react";
import type { LLMCard } from "../lib/types";

type TraceDetail = {
  card_id: string;
  task: string | null;
  provider: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  cost_usd: number;
  system_prompt: string;
  user_prompt: string;
  response_text: string;
  created_at: number;
};

/** Map internal task keys to human-readable labels. */
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
  if (!task) return "LLM call";
  return TASK_LABELS[task] ?? task.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function LLMCardPane({
  cards,
  sessionId,
}: {
  cards: LLMCard[];
  sessionId: string;
}) {
  const [activeCardId, setActiveCardId] = useState<string | null>(null);
  return (
    <aside className="h-full overflow-y-auto border-l border-border bg-panel2/60 p-4 space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-subtle mb-3">
        LLM interactions
      </h2>
      {cards.length === 0 && (
        <div className="text-sm text-subtle">
          LLM calls will appear here as they run.
        </div>
      )}
      {cards.map((c) => (
        <Card
          key={c.cardId}
          c={c}
          onClick={() => c.status !== "running" && setActiveCardId(c.cardId)}
        />
      ))}
      {activeCardId && (
        <DetailModal
          sessionId={sessionId}
          cardId={activeCardId}
          onClose={() => setActiveCardId(null)}
        />
      )}
    </aside>
  );
}

function Card({ c, onClick }: { c: LLMCard; onClick: () => void }) {
  const running = c.status === "running";
  const time = new Date(c.startedAt * 1000).toLocaleTimeString();
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border border-border bg-panel p-3 text-sm ${
        running ? "" : "cursor-pointer hover:border-accent"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-subtle text-xs">{time}</span>
        {running ? (
          <Spinner />
        ) : c.status === "ok" ? (
          <span className="text-ok text-xs">✓</span>
        ) : (
          <span className="text-err text-xs">✗</span>
        )}
      </div>
      <div className="mt-1 font-medium truncate">{taskLabel(c.task)}</div>
      <div className="text-xs text-subtle truncate">
        {c.provider || ""} · {c.model || "…"}
      </div>
      {!running && (
        <div className="mt-2 grid grid-cols-3 gap-1 text-xs text-subtle">
          <span>
            in <span className="text-text">{c.inputTokens ?? 0}</span>
          </span>
          <span>
            out <span className="text-text">{c.outputTokens ?? 0}</span>
          </span>
          <span>
            <span className="text-text">
              {c.durationMs ? (c.durationMs / 1000).toFixed(2) : "—"}
            </span>
            s
          </span>
        </div>
      )}
      {c.error && <div className="mt-2 text-xs text-err">{c.error}</div>}
    </div>
  );
}

function DetailModal({
  sessionId,
  cardId,
  onClose,
}: {
  sessionId: string;
  cardId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`/api/sessions/${sessionId}/traces/${cardId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setDetail)
      .catch((e) => setError(String(e)));
  }, [sessionId, cardId]);

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-panel border border-border rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto p-6 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">LLM call detail</h3>
          <button onClick={onClose} className="text-subtle hover:text-text">
            ✕
          </button>
        </div>
        {error && <div className="text-err text-sm">{error}</div>}
        {!detail && !error && <div className="text-subtle text-sm">Loading…</div>}
        {detail && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <Meta label="Task" value={taskLabel(detail.task)} />
              <Meta label="Model" value={detail.model || "—"} />
              <Meta label="Provider" value={detail.provider || "—"} />
              <Meta label="Cost" value={detail.cost_usd ? `$${detail.cost_usd.toFixed(4)}` : "—"} />
              <Meta label="Input tokens" value={detail.input_tokens.toLocaleString()} />
              <Meta label="Output tokens" value={detail.output_tokens.toLocaleString()} />
              <Meta label="Duration" value={`${(detail.duration_ms / 1000).toFixed(2)}s`} />
              <Meta label="Time" value={new Date(detail.created_at * 1000).toLocaleTimeString()} />
            </div>
            <PromptBlock title="System prompt" text={detail.system_prompt} />
            <PromptBlock title="User prompt" text={detail.user_prompt} />
            <PromptBlock title="Response" text={detail.response_text} />
          </>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest text-subtle">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function PromptBlock({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest text-subtle mb-1">{title}</div>
      <pre className="bg-panel2 border border-border rounded-lg p-3 text-xs whitespace-pre-wrap font-mono max-h-72 overflow-y-auto">
        {text || "(empty)"}
      </pre>
    </div>
  );
}

function Spinner() {
  return (
    <span
      aria-label="loading"
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-subtle border-t-transparent"
    />
  );
}
