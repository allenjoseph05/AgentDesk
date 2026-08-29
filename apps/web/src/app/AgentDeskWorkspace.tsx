import { type FormEvent, useState } from "react";

import {
  selectActions,
  selectAgents,
  selectAnalysis,
  selectClaims,
  selectEvidence,
  selectRecommendationChallenge,
  selectSession,
  selectVerification,
  selectWarnings,
} from "../agui/selectors";
import { useAgentDeskSelector } from "../agui/store-react";
import { TrustedA2uiIntake } from "../a2ui/renderer";
import { agentDeskComponentCatalog } from "../components/catalog";
import { useAgentDeskRuntime } from "./AgentDeskRuntime";
import {
  ADAPTIVE_DEMO_RESEARCH_QUESTION,
  adaptiveIntakeEnabled,
  agentDeskRuntimeMode,
  DEMO_RESEARCH_PARAMETERS,
  DEMO_RESEARCH_QUESTION,
} from "./runtime-mode";

const QUICK_STARTS = [
  "Compare PostgreSQL and MongoDB for our product",
  "Research the best deployment path for this application",
] as const;

const { ActionControls, ActivityTimeline, ResearchResults, ResearchStatusPanel } =
  agentDeskComponentCatalog;

const STATUS_LABELS = {
  idle: "Ready",
  created: "Queued",
  scoping: "Scoping",
  awaiting_input: "Needs input",
  planning: "Planning",
  researching: "Researching",
  analyzing: "Analyzing",
  verifying: "Verifying",
  cancelling: "Cancelling",
  completed: "Complete",
  cancelled: "Cancelled",
  failed: "Needs attention",
  partial: "Partially complete",
} as const;

