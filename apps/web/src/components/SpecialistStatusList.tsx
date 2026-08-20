import type { AgentDeskViewState } from "../agui/state";
import { SPECIALIST_STATUS_PRESENTATION } from "./research-status";

interface SpecialistStatusListProps {
  agents: AgentDeskViewState["agents"];
}

export function SpecialistStatusList({ agents }: SpecialistStatusListProps) {
  return (
    <section className="specialist-section" aria-labelledby="specialist-heading">
      <div className="component-heading">
        <div>
          <p className="eyebrow">Specialist activity</p>
          <h3 id="specialist-heading">Coordinated agents</h3>
        </div>
        <span>{agents.length}</span>
      </div>

      {agents.length > 0 ? (
        <ul className="specialist-list">
          {agents.map((agent) => {
            const presentation = SPECIALIST_STATUS_PRESENTATION[agent.status];
            return (
              <li
                className="specialist-card"
                data-status={agent.status}
                key={agent.agentId}
                aria-busy={agent.status === "working"}
              >
                <span className="specialist-avatar" aria-hidden="true">
                  {initials(agent.name)}
                </span>
                <div className="specialist-card__body">
                  <div className="specialist-card__title">
                    <div>
                      <strong>{agent.name}</strong>
                      <span>{formatSkill(agent.skill)}</span>
                    </div>
                    <span className={`status-chip status-chip--${presentation.tone}`}>
                      <i aria-hidden="true" />
                      {presentation.label}
                    </span>
                  </div>
                  <p>{agent.message ?? presentation.description}</p>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="specialist-empty">
          <span aria-hidden="true">•••</span>
          <p>Specialists will appear here as the Coordinator assigns work.</p>
        </div>
      )}
    </section>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/u)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function formatSkill(skill: string): string {
  return skill.replaceAll("-", " ").replaceAll("_", " ");
}
