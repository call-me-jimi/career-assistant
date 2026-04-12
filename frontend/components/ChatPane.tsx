"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ActionLine, ChatMessage } from "../lib/types";

type Props = {
  messages: ChatMessage[];
  actions: ActionLine[];
};

export default function ChatPane({ messages, actions }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, actions.length]);

  const items = [
    ...messages.map((m) => ({ kind: "msg" as const, t: m.timestamp, value: m })),
    ...actions.map((a) => ({ kind: "action" as const, t: a.timestamp, value: a })),
  ].sort((a, b) => a.t - b.t);

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-3">
      {items.map((it) =>
        it.kind === "msg" ? (
          <Message key={`m-${it.value.id}`} m={it.value} />
        ) : (
          <Action key={`a-${it.value.id}`} a={it.value} />
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

function Spinner() {
  return (
    <span
      aria-label="loading"
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-subtle border-t-transparent"
    />
  );
}