export function AgentDeskWorkspace() {
  const runtime = useAgentDeskRuntime();
  const session = useAgentDeskSelector(selectSession);
  const agents = useAgentDeskSelector(selectAgents);
  const evidence = useAgentDeskSelector(selectEvidence);
  const claims = useAgentDeskSelector(selectClaims);
  const analysis = useAgentDeskSelector(selectAnalysis);
  const recommendationChallenge = useAgentDeskSelector(selectRecommendationChallenge);
  const verification = useAgentDeskSelector(selectVerification);
  const warnings = useAgentDeskSelector(selectWarnings);
  const availableActions = useAgentDeskSelector(selectActions);
  const isDemoMode = agentDeskRuntimeMode === "demo";
  const isAdaptiveDemoMode = agentDeskRuntimeMode === "adaptive-demo";
  const isFixtureMode = isDemoMode || isAdaptiveDemoMode;
  const fixtureQuestion = isAdaptiveDemoMode
    ? ADAPTIVE_DEMO_RESEARCH_QUESTION
    : DEMO_RESEARCH_QUESTION;
  const [question, setQuestion] = useState(isFixtureMode ? fixtureQuestion : "");
  const [showDirectFallback, setShowDirectFallback] = useState(false);
  const [directOptions, setDirectOptions] = useState(
    isAdaptiveDemoMode ? DEMO_RESEARCH_PARAMETERS.options.join(", ") : "",
  );
  const [directCriteria, setDirectCriteria] = useState(
    isAdaptiveDemoMode ? DEMO_RESEARCH_PARAMETERS.criteria.join(", ") : "",
  );
  const [directConstraints, setDirectConstraints] = useState(
    isAdaptiveDemoMode ? DEMO_RESEARCH_PARAMETERS.constraints.join(", ") : "",
  );
  const isBusy = runtime.phase === "connecting" || runtime.phase === "running";
  const hasSession = session !== null;
  const activeSessionId = session?.sessionId ?? "";
  const status = session?.status ?? "idle";
  const isIntakePending = status === "awaiting_input";
  const composerDisabled = isBusy || isIntakePending;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!composerDisabled && question.trim()) {
      void runtime.startResearch(question);
    }
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#research-workspace">
        Skip to research workspace
      </a>

      <aside className="history-rail" aria-label="Research history">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            AD
          </span>
          <div>
            <span className="brand-name">AgentDesk</span>
            <span className="brand-caption">Research workspace</span>
          </div>
        </div>

        <button
          className="new-research-button"
          type="button"
          onClick={() => setQuestion(isFixtureMode ? fixtureQuestion : "")}
        >
          <span aria-hidden="true">+</span>
          New research
        </button>

        <nav className="history-nav" aria-labelledby="history-title">
          <div className="section-heading">
            <h2 id="history-title">Research history</h2>
            <span>{runtime.history.length}</span>
          </div>
          {runtime.history.length > 0 ? (
            runtime.history.map((item) => (
              <button
                aria-current={item.sessionId === activeSessionId ? "page" : undefined}
                className={`history-entry${item.sessionId === activeSessionId ? " history-entry--active" : ""}`}
                key={item.sessionId}
                onClick={() => void runtime.rehydrateSession(item.sessionId)}
                type="button"
              >
                <span className="history-entry__status" aria-hidden="true" />
                <span>
                  <strong>{item.question}</strong>
                  <span>{STATUS_LABELS[item.status]}</span>
                </span>
              </button>
            ))
          ) : (
            <div className="history-empty">
              <span aria-hidden="true">⌁</span>
              <p>Your completed research sessions will collect here.</p>
            </div>
          )}
        </nav>

        <div className="rail-footer">
          <span className="connection-dot" aria-hidden="true" />
          <div>
            <strong>AG-UI workspace</strong>
            <span title={runtime.threadId}>Thread ready</span>
          </div>
        </div>
      </aside>

      <main className="workspace" id="research-workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Multi-agent decision support</p>
            <h1>What should we investigate?</h1>
          </div>
          <div className="workspace-header__status">
            <span className={`runtime-mode runtime-mode--${agentDeskRuntimeMode}`}>
              {isDemoMode
                ? "Fixture demo"
                : isAdaptiveDemoMode
                  ? "Adaptive fixture"
                  : "Live mode"}
            </span>
            <div className="workspace-status" data-phase={runtime.phase}>
              <span aria-hidden="true" />
              {isBusy ? "Agents working" : "Workspace ready"}
            </div>
          </div>
        </header>

        <form className="research-composer" onSubmit={submit} aria-busy={isBusy}>
          <label htmlFor="research-question">Research question</label>
          <div className="composer-field">
            <textarea
              id="research-question"
              name="research-question"
              rows={3}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a complex question, compare options, or investigate a decision..."
              disabled={composerDisabled}
              readOnly={isFixtureMode}
            />
            <button type="submit" disabled={composerDisabled || !question.trim()}>
              {isBusy ? "Researching..." : "Start research"}
              <span aria-hidden="true">→</span>
            </button>
          </div>
          {isFixtureMode && (
            <p className="demo-notice" role="status">
              {isAdaptiveDemoMode
                ? "Adaptive fixture mode uses the real ADK, A2A, A2UI, and AG-UI path with deterministic local data. No live model or research provider is contacted."
                : "Recording mode uses fixed local fixtures and predictable stage timing. No live model or research provider is contacted."}
            </p>
          )}
          {!hasSession && !isFixtureMode && (
            <section
              className="quick-starts"
              aria-label="Example research questions"
            >
              <span>Try asking</span>
              {QUICK_STARTS.map((suggestion) => (
                <button key={suggestion} type="button" onClick={() => setQuestion(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </section>
          )}
        </form>

        {runtime.error !== null && (
          <section className="runtime-alert" role="alert">
            <div>
              <strong>Research connection failed</strong>
              <p>{runtime.error}</p>
            </div>
            <div>
              <button type="button" onClick={() => void runtime.startResearch(question)}>
                Try again
              </button>
              {adaptiveIntakeEnabled && (
                <button type="button" onClick={() => setShowDirectFallback(true)}>
                  Use direct form
                </button>
              )}
            </div>
          </section>
        )}

        {showDirectFallback && (
          <form
            className="direct-fallback"
            onSubmit={(event) => {
              event.preventDefault();
              const options = commaSeparatedValues(directOptions);
              const criteria = commaSeparatedValues(directCriteria);
              if (options.length < 2 || criteria.length === 0) return;
              void runtime.startDirectResearch(question, {
                options,
                constraints: commaSeparatedValues(directConstraints),
                criteria,
                desiredDepth: "normal",
              });
            }}
          >
            <h2>Continue without adaptive scoping</h2>
            <p>Enter a bounded decision request directly. This path does not call the scoper.</p>
            <label htmlFor="direct-options">Options, separated by commas</label>
            <input
              id="direct-options"
              onChange={(event) => setDirectOptions(event.target.value)}
              required
              value={directOptions}
            />
            <label htmlFor="direct-criteria">Decision criteria, separated by commas</label>
            <input
              id="direct-criteria"
              onChange={(event) => setDirectCriteria(event.target.value)}
              required
              value={directCriteria}
            />
            <label htmlFor="direct-constraints">Constraints, separated by commas</label>
            <input
              id="direct-constraints"
              onChange={(event) => setDirectConstraints(event.target.value)}
              value={directConstraints}
            />
            <button disabled={isBusy} type="submit">Start direct research</button>
          </form>
        )}

        <section
          className="state-surface"
          aria-label="Research state"
          aria-live="polite"
          data-surface="agentdesk-state"
        >
          <div className="state-surface__header">
            <div>
              <p className="eyebrow">
                {isDemoMode
                  ? "Fixture demo workspace"
                  : isAdaptiveDemoMode
                    ? "Adaptive fixture workspace"
                    : "Live workspace"}
              </p>
              <h2>{session?.question ?? "Your research will take shape here"}</h2>
            </div>
            <span className={`state-pill state-pill--${status}`}>
              {STATUS_LABELS[status]}
            </span>
          </div>

          {hasSession ? (
            <>
              {runtime.intakeSurface !== null && isIntakePending && (
                <TrustedA2uiIntake
                  busy={isBusy}
                  onSkip={runtime.skipIntake}
                  onSubmit={runtime.submitIntake}
                  surface={runtime.intakeSurface}
                />
              )}
              <ResearchStatusPanel
                agents={agents}
                evidenceCount={evidence.length}
                message={runtime.message}
                session={session}
              />
              <ResearchResults
                analysis={analysis}
                claims={claims}
                evidence={evidence}
                recommendationChallenge={recommendationChallenge}
                verification={verification}
                warnings={warnings}
              />
            </>
          ) : (
            <div className="state-empty">
              <div className="state-empty__graphic" aria-hidden="true">
                <span />
                <span />
                <span />
                <i />
              </div>
              <h3>One question, a coordinated team</h3>
              <p>
                Submit a research question to see planning, specialist activity, evidence,
                and analysis in one focused surface.
              </p>
              <section
                className="capability-row"
                aria-label="Workspace capabilities"
              >
                <span>Plan</span>
                <i aria-hidden="true" />
                <span>Research</span>
                <i aria-hidden="true" />
                <span>Analyze</span>
                <i aria-hidden="true" />
                <span>Verify</span>
              </section>
            </div>
          )}
          <ActivityTimeline agents={agents} items={runtime.timeline} />
          <ActionControls
            activeAction={runtime.activeAction}
            agents={agents}
            analysis={analysis}
            availableActions={availableActions}
            isBusy={isBusy}
            onCancel={runtime.cancelRun}
            onChallenge={(challenge) =>
              runtime.challengeRecommendation(activeSessionId, challenge)
            }
            onFocusCriterion={(criterion) =>
              runtime.focusOnCriterion(activeSessionId, criterion)
            }
            onResearchDeeper={(focusAreas) =>
              runtime.researchDeeper(activeSessionId, focusAreas)
            }
            onRetryAgent={(agentId, remoteTaskId) =>
              runtime.retryFailedAgent(activeSessionId, agentId, remoteTaskId)
            }
          />
        </section>
      </main>
    </div>
  );
}

function commaSeparatedValues(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ).slice(0, 20);
}
