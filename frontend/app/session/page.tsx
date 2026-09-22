"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import ChatPane from "../../components/ChatPane";
import InputBar from "../../components/InputBar";
import LLMCardPane from "../../components/LLMCardPane";
import Brand from "../../components/Brand";
import type {
  ActionLine,
  ChatMessage,
  DownloadLine,
  InterruptPayload,
  InterviewEvaluation,
  LLMCard,
  ServerEvent,
} from "../../lib/types";
import { connectSession } from "../../lib/ws";

const ASSISTANT_LABELS: Record<string, string> = {
  cover_letter: "Cover Letter",
  interview_prep: "Interview Prep",
  career_advisor: "Career Advisor",
  interview_evaluator: "Interview Evaluator",
};

function SessionView() {
  const params = useSearchParams();
  const sessionId = params.get("id") || "";
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [actions, setActions] = useState<ActionLine[]>([]);
  const [cards, setCards] = useState<LLMCard[]>([]);
  const [downloads, setDownloads] = useState<DownloadLine[]>([]);
  const [pending, setPending] = useState<InterruptPayload | null>(null);
  const [done, setDone] = useState(false);
  const [assistantType, setAssistantType] = useState<string>("");
  const [language, setLanguage] = useState<string>("");
  const [evaluationEntry, setEvaluationEntry] = useState<{
    timestamp: number;
    data: InterviewEvaluation;
  } | null>(null);
  const sendRef = useRef<(v: unknown) => void>(() => {});

  useEffect(() => {
    if (!sessionId) return;
    const conn = connectSession(sessionId, handleEvent);
    sendRef.current = conn.send;
    fetch(`/api/sessions/${sessionId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        setAssistantType(data.assistant_type || "");
        // Creation value. The graph can move off it later (language_switch, or a
        // Details edit), and both broadcast state.update so this stays current.
        setLanguage(data.language || "");
      })
      .catch(() => {});
    return () => conn.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  function handleEvent(ev: ServerEvent) {
    switch (ev.type) {
      case "chat.message":
        setMessages((prev) => [
          ...prev,
          {
            id: ev.message_id,
            role: ev.role,
            text: ev.text,
            timestamp: ev.timestamp,
          },
        ]);
        break;
      case "action.start":
        setActions((prev) => [
          ...prev,
          {
            id: ev.action_id,
            action: ev.action,
            label: ev.label,
            status: "running",
            timestamp: ev.timestamp,
          },
        ]);
        break;
      case "action.finish":
        setActions((prev) =>
          prev.map((a) =>
            a.id === ev.action_id ? { ...a, status: ev.status } : a,
          ),
        );
        break;
      case "llm.start":
        setCards((prev) => [
          ...prev,
          {
            cardId: ev.card_id,
            task: ev.task,
            provider: ev.provider,
            model: ev.model,
            startedAt: ev.timestamp,
            status: "running",
          },
        ]);
        break;
      case "llm.end":
        setCards((prev) =>
          prev.map((c) =>
            c.cardId === ev.card_id
              ? {
                  ...c,
                  endedAt: ev.timestamp,
                  durationMs: ev.duration_ms,
                  inputTokens: ev.input_tokens,
                  outputTokens: ev.output_tokens,
                  task: ev.task ?? c.task,
                  provider: ev.provider ?? c.provider,
                  model: ev.model ?? c.model,
                  status: "ok",
                }
              : c,
          ),
        );
        break;
      case "llm.error":
        setCards((prev) =>
          prev.map((c) =>
            c.cardId === ev.card_id ? { ...c, status: "error", error: ev.error } : c,
          ),
        );
        break;
      case "interrupt.request":
        setPending(ev.payload);
        break;
      case "state.update":
        if (ev.patch && typeof ev.patch.language === "string" && ev.patch.language) {
          setLanguage(ev.patch.language);
        }
        if (ev.patch && "interview_evaluation" in ev.patch && ev.patch.interview_evaluation) {
          setEvaluationEntry((prev) => ({
            timestamp: prev?.timestamp ?? Date.now() / 1000,
            data: ev.patch.interview_evaluation,
          }));
        }
        break;
      case "export.ready": {
        const filename = ev.path.split("/").pop() || `${ev.kind}.${ev.kind === "md" ? "md" : ev.kind}`;
        setDownloads((prev) => [
          ...prev,
          {
            id: `dl-${ev.timestamp}-${ev.kind}`,
            sessionId: sessionId,
            kind: ev.kind,
            filename,
            timestamp: ev.timestamp,
          },
        ]);
        break;
      }
      case "session.complete":
        setPending(null);
        setDone(true);
        break;
      case "session.error":
        setDone(true);
        break;
    }
  }

  const header = useMemo(
    () => (
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-4">
          <Brand
            onClick={(e) => {
              if (!done && !confirm("Leaving will end this session. Continue?")) {
                e.preventDefault();
              }
            }}
          />
          {assistantType && ASSISTANT_LABELS[assistantType] && (
            <>
              <span className="h-5 w-px bg-border" />
              <span className="px-2 py-0.5 text-xs rounded-full border border-accent/40 text-accent">
                {ASSISTANT_LABELS[assistantType]}
              </span>
            </>
          )}
          {language && (
            <span
              className="text-xs text-subtle"
              title="Output language for this session. To change it, open Details while the assistant is waiting for your input."
            >
              {language}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 text-xs">
          <a
            href={`/session/details?id=${sessionId}`}
            className="text-accent hover:underline"
          >
            Details
          </a>
          <a
            href={`/session/graph?id=${sessionId}`}
            className="text-accent hover:underline"
          >
            Graph
          </a>
          <a
            href={`/settings?from=${encodeURIComponent(`/session?id=${sessionId}`)}`}
            className="text-accent hover:underline"
          >
            Settings
          </a>
          <a
            href={`/session/usage?id=${sessionId}`}
            className="text-subtle hover:text-accent"
          >
            session: {sessionId.slice(0, 8)}
          </a>
        </div>
      </header>
    ),
    [sessionId, done, assistantType, language],
  );

  return (
    <main className="h-screen flex flex-col">
      {header}
      <div className="flex-1 grid grid-cols-[2fr_1fr] overflow-hidden">
        <section className="flex flex-col overflow-hidden">
          <ChatPane messages={messages} actions={actions} downloads={downloads} evaluationEntry={evaluationEntry} />
          <InputBar
            pending={pending}
            disabled={done}
            sessionId={sessionId}
            onSend={(value) => {
              sendRef.current(value);
              setPending(null);
            }}
            onUserMessage={(text) =>
              setMessages((prev) => [
                ...prev,
                {
                  id: `user-${Date.now()}`,
                  role: "user",
                  text,
                  timestamp: Date.now() / 1000,
                },
              ])
            }
          />
        </section>
        <LLMCardPane cards={cards} sessionId={sessionId} />
      </div>
    </main>
  );
}

export default function SessionPage() {
  return (
    <Suspense fallback={<div className="p-8 text-subtle">Loading session…</div>}>
      <SessionView />
    </Suspense>
  );
}
