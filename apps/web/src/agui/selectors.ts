import type { AgentDeskViewState } from "./state.ts";

export interface SessionSelection {
  activeStep: string | null;
  lastUpdatedAt: string | null;
  question: string;
  sessionId: string;
  status: AgentDeskViewState["status"];
}

export function selectSession(state: AgentDeskViewState): SessionSelection | null {
  if (state.sessionId === null || state.question === null) {
    return null;
  }
  return {
    activeStep: state.activeStep,
    lastUpdatedAt: state.lastUpdatedAt,
    question: state.question,
    sessionId: state.sessionId,
    status: state.status,
  };
}

export function selectAgents(state: AgentDeskViewState) {
  return state.agents;
}

export function selectEvidence(state: AgentDeskViewState) {
  return state.evidence;
}

export function selectClaims(state: AgentDeskViewState) {
  return state.claims;
}

export function selectAnalysis(state: AgentDeskViewState) {
  return state.analysis;
}

export function selectVerification(state: AgentDeskViewState) {
  return state.verification;
}

export function selectWarnings(state: AgentDeskViewState) {
  return state.warnings;
}

export function selectErrors(state: AgentDeskViewState) {
  return state.errors;
}

export function selectActions(state: AgentDeskViewState) {
  return state.availableActions;
}
