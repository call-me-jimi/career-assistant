"use client";

import { useEffect, useRef, useState } from "react";
import type { InterruptPayload } from "../lib/types";
import { API_BASE } from "../lib/ws";
import MicButton from "./MicButton";
import RecordInterviewHelp from "./RecordInterviewHelp";

const VOICE_PROMPT_KINDS = new Set([
  "mock_interview",
  "qa_menu",
  "cl_review",
  "interview_review",
  "evaluator_review",
  "evaluator_context",
  "interview_tech_topic",
  "ask_name",
]);

function supportsVoiceInput(kind?: string): boolean {
  return !!kind && VOICE_PROMPT_KINDS.has(kind);
}

type Props = {
  pending: InterruptPayload | null;
  onSend: (value: unknown) => void;
  onUserMessage: (text: string) => void;
  disabled?: boolean;
  sessionId?: string;
};

type QuickReply = {
  label: string;
  value: string;
};

function quickRepliesFor(kind?: string): QuickReply[] {
  switch (kind) {
    case "confirm_info":
      return [{ label: "Yes, looks good", value: "yes" }];
    case "classify_flow":
      return [
        { label: "Direct", value: "direct" },
        { label: "Recruiter", value: "recruiter" },
      ];
    case "cl_review":
      return [{ label: "Accept", value: "accept" }];
    case "interview_review":
      return [{ label: "Accept", value: "accept" }];
    case "evaluator_review":
      return [
        { label: "Accept", value: "accept" },
        { label: "Retry", value: "retry" },
      ];
    case "interview_menu":
      return [
        { label: "Mock interview", value: "mock" },
        { label: "Practice common Qs", value: "practice" },
        { label: "Tech deep-dive", value: "tech" },
        { label: "Questions to ask", value: "questions" },
        { label: "Done", value: "done" },
      ];
    case "mock_interview":
      return [
        { label: "Next question", value: "next" },
        { label: "Different topic", value: "different" },
        { label: "Done", value: "done" },
      ];
    case "interview_tech_topic":
      return [{ label: "Pick from JD", value: "pick" }];
    case "qa_menu":
      return [
        { label: "Motivation", value: "motivation" },
        { label: "Salary", value: "salary" },
        { label: "Experience", value: "experience" },
        { label: "Done", value: "done" },
      ];
    case "export_delivery":
      return [
        { label: "Download", value: "download" },
        { label: "Folder", value: "folder" },
        { label: "Both", value: "both" },
      ];
    case "export_choice":
      return [
        { label: "All", value: "all" },
        { label: "PDF", value: "pdf" },
        { label: "Markdown", value: "md" },
        { label: "JSON", value: "json" },
        { label: "Google Sheets", value: "sheets" },
        { label: "None", value: "none" },
      ];
    case "language_switch":
      return [
        { label: "Yes, switch", value: "yes" },
        { label: "No, keep current", value: "no" },
      ];
    case "post_export":
      return [
        { label: "Yes", value: "yes" },
        { label: "No, all done", value: "no" },
      ];
    default:
      return [];
  }
}

