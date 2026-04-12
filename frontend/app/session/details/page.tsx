"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

type Fields = Record<string, string>;

type CoverLetterVersion = {
  version_id: string;
  text: string;
  iteration: number;
  hm_score: number | null;
  hm_feedback: Record<string, any> | null;
};

type StateResponse = {
  session_id: string;
  phase: string;
  paused: boolean;
  fields: Fields;
  cover_letter_versions: CoverLetterVersion[];
  best_version_id: string | null;
};

type FieldDef = {
  key: string;
  label: string;
  multiline?: boolean;
  minRows?: number;
};

const FIELD_GROUPS: { title: string; fields: FieldDef[] }[] = [
  {
    title: "Applicant",
    fields: [
      { key: "applicant_name", label: "Name" },
      { key: "cv_text", label: "CV text (uploaded)", multiline: true },
      { key: "candidate_profile", label: "Candidate profile (generated)", multiline: true },
    ],
  },
  {
    title: "Job & company",
    fields: [
      { key: "job_url", label: "Job URL" },
      { key: "job_title", label: "Job title (extracted)" },
      { key: "company_name", label: "Company (extracted)" },
      { key: "location", label: "Location (extracted)" },
      { key: "job_source_type", label: "Source (direct / recruiter)" },
      { key: "job_raw_text", label: "Original job ad (scraped)", multiline: true, minRows: 10 },
      { key: "job_description", label: "Job brief (generated)", multiline: true },
      { key: "company_description", label: "Company description (generated)", multiline: true, minRows: 10 },
    ],
  },
  {
    title: "Strategy",
    fields: [
      { key: "alignment_strategy", label: "Alignment strategy (generated)", multiline: true, minRows: 10 },
      { key: "inferred_role_context", label: "Inferred role context (generated)", multiline: true, minRows: 10 },
      { key: "positioning_strategy", label: "Positioning strategy (generated)", multiline: true, minRows: 10 },
    ],
  },
];

