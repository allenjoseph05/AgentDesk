import { useEffect, useState } from "react";

import type { AgentDeskAction } from "../agui/actions";
import type { AgentDeskViewState } from "../agui/state";

interface ActionControlsProps {
  activeAction: AgentDeskAction["type"] | null;
  agents: AgentDeskViewState["agents"];
  analysis: AgentDeskViewState["analysis"];
  availableActions: AgentDeskViewState["availableActions"];
  isBusy: boolean;
  onCancel(): void;
  onChallenge(challenge: string | null): Promise<boolean>;
  onFocusCriterion(criterion: string): Promise<boolean>;
  onResearchDeeper(focusAreas: string[]): Promise<boolean>;
  onRetryAgent(agentId: string, remoteTaskId: string | null): Promise<boolean>;
}

const ACTION_LABELS: Record<AgentDeskAction["type"], string> = {
  start_research: "Starting research",
  challenge_recommendation: "Testing counterargument",
  research_deeper: "Researching deeper",
  focus_on_criterion: "Refocusing analysis",
  retry_failed_agent: "Retrying specialist",
};

export function ActionControls({
  activeAction,
  agents,
  analysis,
  availableActions,
  isBusy,
  onCancel,
  onChallenge,
  onFocusCriterion,
  onResearchDeeper,
  onRetryAgent,
}: ActionControlsProps) {
  const [challenge, setChallenge] = useState("");
  const [criterion, setCriterion] = useState(analysis?.criteria[0]?.criterion ?? "");
  const suggestedCriterion = analysis?.criteria[0]?.criterion ?? "";
  const failedAgents = agents.filter((agent) => agent.status === "failed");
  const actions = new Set(availableActions);

  useEffect(() => {
    if (suggestedCriterion) {
      setCriterion((current) => current || suggestedCriterion);
    }
  }, [suggestedCriterion]);

  if (!isBusy && availableActions.length === 0) {
    return null;
  }

  return (
    <section className="action-controls" aria-labelledby="action-controls-title" aria-busy={isBusy}>
      <div className="action-controls__heading">
        <div>
          <p className="eyebrow">Next actions</p>
          <h3 id="action-controls-title">Continue this research</h3>
        </div>
        {activeAction !== null && <span>{ACTION_LABELS[activeAction]}…</span>}
      </div>

      {isBusy ? (
        <div className="active-run-control">
          <div>
            <strong>Coordinator run in progress</strong>
            <p>Only one action can run at a time. You can safely stop the active run.</p>
          </div>
          <button className="action-button action-button--danger" type="button" onClick={onCancel}>
            Cancel active run
          </button>
        </div>
      ) : (
        <div className="action-control-grid">
          {actions.has("challenge_recommendation") && (
            <article className="action-control-card">
              <div>
                <h4>Challenge recommendation</h4>
                <p>Ask the Analyst to test a counterargument or weakness.</p>
              </div>
              <label htmlFor="recommendation-challenge">Optional challenge</label>
              <input
                id="recommendation-challenge"
                value={challenge}
                onChange={(event) => setChallenge(event.target.value)}
                placeholder="e.g. What if flexibility matters more?"
              />
              <button
                className="action-button"
                type="button"
                onClick={() => void onChallenge(challenge.trim() || null)}
              >
                Test counterargument
              </button>
            </article>
          )}

          {actions.has("research_deeper") && (
            <article className="action-control-card">
              <div>
                <h4>Research deeper</h4>
                <p>Start a deeper pass while keeping this session and thread.</p>
              </div>
              <button
                className="action-button"
                type="button"
                onClick={() => void onResearchDeeper([])}
              >
                Deepen research
              </button>
            </article>
          )}

          {actions.has("focus_on_criterion") && (
            <article className="action-control-card">
              <div>
                <h4>Focus on a criterion</h4>
                <p>Reweight attention toward one decision criterion.</p>
              </div>
              <label htmlFor="focus-criterion">Criterion</label>
              <input
                id="focus-criterion"
                list="criterion-suggestions"
                value={criterion}
                onChange={(event) => setCriterion(event.target.value)}
                placeholder="Enter a decision criterion"
              />
              <datalist id="criterion-suggestions">
                {analysis?.criteria.map((item) => (
                  <option value={item.criterion} key={item.criterion} />
                ))}
              </datalist>
              <button
                className="action-button"
                type="button"
                disabled={!criterion.trim()}
                onClick={() => void onFocusCriterion(criterion)}
              >
                Focus analysis
              </button>
            </article>
          )}

          {actions.has("retry_failed_agent") && (
            <article className="action-control-card action-control-card--retry">
              <div>
                <h4>Retry a specialist</h4>
                <p>Retry only a failed task; completed specialist work is preserved.</p>
              </div>
              {failedAgents.length === 0 ? (
                <p className="action-unavailable">No failed specialist is available to retry.</p>
              ) : (
                <ul className="retry-agent-list">
                  {failedAgents.map((agent) => (
                    <li key={agent.agentId}>
                      <span><strong>{agent.name}</strong><small>{agent.message}</small></span>
                      <button
                        className="action-button"
                        type="button"
                        onClick={() => void onRetryAgent(agent.agentId, agent.remoteTaskId)}
                      >
                        Retry
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          )}
        </div>
      )}
    </section>
  );
}
