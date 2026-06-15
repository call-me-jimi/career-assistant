"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import EvaluationCard from "./EvaluationCard";
import type { ActionLine, ChatMessage, DownloadLine, InterviewEvaluation } from "../lib/types";

type Props = {
  messages: ChatMessage[];
  actions: ActionLine[];
  downloads?: DownloadLine[];
  evaluationEntry?: { timestamp: number; data: InterviewEvaluation } | null;
};

export default function ChatPane({ messages, actions, downloads = [], evaluationEntry = null }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, actions.length, downloads.length, evaluationEntry]);

  const items = [
    ...messages.map((m) => ({ kind: "msg" as const, t: m.timestamp, value: m })),
    ...actions.map((a) => ({ kind: "action" as const, t: a.timestamp, value: a })),
    ...downloads.map((d) => ({ kind: "download" as const, t: d.timestamp, value: d })),
    ...(evaluationEntry ? [{ kind: "evaluation" as const, t: evaluationEntry.timestamp, value: evaluationEntry.data }] : []),
  ].sort((a, b) => a.t - b.t);

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-3">
      {items.map((it) =>
        it.kind === "msg" ? (
          <Message key={`m-${it.value.id}`} m={it.value} />
        ) : it.kind === "action" ? (
          <Action key={`a-${it.value.id}`} a={it.value} />
        ) : it.kind === "evaluation" ? (
          <EvaluationInChat key="evaluation" evaluation={it.value} />
        ) : (
          <Download key={`d-${it.value.id}`} d={it.value} />
        ),
      )}
      <div ref={endRef} />
    </div>
  );
}

function Message({ m }: { m: ChatMessage }) {
  const mine = m.role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 border prose prose-invert prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0 prose-headings:my-2 prose-pre:my-2 prose-code:text-accent ${
          mine
            ? "bg-accent/10 border-accent/40"
            : "bg-panel border-border"
        }`}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
      </div>
    </div>
  );
}

function Action({ a }: { a: ActionLine }) {
  const color =
    a.status === "running"
      ? "text-subtle"
      : a.status === "ok"
        ? "text-ok"
        : "text-err";
  return (
    <div className={`flex items-center gap-2 text-sm ${color} pl-2`}>
      {a.status === "running" ? (
        <Spinner />
      ) : a.status === "ok" ? (
        <span>✓</span>
      ) : (
        <span>✗</span>
      )}
      <span>{a.label}</span>
    </div>
  );
}

function Download({ d }: { d: DownloadLine }) {
  const href = `/api/sessions/${d.sessionId}/exports/${d.kind}`;
  return (
    <div className="flex justify-start">
      <a
        href={href}
        download={d.filename}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-accent/40 bg-accent/10 text-accent hover:bg-accent/20 hover:border-accent text-sm"
      >
        <span>⬇</span>
        <span>Download {d.kind.toUpperCase()} — {d.filename}</span>
      </a>
    </div>
  );
}

function EvaluationInChat({ evaluation }: { evaluation: InterviewEvaluation }) {
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] rounded-2xl border border-border bg-panel px-4 py-3">
        <EvaluationCard evaluation={evaluation} />
      </div>
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
