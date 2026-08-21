import type { AgentDeskViewState } from "../agui/state";
import type { SessionSelection } from "../agui/selectors";
import {
  buildWorkflowStages,
  RESEARCH_STATUS_PRESENTATION,
  type WorkflowStageState,
} from "./research-status";
import { SpecialistStatusList } from "./SpecialistStatusList";

interface ResearchStatusPanelProps {
  agents: AgentDeskViewState["agents"];
  evidenceCount: number;
  message: string;
  session: SessionSelection;
}

const STAGE_STATE_LABELS: Record<WorkflowStageState, string> = {
  queued: "Up next",
  active: "In progress",
  complete: "Complete",
  attention: "Needs review",
  stopping: "Stopping",
  stopped: "Stopped",
};

export function ResearchStatusPanel({
  agents,
  evidenceCount,
  message,
  session,
}: ResearchStatusPanelProps) {
  const status = RESEARCH_STATUS_PRESENTATION[session.status];
  const stages = buildWorkflowStages(session.status, session.activeStep);

  return (
    <div className="research-status-panel" data-status={session.status}>
      <section className="research-phase" aria-labelledby="research-phase-heading">
        <div className={`phase-symbol phase-symbol--${status.tone}`} aria-hidden="true">
          <span />
          <i />
        </div>
        <div className="research-phase__copy">
          <p className="eyebrow">Research status</p>
          <h3 id="research-phase-heading">{status.label}</h3>
          <p>{status.description}</p>
        </div>
        <dl className="research-facts">
          <div>
            <dt>Active step</dt>
            <dd>{formatStep(session.activeStep)}</dd>
          </div>
          <div>
            <dt>Evidence</dt>
            <dd>{evidenceCount}</dd>
          </div>
        </dl>
      </section>

      <ol className="workflow-stages" aria-label="Research workflow stages">
        {stages.map((stage) => (
          <li data-state={stage.state} key={stage.id}>
            <span className="workflow-marker" aria-hidden="true">
              <i />
            </span>
            <div>
              <strong>{stage.label}</strong>
              <span>{STAGE_STATE_LABELS[stage.state]}</span>
            </div>
          </li>
        ))}
      </ol>

      <SpecialistStatusList agents={agents} />

      <div className="activity-card" aria-live="polite">
        <span className="activity-orbit" aria-hidden="true">
          <i />
        </span>
        <div>
          <strong>{message}</strong>
          <p>Activity is reported as observed states, not estimated percentage progress.</p>
        </div>
      </div>
    </div>
  );
}

function formatStep(activeStep: string | null): string {
  if (activeStep === null) {
    return "None";
  }
  return activeStep.replaceAll("-", " ").replaceAll("_", " ");
}
