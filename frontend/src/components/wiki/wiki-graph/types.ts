import { SimulationNodeDatum, SimulationLinkDatum } from "d3-force";

export type GraphNode = SimulationNodeDatum & {
  slug: string;
  title: string;
  page_type: string;
  scope_type?: string;
  scope_name?: string | null;
  degree?: number;
};

export type GraphLink = SimulationLinkDatum<GraphNode> & {
  from: string;
  to: string;
};

export type NodeInput = {
  slug: string;
  title: string;
  page_type: string;
  scope_type?: string;
  scope_id?: string | null;
  scope_name?: string | null;
};
