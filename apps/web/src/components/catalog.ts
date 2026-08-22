import { ActionControls } from "./ActionControls";
import { ActivityTimeline } from "./ActivityTimeline";
import { ResearchResults } from "./ResearchResults";
import { ResearchStatusPanel } from "./ResearchStatusPanel";
import { SpecialistStatusList } from "./SpecialistStatusList";

export const AGENTDESK_COMPONENT_CATALOG_VERSION = "1.0";

export const agentDeskComponentCatalog = Object.freeze({
  ActionControls,
  ActivityTimeline,
  ResearchResults,
  ResearchStatusPanel,
  SpecialistStatusList,
});

export type AgentDeskComponentName = keyof typeof agentDeskComponentCatalog;

export class UnknownCatalogComponentError extends Error {
  constructor(name: string) {
    super(`Unknown AgentDesk component: ${name}`);
    this.name = "UnknownCatalogComponentError";
  }
}

export function resolveCatalogComponent(name: string) {
  if (!Object.hasOwn(agentDeskComponentCatalog, name)) {
    throw new UnknownCatalogComponentError(name);
  }
  return agentDeskComponentCatalog[name as AgentDeskComponentName];
}
