import type { StartResearchParameters } from "../agui/actions";

export type AgentDeskRuntimeMode = "live" | "demo";

export const DEMO_RESEARCH_QUESTION = "Should the product use PostgreSQL or MongoDB?";
export const DEMO_RESEARCH_PARAMETERS: StartResearchParameters = {
  options: ["PostgreSQL", "MongoDB"],
  constraints: ["Preserve transactional integrity"],
  criteria: ["Data integrity", "Schema flexibility"],
  desiredDepth: "normal",
};

export function resolveRuntimeMode(value: unknown): AgentDeskRuntimeMode {
  if (value === undefined || value === "" || value === "live") {
    return "live";
  }
  if (value === "demo") {
    return "demo";
  }
  throw new Error("VITE_AGENTDESK_RUNTIME_MODE must be live or demo.");
}

export const agentDeskRuntimeMode = resolveRuntimeMode(
  import.meta.env.VITE_AGENTDESK_RUNTIME_MODE,
);
