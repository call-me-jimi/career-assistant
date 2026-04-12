export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  text: string;
  timestamp: number;
};

export type ActionLine = {
  id: string;
  action: string;
  label: string;
  status: "running" | "ok" | "error";
  timestamp: number;
};

export type LLMCard = {
  cardId: string;
  task?: string;
  provider?: string;
  model?: string;
  startedAt: number;
  endedAt?: number;
  durationMs?: number;
  inputTokens?: number;
  outputTokens?: number;
  status: "running" | "ok" | "error";
  error?: string;
};

export type InterruptPayload = {
  kind: string;
  [key: string]: any;
};

export type ServerEvent =
  | { type: "chat.message"; message_id: string; role: "assistant" | "user"; text: string; timestamp: number }
  | { type: "action.start"; action_id: string; action: string; label: string; timestamp: number }
  | { type: "action.finish"; action_id: string; status: "ok" | "error"; timestamp: number }
  | {
      type: "llm.start";
      card_id: string;
      task?: string;
      provider?: string;
      model?: string;
      timestamp: number;
    }
  | {
      type: "llm.end";
      card_id: string;
      duration_ms: number;
      input_tokens: number;
      output_tokens: number;
      task?: string;
      provider?: string;
      model?: string;
      timestamp: number;
    }
  | {
      type: "llm.error";
      card_id: string;
      error: string;
      timestamp: number;
    }
  | { type: "interrupt.request"; payload: InterruptPayload }
  | { type: "state.update"; patch: Record<string, any> }
  | { type: "export.ready"; kind: string; path: string }
  | { type: "session.complete" }
  | { type: "session.error"; error: string };
