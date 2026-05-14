"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

type EmbeddingSpec = {
  id: string;
  provider: string;
  model_id: string;
  dimension: number;
  label: string;
  cost_per_1m_tokens: number | null;
  notes: string | null;
  api_key_configured: boolean;
};

type CatalogResp = {
  active_spec_id: string | null;
  specs: EmbeddingSpec[];
};

type StatusResp = {
  active_spec_id: string | null;
  total_pages: number;
  embedded_pages: number;
  current_job: JobResp | null;
};

type JobResp = {
  id: string;
  model_spec_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  total_pages: number;
  done_pages: number;
  error_message: string | null;
};

export function EmbeddingSettingsCard() {
  const [catalog, setCatalog] = useState<CatalogResp | null>(null);
  const [status, setStatus] = useState<StatusResp | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // Masked keys per provider, e.g. {"google": "••••••••P258"}. Loaded from
  // /api/settings; the bullet character means "key already saved server-side".
  const [maskedKeys, setMaskedKeys] = useState<Record<string, string>>({});
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void refresh();
  }, []);

  // When the user picks a different model, prefill the input with that
  // provider's masked key (or empty if none).
  useEffect(() => {
    const provider = catalog?.specs.find((s) => s.id === selected)?.provider;
    setApiKey(provider ? maskedKeys[provider] ?? "" : "");
  }, [selected, maskedKeys, catalog]);

  // Poll active job every 2s while one is running.
  useEffect(() => {
    const job = status?.current_job;
    if (!job || (job.status !== "pending" && job.status !== "running")) return;
    const t = setInterval(() => {
      void refreshStatus();
    }, 2000);
    return () => clearInterval(t);
  }, [status?.current_job?.id, status?.current_job?.status]);

  async function refresh() {
    try {
      const [c, s, settings] = await Promise.all([
        api<CatalogResp>("/api/settings/embeddings/catalog"),
        api<StatusResp>("/api/settings/embeddings/status"),
        api<Record<string, unknown>>("/api/settings"),
      ]);
      setCatalog(c);
      setStatus(s);
      const masked: Record<string, string> = {};
      for (const provider of new Set(c.specs.map((sp) => sp.provider))) {
        const v = settings[`embedding_api_key__${provider}`];
        if (typeof v === "string" && v.length > 0) masked[provider] = v;
      }
      setMaskedKeys(masked);
      if (!selected) setSelected(c.active_spec_id ?? c.specs[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load embedding catalog");
    }
  }

  async function refreshStatus() {
    try {
      const s = await api<StatusResp>("/api/settings/embeddings/status");
      setStatus(s);
    } catch {
      // ignore — keep last known
    }
  }

  const selectedSpec = catalog?.specs.find((s) => s.id === selected) ?? null;
  const job = status?.current_job ?? null;
  const jobBusy = job && (job.status === "pending" || job.status === "running");
  const isActiveSelected = selectedSpec?.id === catalog?.active_spec_id;
  const willSwitch = !!selectedSpec && !isActiveSelected;
  // The current input value is "the saved masked one" if it contains the
  // bullet character — in that case treat it as "no change".
  const isMaskedKey = apiKey.includes("•");
  const hasNewKey = apiKey.trim().length > 0 && !isMaskedKey;
  const canSave =
    !!selectedSpec &&
    !jobBusy &&
    (hasNewKey || (willSwitch && selectedSpec.api_key_configured));

  async function handleSave() {
    if (!selectedSpec) return;
    setSaving(true);
    setError("");
    try {
      // 1. Save API key for this provider only if user typed a new one.
      if (hasNewKey) {
        await api("/api/settings", {
          method: "PUT",
          body: {
            settings: {
              [`embedding_api_key__${selectedSpec.provider}`]: apiKey.trim(),
            },
          },
        });
      }
      // 2. Trigger switch if the selected model differs from active.
      if (willSwitch) {
        await api("/api/settings/embeddings/switch", {
          method: "POST",
          body: { model_spec_id: selectedSpec.id },
        });
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    try {
      await api(`/api/settings/embeddings/jobs/${job.id}/cancel`, {
        method: "POST",
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
    }
  }

  if (!catalog || !status) {
    return (
      <div className="bg-card rounded-xl p-6 border border-border shadow-sahara">
        <p className="text-sm text-muted-foreground">Loading embedding catalog…</p>
      </div>
    );
  }

  return (
    <div className="bg-card rounded-xl p-6 border border-border shadow-sahara">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary text-base">data_array</span>
        </div>
        <div className="flex-1">
          <h3 className="text-base font-semibold text-foreground">Embedding Model</h3>
          <p className="text-xs text-muted-foreground">
            Choose a model and save its API key.
          </p>
        </div>
      </div>

      {/* Job progress */}
      {jobBusy && (
        <div className="mb-4 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span>
              Migrating to <strong>{job.model_spec_id}</strong> — {job.done_pages}/{job.total_pages} pages
            </span>
            <button onClick={cancelJob} className="text-xs underline hover:no-underline">
              Cancel
            </button>
          </div>
          <div className="h-2 rounded bg-blue-100 dark:bg-blue-900 overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{
                width: `${
                  job.total_pages > 0 ? Math.round((job.done_pages / job.total_pages) * 100) : 0
                }%`,
              }}
            />
          </div>
        </div>
      )}

      {job?.status === "failed" && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-xs">
          <strong>Migration failed:</strong> {job.error_message || "unknown"}
        </div>
      )}

      {/* Model list — name + provider only */}
      <div className="flex flex-col gap-2 mb-4">
        {catalog.specs.map((spec) => {
          const isActive = spec.id === catalog.active_spec_id;
          const isChecked = spec.id === selected;
          return (
            <label
              key={spec.id}
              className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                isChecked ? "border-primary bg-primary/5" : "border-border hover:bg-accent/30"
              }`}
            >
              <input
                type="radio"
                name="embedding-spec"
                value={spec.id}
                checked={isChecked}
                onChange={() => setSelected(spec.id)}
                disabled={!!jobBusy}
              />
              <span className="text-sm font-medium flex-1">{spec.model_id}</span>
              <span className="text-xs text-muted-foreground">{spec.provider}</span>
              {isActive && (
                <span className="text-[10px] uppercase tracking-wide bg-green-500/15 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                  Active
                </span>
              )}
            </label>
          );
        })}
      </div>

      {/* API key */}
      {selectedSpec && (
        <div className="mb-4 flex flex-col gap-1.5">
          <Label className="text-xs">
            API key for {selectedSpec.provider}
            {selectedSpec.api_key_configured && (
              <span className="ml-2 text-green-600 dark:text-green-400">✓ saved</span>
            )}
          </Label>
          <Input
            type={isMaskedKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onFocus={() => {
              if (isMaskedKey) setApiKey("");
            }}
            placeholder={
              selectedSpec.api_key_configured ? "Replace existing key…" : "Paste API key"
            }
            className="bg-background"
          />
        </div>
      )}

      {/* Single Save button */}
      <div className="flex items-center gap-3">
        <button
          disabled={!canSave || saving}
          onClick={handleSave}
          className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}
