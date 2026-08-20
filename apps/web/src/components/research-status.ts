import type { AgentDeskViewState } from "../agui/state.ts";

export type ResearchStatus = AgentDeskViewState["status"];
export type SpecialistStatus = AgentDeskViewState["agents"][number]["status"];
export type StatusTone = "neutral" | "active" | "success" | "warning" | "danger";
export type WorkflowStageState =
  | "queued"
  | "active"
  | "complete"
  | "attention"
  | "stopping"
  | "stopped";

export interface StatusPresentation {
  description: string;
  label: string;
  tone: StatusTone;
}

export interface WorkflowStage {
  id: "plan" | "research" | "analyze" | "verify";
  label: string;
  state: WorkflowStageState;
}

export const RESEARCH_STATUS_PRESENTATION = {
  idle: {
    label: "Ready",
    description: "Submit a question when you are ready to begin.",
    tone: "neutral",
  },
  planning: {
    label: "Planning",
    description: "The Coordinator is shaping the question into a research plan.",
    tone: "active",
  },
  researching: {
    label: "Researching",
    description: "Specialists are gathering and evaluating relevant evidence.",
    tone: "active",
  },
  analyzing: {
    label: "Analyzing",
    description: "The evidence is being compared against the decision criteria.",
    tone: "active",
  },
  verifying: {
    label: "Verifying",
    description: "Claims and recommendation boundaries are being checked.",
    tone: "active",
  },
  cancelling: {
    label: "Stopping work",
    description: "The Coordinator is safely stopping active specialist tasks.",
    tone: "warning",
  },
  completed: {
    label: "Complete",
    description: "The coordinated research run finished successfully.",
    tone: "success",
  },
  partial: {
    label: "Partially complete",
    description: "Useful work is available, but one or more steps need attention.",
    tone: "warning",
  },
  failed: {
    label: "Needs attention",
    description: "The run could not finish. Review the specialist details before retrying.",
    tone: "danger",
  },
  cancelled: {
    label: "Cancelled",
    description: "The run stopped without continuing the remaining workflow.",
    tone: "neutral",
  },
} satisfies Record<ResearchStatus, StatusPresentation>;

export const SPECIALIST_STATUS_PRESENTATION = {
  pending: {
    label: "Queued",
    description: "Waiting for the Coordinator to assign work.",
    tone: "neutral",
  },
  working: {
    label: "Working",
    description: "Actively processing the assigned task.",
    tone: "active",
  },
  waiting: {
    label: "Waiting",
    description: "Blocked on evidence or another specialist result.",
    tone: "warning",
  },
  completed: {
    label: "Complete",
    description: "The specialist returned its task result.",
    tone: "success",
  },
  failed: {
    label: "Failed",
    description: "The specialist could not complete its task.",
    tone: "danger",
  },
  cancelled: {
    label: "Cancelled",
    description: "The specialist task was stopped.",
    tone: "neutral",
  },
} satisfies Record<SpecialistStatus, StatusPresentation>;

const WORKFLOW_STAGES = [
  { id: "plan", label: "Plan" },
  { id: "research", label: "Research" },
  { id: "analyze", label: "Analyze" },
  { id: "verify", label: "Verify" },
] as const;

const ACTIVE_STAGE_INDEX: Partial<Record<ResearchStatus, number>> = {
  planning: 0,
  researching: 1,
  analyzing: 2,
  verifying: 3,
};

export function buildWorkflowStages(
  status: ResearchStatus,
  activeStep: string | null,
): WorkflowStage[] {
  if (status === "completed") {
    return WORKFLOW_STAGES.map((stage) => ({ ...stage, state: "complete" }));
  }
  if (status === "idle") {
    return WORKFLOW_STAGES.map((stage) => ({ ...stage, state: "queued" }));
  }

  const currentIndex = inferStageIndex(activeStep) ?? ACTIVE_STAGE_INDEX[status] ?? 0;
  return WORKFLOW_STAGES.map((stage, index) => ({
    ...stage,
    state:
      index < currentIndex
        ? "complete"
        : index > currentIndex
          ? "queued"
          : status === "failed" || status === "partial"
            ? "attention"
            : status === "cancelling"
              ? "stopping"
              : status === "cancelled"
                ? "stopped"
                : "active",
  }));
}

function inferStageIndex(activeStep: string | null): number | null {
  const step = activeStep?.toLowerCase() ?? "";
  if (step.includes("verif") || step.includes("final")) {
    return 3;
  }
  if (step.includes("analy") || step.includes("synth")) {
    return 2;
  }
  if (step.includes("research") || step.includes("evidence")) {
    return 1;
  }
  if (step.includes("plan") || step.includes("accept")) {
    return 0;
  }
  return null;
}
