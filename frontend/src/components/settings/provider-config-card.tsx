"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PROVIDERS = [
  { value: "google", label: "Google (Gemini)" },
  { value: "openai", label: "OpenAI" },
  { value: "ninerouter", label: "9Router" },
  { value: "anthropic", label: "Anthropic" },
];

type Props = {
  title: string;
  description: string;
  icon: string;
  provider: string;
  model: string;
  apiKey: string;
  baseUrl?: string;
  onProviderChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange?: (value: string) => void;
};

export function ProviderConfigCard({
  title,
  description,
  icon,
  provider,
  model,
  apiKey,
  baseUrl,
  onProviderChange,
  onModelChange,
  onApiKeyChange,
  onBaseUrlChange,
}: Props) {
  return (
    <div className="bg-card rounded-xl p-6 border border-border shadow-sahara">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary text-base">
            {icon}
          </span>
        </div>
        <div>
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs">Provider</Label>
          <Select value={provider} onValueChange={(v) => v && onProviderChange(v)}>
            <SelectTrigger className="bg-background">
              <SelectValue placeholder="Select provider" />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs">Model ID</Label>
          <Input
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            placeholder="e.g. text-embedding-004"
            className="bg-background"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs">API Key</Label>
          <Input
            type={apiKey.includes("•") ? "text" : "password"}
            value={apiKey}
            onChange={(e) => onApiKeyChange(e.target.value)}
            onFocus={() => {
              if (apiKey.includes("•")) onApiKeyChange("");
            }}
            placeholder="sk-..."
            className="bg-background"
          />
        </div>

        {onBaseUrlChange && (
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs">Base URL</Label>
            <Input
              value={baseUrl ?? ""}
              onChange={(e) => onBaseUrlChange(e.target.value)}
              placeholder="http://host.docker.internal:20128"
              className="bg-background"
            />
          </div>
        )}
      </div>
    </div>
  );
}
