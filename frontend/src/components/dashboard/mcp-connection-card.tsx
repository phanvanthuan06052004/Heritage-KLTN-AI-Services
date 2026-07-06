"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export function McpConnectionCard() {
  const [copied, setCopied] = useState(false);

  const configSnippet = `{
  "mcpServers": {
    "heritage-ai": {
      "url": "${typeof window !== "undefined" ? window.location.origin : "https://your-server"}/mcp",
      "headers": {
        "Authorization": "Bearer <your-mcp-token>"
      }
    }
  }
}`;

  const handleCopy = () => {
    navigator.clipboard.writeText(configSnippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-surface-variant rounded-xl p-6 border border-border">
      <h3 className="text-xl tracking-tight text-foreground mb-2">
        MCP Connection
      </h3>
      <p className="text-xs text-muted-foreground mb-4">
        Connect Claude Desktop to Heritage AI with this config snippet.
      </p>

      <div className="bg-[#3a302a] rounded-lg p-4 font-mono text-xs text-[#faf5ee] overflow-x-auto">
        <pre>{configSnippet}</pre>
      </div>

      <Button
        variant="ghost"
        size="sm"
        onClick={handleCopy}
        className="mt-3 text-primary hover:text-primary/80 text-xs"
      >
        <span className="material-symbols-outlined text-sm mr-1">
          {copied ? "check" : "content_copy"}
        </span>
        {copied ? "Copied!" : "Copy Config"}
      </Button>
    </div>
  );
}