export default function InputBar({
  pending,
  onSend,
  onUserMessage,
  disabled,
  sessionId,
}: Props) {
  const [text, setText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const audioFileRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const kind = pending?.kind;

  function handleTranscript(transcript: string) {
    setText((prev) => (prev ? `${prev} ${transcript}` : transcript));
    textareaRef.current?.focus();
  }

  useEffect(() => {
    if (
      pending &&
      !disabled &&
      kind !== "upload_cv" &&
      kind !== "upload_interview_audio"
    ) {
      textareaRef.current?.focus();
    }
  }, [pending, disabled, kind]);

  async function handleUpload(file: File) {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_BASE}/api/uploads/cv`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      onUserMessage(`Uploaded ${file.name} (${data.chars} chars).`);
      onSend({ cv_text: data.cv_text });
    } finally {
      setUploading(false);
    }
  }

  async function handleAudioUpload(file: File) {
    if (!sessionId) {
      setUploadError("Session id missing — refresh the page.");
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      const fd = new FormData();
      fd.append("session_id", sessionId);
      fd.append("file", file);
      const res = await fetch(`${API_BASE}/api/uploads/interview-audio`, {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const mb = (data.size_bytes / (1024 * 1024)).toFixed(1);
      onUserMessage(`Uploaded ${file.name} (${mb} MB).`);
      onSend({ audio_path: data.audio_path, filename: data.filename });
    } catch (e: any) {
      setUploadError(e?.message || String(e));
    } finally {
      setUploading(false);
    }
  }

  function submitText(override?: string) {
    const trimmed = (override ?? text).trim();
    if (!trimmed) return;
    onUserMessage(trimmed);

    let value: unknown = trimmed;
    if (kind === "collect_job") {
      value = /^https?:\/\//i.test(trimmed)
        ? { url: trimmed }
        : { text: trimmed };
    } else if (kind === "collect_job_text") {
      value = { text: trimmed };
    } else if (kind === "confirm_info") {
      if (["yes", "y", "ok"].includes(trimmed.toLowerCase())) {
        value = "yes";
      } else {
        const patch: Record<string, string> = {};
        trimmed.split("\n").forEach((line) => {
          const m = line.match(/^\s*([a-z_]+)\s*:\s*(.+)$/i);
          if (m) patch[m[1].toLowerCase()] = m[2].trim();
        });
        value = Object.keys(patch).length ? patch : trimmed;
      }
    }
    onSend(value);
    setText("");
  }

  if (kind === "upload_cv") {
    return (
      <div className="border-t border-border p-4 flex items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);
          }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading || disabled}
          className="px-5 py-3 rounded-xl bg-accent text-bg font-medium disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload CV (PDF)"}
        </button>
        <button
          onClick={() => onSend({})}
          className="px-4 py-3 rounded-xl border border-border text-subtle"
        >
          Skip
        </button>
      </div>
    );
  }

  if (kind === "upload_interview_audio") {
    return (
      <div className="border-t border-border p-4 space-y-2">
        <div className="flex items-center gap-3">
          <input
            ref={audioFileRef}
            type="file"
            accept="audio/*,video/mp4,video/webm"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleAudioUpload(f);
            }}
          />
          <button
            onClick={() => audioFileRef.current?.click()}
            disabled={uploading || disabled}
            className="px-5 py-3 rounded-xl bg-accent text-bg font-medium disabled:opacity-50"
          >
            {uploading ? "Uploading…" : "Upload interview recording"}
          </button>
          <RecordInterviewHelp />
        </div>
        {uploadError && (
          <p className="text-xs text-err">Upload failed: {uploadError}</p>
        )}
      </div>
    );
  }

  const quickReplies = pending && !disabled ? quickRepliesFor(kind) : [];
  const showVoice = supportsVoiceInput(kind) && !disabled;

  return (
    <div className="border-t border-border p-4 space-y-2">
      <div className="flex gap-3">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submitText();
            }
          }}
          disabled={disabled || !pending}
          placeholder={
            !pending
              ? "Waiting for the assistant…"
              : placeholderFor(kind)
          }
          rows={2}
          className="flex-1 rounded-xl bg-panel border border-border p-3 text-text placeholder:text-subtle focus:outline-none focus:border-accent resize-none"
        />
        {showVoice && (
          <MicButton
            sessionId={sessionId}
            disabled={disabled || !pending}
            onTranscript={handleTranscript}
            onError={setVoiceError}
          />
        )}
        <button
          onClick={() => submitText()}
          disabled={disabled || !pending || !text.trim()}
          className="px-5 py-3 rounded-xl bg-accent text-bg font-medium disabled:opacity-50"
        >
          Send
        </button>
      </div>
      {voiceError && (
        <p className="text-xs text-err">Voice input: {voiceError}</p>
      )}
      {quickReplies.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-subtle">Quick reply:</span>
          {quickReplies.map((qr) => (
            <button
              key={qr.value}
              onClick={() => submitText(qr.value)}
              className="px-3 py-1.5 rounded-lg border border-accent/30 bg-accent/5 text-sm text-accent hover:bg-accent/15 hover:border-accent transition-colors"
            >
              {qr.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function placeholderFor(kind?: string): string {
  switch (kind) {
    case "ask_name":
      return "Your name…";
    case "collect_job":
    case "collect_job_text":
      return "Paste a job URL or the full job description…";
    case "ask_field:job_title":
      return "e.g. Senior Backend Engineer";
    case "ask_field:company_name":
      return "e.g. Acme Corp";
    case "confirm_info":
      return "yes — or corrections like `company: Acme`";
    case "classify_flow":
      return "direct or recruiter";
    case "cl_review":
      return "accept, or describe revisions…";
    case "interview_review":
      return "accept, or describe revisions to the briefing…";
    case "evaluator_context":
      return "round / format / focus areas — or `none`";
    case "evaluator_review":
      return "accept, retry, or describe revisions to the report…";
    case "interview_menu":
      return "mock / practice / tech / questions / done";
    case "mock_interview":
      return "type your answer, or `next` / `different` / `done`";
    case "interview_tech_topic":
      return "topic name, or `pick` to let me choose";
    case "qa_menu":
      return "motivation / salary / experience / custom question / done";
    case "export_delivery":
      return "download / folder / both";
    case "export_choice":
      return "pdf md json sheets — or `all` / `none`";
    default:
      return "Your reply…";
  }
}
