"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

type LLMConfig = {
  provider: string;
  model_name: string;
  base_url?: string | null;
};

type ModelPricing = {
  input_per_mtok: number;
  output_per_mtok: number;
};

type SettingsPayload = {
  default_llm: LLMConfig;
  task_llm_configs: Record<string, LLMConfig>;
  model_pricing: Record<string, ModelPricing>;
  known_tasks: string[];
  google_sheets_spreadsheet_id: string;
};

const PROVIDERS = ["anthropic", "openai", "ollama"];

const PROVIDER_MODELS: Record<string, string[]> = {
  anthropic: [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
  ],
  openai: [
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-pro",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "o3",
    "o3-mini",
    "o1",
    "o1-mini",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
  ],
};

function emptyCfg(): LLMConfig {
  return { provider: "", model_name: "", base_url: "" };
}

function cfgEqual(a: LLMConfig, b: LLMConfig) {
  return (
    a.provider === b.provider &&
    a.model_name === b.model_name &&
    (a.base_url || "") === (b.base_url || "")
  );
}

function pricingEqual(a: ModelPricing, b: ModelPricing) {
  return a.input_per_mtok === b.input_per_mtok && a.output_per_mtok === b.output_per_mtok;
}

function SettingsView() {
  const params = useSearchParams();
  const from = params.get("from") || "/";
  const backLabel = from.startsWith("/session") ? "← Back to chat" : "← Back home";
  const [loaded, setLoaded] = useState(false);
  const [defaultLlm, setDefaultLlm] = useState<LLMConfig>(emptyCfg());
  const [tasks, setTasks] = useState<string[]>([]);
  const [taskCfgs, setTaskCfgs] = useState<Record<string, LLMConfig>>({});
  const [pricing, setPricing] = useState<Record<string, ModelPricing>>({});
  const [newPriceModel, setNewPriceModel] = useState("");
  const [sheetsId, setSheetsId] = useState("");
  const [status, setStatus] = useState<string>("");

  const [origDefaultLlm, setOrigDefaultLlm] = useState<LLMConfig>(emptyCfg());
  const [origTaskCfgs, setOrigTaskCfgs] = useState<Record<string, LLMConfig>>({});
  const [origPricing, setOrigPricing] = useState<Record<string, ModelPricing>>({});
  const [origSheetsId, setOrigSheetsId] = useState("");

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((data: SettingsPayload) => {
        setDefaultLlm(data.default_llm);
        setOrigDefaultLlm(data.default_llm);
        setTasks(data.known_tasks);
        const filled: Record<string, LLMConfig> = {};
        for (const t of data.known_tasks) {
          filled[t] = data.task_llm_configs[t] || emptyCfg();
        }
        setTaskCfgs(filled);
        setOrigTaskCfgs(JSON.parse(JSON.stringify(filled)));
        const p = data.model_pricing || {};
        setPricing(p);
        setOrigPricing(JSON.parse(JSON.stringify(p)));
        const sid = data.google_sheets_spreadsheet_id || "";
        setSheetsId(sid);
        setOrigSheetsId(sid);
        setLoaded(true);
      })
      .catch((e) => setStatus(`Load failed: ${e}`));
  }, []);

  const defaultDirty = !cfgEqual(defaultLlm, origDefaultLlm);
  const sheetsDirty = sheetsId !== origSheetsId;
  const pricingDirty = (() => {
    const origKeys = Object.keys(origPricing).sort();
    const curKeys = Object.keys(pricing).sort();
    if (origKeys.join(",") !== curKeys.join(",")) return true;
    return origKeys.some((k) => !pricingEqual(pricing[k], origPricing[k]));
  })();
  const anyDirty =
    defaultDirty ||
    sheetsDirty ||
    pricingDirty ||
    tasks.some((t) => !cfgEqual(taskCfgs[t], origTaskCfgs[t] || emptyCfg()));

  function updatePrice(model: string, patch: Partial<ModelPricing>) {
    setPricing((prev) => ({ ...prev, [model]: { ...prev[model], ...patch } }));
  }

  function removePrice(model: string) {
    setPricing((prev) => {
      const next = { ...prev };
      delete next[model];
      return next;
    });
  }

  function addPrice() {
    const name = newPriceModel.trim();
    if (!name || pricing[name]) return;
    setPricing((prev) => ({ ...prev, [name]: { input_per_mtok: 0, output_per_mtok: 0 } }));
    setNewPriceModel("");
  }

  function updateTask(task: string, patch: Partial<LLMConfig>) {
    setTaskCfgs((prev) => ({ ...prev, [task]: { ...prev[task], ...patch } }));
  }

  async function save() {
    setStatus("Saving…");
    const cleanTasks: Record<string, LLMConfig> = {};
    for (const [k, v] of Object.entries(taskCfgs)) {
      if (v.provider && v.model_name) cleanTasks[k] = v;
    }
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        default_llm: defaultLlm,
        task_llm_configs: cleanTasks,
        model_pricing: pricing,
        google_sheets_spreadsheet_id: sheetsId,
      }),
    });
    if (res.ok) {
      setOrigDefaultLlm(JSON.parse(JSON.stringify(defaultLlm)));
      setOrigTaskCfgs(JSON.parse(JSON.stringify(taskCfgs)));
      setOrigPricing(JSON.parse(JSON.stringify(pricing)));
      setOrigSheetsId(sheetsId);
      setStatus("Saved. New calls will use the updated models.");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      setStatus(`Save failed: HTTP ${res.status}`);
    }
  }

  if (!loaded) {
    return <main className="p-8 text-subtle">Loading settings…</main>;
  }

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="font-semibold">Settings</div>
        <div className="flex items-center gap-4 text-xs">
          {status && <span className="text-subtle">{status}</span>}
          <a href={from} className="text-accent hover:underline">
            {backLabel}
          </a>
        </div>
      </header>
      <div className="max-w-3xl mx-auto p-6 space-y-8">
        <p className="text-sm text-subtle">
          Configure which LLM models the assistant uses — a global default, per-task overrides, and
          model pricing for cost tracking. You can also set the Google Sheets spreadsheet for cover
          letter exports.
        </p>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Default model{defaultDirty && " *"}</h2>
          <p className="text-sm text-subtle">
            Used for any task that doesn't have a per-task override below.
          </p>
          <CfgRow
            cfg={defaultLlm}
            onChange={(patch) => setDefaultLlm({ ...defaultLlm, ...patch })}
          />
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Per-task overrides</h2>
          <p className="text-sm text-subtle">
            Leave provider/model blank to fall back to the default.
          </p>
          <div className="space-y-2">
            {tasks.map((t) => (
              <div key={t} className="border border-border rounded-lg p-3 bg-panel">
                <div className="text-sm font-medium mb-2">
                  {t}{!cfgEqual(taskCfgs[t], origTaskCfgs[t] || emptyCfg()) && " *"}
                </div>
                <CfgRow
                  cfg={taskCfgs[t]}
                  onChange={(patch) => updateTask(t, patch)}
                />
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Model pricing{pricingDirty && " *"}</h2>
          <p className="text-sm text-subtle">
            USD per million tokens. Used to compute cost on the session usage page. Models without
            an entry here show "—" instead of a cost.
          </p>
          <div className="space-y-2">
            {Object.entries(pricing).map(([model, p]) => (
              <div
                key={model}
                className="border border-border rounded-lg p-3 bg-panel grid grid-cols-[1fr_auto_auto_auto] gap-2 items-center"
              >
                <div className="text-sm font-mono">
                  {model}{(!origPricing[model] || !pricingEqual(p, origPricing[model])) && " *"}
                </div>
                <input
                  type="number"
                  step="0.01"
                  value={p.input_per_mtok}
                  onChange={(e) =>
                    updatePrice(model, { input_per_mtok: parseFloat(e.target.value) || 0 })
                  }
                  placeholder="input $/Mtok"
                  className="w-28 bg-panel2 border border-border rounded px-2 py-1 text-sm"
                />
                <input
                  type="number"
                  step="0.01"
                  value={p.output_per_mtok}
                  onChange={(e) =>
                    updatePrice(model, { output_per_mtok: parseFloat(e.target.value) || 0 })
                  }
                  placeholder="output $/Mtok"
                  className="w-28 bg-panel2 border border-border rounded px-2 py-1 text-sm"
                />
                <button
                  onClick={() => removePrice(model)}
                  className="text-xs text-subtle hover:text-err"
                >
                  remove
                </button>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newPriceModel}
              onChange={(e) => setNewPriceModel(e.target.value)}
              placeholder="model name (e.g. claude-sonnet-4-6)"
              className="flex-1 bg-panel2 border border-border rounded px-2 py-1 text-sm"
            />
            <button
              onClick={addPrice}
              className="px-3 py-1 rounded border border-border text-sm hover:bg-panel"
            >
              Add model
            </button>
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Google Sheets export{sheetsDirty && " *"}</h2>
          <p className="text-sm text-subtle">
            Spreadsheet ID to append cover letter exports to. Overrides the{" "}
            <code className="font-mono text-xs">GOOGLE_SHEETS_SPREADSHEET_ID</code> env var.
          </p>
          <input
            type="text"
            value={sheetsId}
            onChange={(e) => setSheetsId(e.target.value)}
            placeholder="e.g. 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
            className="w-full bg-panel2 border border-border rounded px-2 py-1 text-sm font-mono"
          />
        </section>

        <div className="flex items-center gap-4">
          <button
            onClick={save}
            disabled={!anyDirty}
            className="px-4 py-2 rounded-lg bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Save
          </button>
          {status && <span className="text-sm text-subtle">{status}</span>}
        </div>
      </div>
    </main>
  );
}

function CfgRow({
  cfg,
  onChange,
}: {
  cfg: LLMConfig;
  onChange: (patch: Partial<LLMConfig>) => void;
}) {
  return (
    <div className="grid grid-cols-[1fr_1fr_1fr] gap-2">
      <select
        value={cfg.provider || ""}
        onChange={(e) => onChange({ provider: e.target.value, model_name: "" })}
        className="bg-panel2 border border-border rounded px-2 py-1 text-sm"
      >
        <option value="">(default)</option>
        {PROVIDERS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      {PROVIDER_MODELS[cfg.provider] ? (
        <select
          value={cfg.model_name || ""}
          onChange={(e) => onChange({ model_name: e.target.value })}
          className="bg-panel2 border border-border rounded px-2 py-1 text-sm"
        >
          <option value="">select model…</option>
          {PROVIDER_MODELS[cfg.provider].map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={cfg.model_name || ""}
          onChange={(e) => onChange({ model_name: e.target.value })}
          placeholder="model name"
          className="bg-panel2 border border-border rounded px-2 py-1 text-sm"
        />
      )}
      <input
        type="text"
        value={cfg.base_url || ""}
        onChange={(e) => onChange({ base_url: e.target.value })}
        placeholder="base url (optional)"
        className="bg-panel2 border border-border rounded px-2 py-1 text-sm"
      />
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<main className="p-8 text-subtle">Loading…</main>}>
      <SettingsView />
    </Suspense>
  );
}
