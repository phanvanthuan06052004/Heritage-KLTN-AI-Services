import React from "react";
import { WikiGraph } from "./index";
import { NodeInput } from "./types";

export function WikiGraphMini({
  slug,
  nodes,
  edges,
}: {
  slug: string;
  nodes: NodeInput[];
  edges: { from: string; to: string }[];
}) {
  return (
    <WikiGraph
      nodes={nodes}
      edges={edges}
      centerSlug={slug}
      mini
      height={180}
    />
  );
}
