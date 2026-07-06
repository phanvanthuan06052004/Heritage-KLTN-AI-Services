"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PageHeader } from "@/components/shared/page-header";
import { ProviderConfigCard } from "@/components/settings/provider-config-card";
import { EmbeddingSettingsCard } from "@/components/settings/embedding-settings-card";

// Keys must match ALL_CONFIG_KEYS in app/services/config_service.py.
// Embedding configuration is now driven by EmbeddingSettingsCard (catalog
// whitelist + re-embed jobs); only LLM and Vision are still free-form here.
type ProviderConfig = {
  llm_provider: string;
  llm_model_id: string;
  llm_api_key: string;
  llm_base_url: string;
  vision_provider: string;
  vision_model_id: string;
  vision_api_key: string;
  vision_base_url: string;
};

const defaultConfig: ProviderConfig = {
  llm_provider: "",
  llm_model_id: "",
  llm_api_key: "",
  llm_base_url: "",
  vision_provider: "",
  vision_model_id: "",
  vision_api_key: "",
  vision_base_url: "",
};

export default function SettingsPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [config, setConfig] = useState<ProviderConfig>(defaultConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");

  // Admin guard
  useEffect(() => {
    if (user && user.role !== "admin") {
      router.replace("/");
    }
  }, [user, router]);

  useEffect(() => {
    if (user?.role !== "admin") return;
    async function load() {
      try {
        const data = await api<Record<string, unknown>>("/api/settings");
        const coerced = Object.fromEntries(
          Object.keys(defaultConfig).map((k) => [k, String(data[k] ?? "")])
        ) as ProviderConfig;
        setConfig(coerced);
      } catch {
        // Use defaults
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [user]);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setSaveError("");
    try {
      const settings: Record<string, string> = {};
      for (const [k, v] of Object.entries(config)) {
        const str = typeof v === "string" ? v : "";
        // Skip masked values — server already has them stored
        if (str && !str.startsWith("•")) settings[k] = str;
        else if (!str) settings[k] = "";
      }
      await api("/api/settings", { method: "PUT", body: { settings } });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const updateField = (key: keyof ProviderConfig, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="material-symbols-outlined text-3xl text-muted-foreground animate-spin">
          progress_activity
        </span>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Configure AI providers for embedding, LLM, and vision processing."
      />

      <div className="flex flex-col gap-6">
        <EmbeddingSettingsCard />

        <ProviderConfigCard
          title="LLM Provider"
          description="Used for AI-powered analysis and summarization"
          icon="psychology"
          provider={config.llm_provider}
          model={config.llm_model_id}
          apiKey={config.llm_api_key}
          baseUrl={config.llm_base_url}
          onProviderChange={(v) => updateField("llm_provider", v)}
          onModelChange={(v) => updateField("llm_model_id", v)}
          onApiKeyChange={(v) => updateField("llm_api_key", v)}
          onBaseUrlChange={(v) => updateField("llm_base_url", v)}
        />

        <ProviderConfigCard
          title="Vision Provider"
          description="Optional — used for image analysis in documents"
          icon="visibility"
          provider={config.vision_provider}
          model={config.vision_model_id}
          apiKey={config.vision_api_key}
          baseUrl={config.vision_base_url}
          onProviderChange={(v) => updateField("vision_provider", v)}
          onModelChange={(v) => updateField("vision_model_id", v)}
          onApiKeyChange={(v) => updateField("vision_api_key", v)}
          onBaseUrlChange={(v) => updateField("vision_base_url", v)}
        />

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={saving}
              className="bg-primary text-primary-foreground px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Settings"}
            </button>
            {saved && (
              <span className="text-sm text-green-600 flex items-center gap-1">
                <span className="material-symbols-outlined text-sm filled">check_circle</span>
                Saved successfully
              </span>
            )}
          </div>
          {saveError && (
            <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-lg flex items-center gap-2">
              <span className="material-symbols-outlined text-base">error</span>
              {saveError}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
