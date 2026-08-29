import type { StartResearchParameters } from "../agui/actions";

export type AgentDeskRuntimeMode = "live" | "demo" | "adaptive-demo";

export const DEMO_RESEARCH_QUESTION = "Should the product use PostgreSQL or MongoDB?";
export const DEMO_RESEARCH_PARAMETERS: StartResearchParameters = {
  options: ["PostgreSQL", "MongoDB"],
  constraints: ["Preserve transactional integrity"],
  criteria: ["Data integrity", "Schema flexibility"],
  desiredDepth: "normal",
};

export const ADAPTIVE_DEMO_RESEARCH_QUESTION = DEMO_RESEARCH_QUESTION;

export function resolveRuntimeMode(value: unknown): AgentDeskRuntimeMode {
  if (value === undefined || value === "" || value === "live") {
    return "live";
  }
  if (value === "demo" || value === "adaptive-demo") {
    return value;
  }
  throw new Error("VITE_AGENTDESK_RUNTIME_MODE must be live, demo, or adaptive-demo.");
}

export function resolveAdaptiveIntakeEnabled(value: unknown): boolean {
  if (value === undefined || value === "" || value === "false") return false;
  if (value === "true") return true;
  throw new Error("VITE_AGENTDESK_ADAPTIVE_INTAKE_ENABLED must be true or false.");
}

export const agentDeskRuntimeMode = resolveRuntimeMode(
  import.meta.env.VITE_AGENTDESK_RUNTIME_MODE,
);
export const adaptiveIntakeEnabled =
  agentDeskRuntimeMode === "adaptive-demo" ||
  resolveAdaptiveIntakeEnabled(import.meta.env.VITE_AGENTDESK_ADAPTIVE_INTAKE_ENABLED);