function DetailsView() {
  const params = useSearchParams();
  const sessionId = params.get("id") || "";
  const [fields, setFields] = useState<Fields>({});
  const [originalFields, setOriginalFields] = useState<Fields>({});
  const [versions, setVersions] = useState<CoverLetterVersion[]>([]);
  const [bestVersionId, setBestVersionId] = useState<string | null>(null);
  const [phase, setPhase] = useState("");
  const [paused, setPaused] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const dirtyKeys = useMemo(() => {
    const dirty = new Set<string>();
    for (const key of Object.keys(fields)) {
      if (fields[key] !== originalFields[key]) dirty.add(key);
    }
    return dirty;
  }, [fields, originalFields]);

  const hasDirty = dirtyKeys.size > 0;

  async function reload() {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/state`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: StateResponse = await res.json();
      setFields(data.fields);
      setOriginalFields(data.fields);
      setVersions(data.cover_letter_versions || []);
      setBestVersionId(data.best_version_id);
      setPhase(data.phase);
      setPaused(data.paused);
      setLoaded(true);
      setError("");
      setStatus("");
    } catch (e: any) {
      setError(`Could not load state: ${e?.message || e}`);
    }
  }

  useEffect(() => {
    if (sessionId) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  function setField(key: string, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function save() {
    setStatus("Saving…");
    try {
      const patch: Fields = {};
      for (const key of dirtyKeys) patch[key] = fields[key];
      const res = await fetch(`/api/sessions/${sessionId}/state`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setOriginalFields({ ...fields });
      setStatus("Saved. The assistant will see the updated values on its next step.");
    } catch (e: any) {
      setStatus(`Save failed: ${e?.message || e}`);
    }
  }

  if (!sessionId) {
    return <main className="p-8 text-subtle">Missing session id.</main>;
  }
  if (!loaded) {
    return <main className="p-8 text-subtle">{error || "Loading session state…"}</main>;
  }

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="font-semibold">Session details</div>
        <div className="flex items-center gap-4 text-xs">
          <a href={`/session?id=${sessionId}`} className="text-accent hover:underline">
            ← Back to chat
          </a>
          <span className="text-subtle">phase: {phase}</span>
          <span className={paused ? "text-ok" : "text-warn"}>
            {paused ? "paused — safe to edit" : "running — edits will fail"}
          </span>
        </div>
      </header>

      <div className="max-w-4xl mx-auto p-6 space-y-8">
        {FIELD_GROUPS.map((group) => (
          <section key={group.title} className="space-y-3">
            <h2 className="text-lg font-semibold">{group.title}</h2>
            <div className="space-y-3">
              {group.fields.map((f) => {
                const dirty = dirtyKeys.has(f.key);
                return (
                  <div key={f.key} className="space-y-1">
                    <label className="block text-xs text-subtle">
                      {f.label}
                      {dirty && <span className="ml-1 text-accent" title="Modified">*</span>}
                    </label>
                    {f.multiline ? (
                      <textarea
                        value={fields[f.key] || ""}
                        onChange={(e) => setField(f.key, e.target.value)}
                        rows={Math.max(f.minRows || 3, Math.min(20, (fields[f.key] || "").split("\n").length + 1))}
                        className={`w-full bg-panel border rounded-lg px-3 py-2 text-sm font-mono ${
                          dirty ? "border-accent" : "border-border"
                        }`}
                      />
                    ) : (
                      <input
                        type="text"
                        value={fields[f.key] || ""}
                        onChange={(e) => setField(f.key, e.target.value)}
                        className={`w-full bg-panel border rounded-lg px-3 py-2 text-sm ${
                          dirty ? "border-accent" : "border-border"
                        }`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}

        {versions.length > 1 && (
          <VersionToggle
            versions={versions}
            bestVersionId={bestVersionId}
            sessionId={sessionId}
            paused={paused}
            onSelected={(vid) => {
              setBestVersionId(vid);
              const ver = versions.find((v) => v.version_id === vid);
              if (ver) setField("cover_letter", ver.text);
              setOriginalFields((prev) => ({ ...prev, cover_letter: ver?.text || prev.cover_letter }));
            }}
          />
        )}

        <div className="flex items-center gap-4 pb-8">
          <button
            onClick={save}
            disabled={!paused || !hasDirty}
            className="px-4 py-2 rounded-lg bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-40"
          >
            Save changes{hasDirty ? ` (${dirtyKeys.size})` : ""}
          </button>
          <button
            onClick={reload}
            className="px-4 py-2 rounded-lg border border-border hover:bg-panel"
          >
            Reload
          </button>
          {status && <span className="text-sm text-subtle">{status}</span>}
        </div>
      </div>
    </main>
  );
}

function VersionToggle({
  versions,
  bestVersionId,
  sessionId,
  paused,
  onSelected,
}: {
  versions: CoverLetterVersion[];
  bestVersionId: string | null;
  sessionId: string;
  paused: boolean;
  onSelected: (versionId: string) => void;
}) {
  const bestIdx = versions.findIndex((v) => v.version_id === bestVersionId);
  const [activeIdx, setActiveIdx] = useState(bestIdx >= 0 ? bestIdx : 0);
  const [selecting, setSelecting] = useState(false);
  const v = versions[activeIdx];
  const isCurrentBest = v?.version_id === bestVersionId;

  async function selectVersion() {
    if (!v) return;
    setSelecting(true);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/select-version`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: v.version_id }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(body.detail || `Failed: HTTP ${res.status}`);
        return;
      }
      onSelected(v.version_id);
    } finally {
      setSelecting(false);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">Cover letter versions</h2>
        <div className="flex gap-1">
          {versions.map((ver, i) => {
            const isBest = ver.version_id === bestVersionId;
            const active = i === activeIdx;
            return (
              <button
                key={ver.version_id}
                onClick={() => setActiveIdx(i)}
                className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? "bg-accent text-bg"
                    : isBest
                      ? "border border-accent text-accent hover:bg-accent/10"
                      : "border border-border text-subtle hover:text-text hover:border-accent"
                }`}
                title={
                  isBest
                    ? `Version ${ver.iteration} (selected)`
                    : `Version ${ver.iteration}`
                }
              >
                {ver.iteration}
              </button>
            );
          })}
        </div>
      </div>
      {v && (
        <div className="space-y-2">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-medium">
              Version {v.iteration}
              {isCurrentBest && (
                <span className="ml-2 text-accent">(selected)</span>
              )}
            </span>
            {v.hm_score != null && (
              <span className="text-subtle">
                HM score: <span className="text-text">{v.hm_score.toFixed(1)}/10</span>
              </span>
            )}
            {!isCurrentBest && (
              <button
                onClick={selectVersion}
                disabled={!paused || selecting}
                className="ml-auto px-3 py-1 rounded-lg border border-accent/30 bg-accent/5 text-xs text-accent hover:bg-accent/15 disabled:opacity-40 transition-colors"
              >
                {selecting ? "Saving…" : "Use this version"}
              </button>
            )}
          </div>
          <pre className="whitespace-pre-wrap text-sm font-mono bg-panel2 border border-border rounded-lg p-3 max-h-96 overflow-y-auto">
            {v.text}
          </pre>
          {v.hm_feedback && (
            <details className="text-xs text-subtle">
              <summary className="cursor-pointer">Hiring manager feedback</summary>
              <div className="mt-1 space-y-1 pl-2">
                {v.hm_feedback.strengths && (
                  <div>
                    <span className="text-ok">Strengths:</span>{" "}
                    {Array.isArray(v.hm_feedback.strengths)
                      ? v.hm_feedback.strengths.join(", ")
                      : v.hm_feedback.strengths}
                  </div>
                )}
                {v.hm_feedback.weaknesses && (
                  <div>
                    <span className="text-warn">Weaknesses:</span>{" "}
                    {Array.isArray(v.hm_feedback.weaknesses)
                      ? v.hm_feedback.weaknesses.join(", ")
                      : v.hm_feedback.weaknesses}
                  </div>
                )}
                {v.hm_feedback.suggestions && (
                  <div>
                    <span className="text-accent">Suggestions:</span>{" "}
                    {Array.isArray(v.hm_feedback.suggestions)
                      ? v.hm_feedback.suggestions.join(", ")
                      : v.hm_feedback.suggestions}
                  </div>
                )}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

export default function DetailsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-subtle">Loading…</div>}>
      <DetailsView />
    </Suspense>
  );
}
