import { type FormEvent, useState } from "react";

import {
  selectAgents,
  selectAnalysis,
  selectClaims,
  selectEvidence,
  selectSession,
  selectVerification,
  selectWarnings,
} from "../agui/selectors";
import { useAgentDeskSelector } from "../agui/store-react";
import { ResearchResults } from "../components/ResearchResults";
import { ResearchStatusPanel } from "../components/ResearchStatusPanel";
import { useAgentDeskRuntime } from "./AgentDeskRuntime";

const QUICK_STARTS = [
  "Compare PostgreSQL and MongoDB for our product",
  "Research the best deployment path for this application",
] as const;

const STATUS_LABELS = {
  idle: "Ready",
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
  const verification = useAgentDeskSelector(selectVerification);
  const warnings = useAgentDeskSelector(selectWarnings);
  const [question, setQuestion] = useState("");
  const isBusy = runtime.phase === "connecting" || runtime.phase === "running";
  const hasSession = session !== null;
  const status = session?.status ?? "idle";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isBusy && question.trim()) {
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

        <button className="new-research-button" type="button" onClick={() => setQuestion("")}>
          <span aria-hidden="true">+</span>
          New research
        </button>

        <nav className="history-nav" aria-labelledby="history-title">
          <div className="section-heading">
            <h2 id="history-title">Research history</h2>
            <span>{hasSession ? "1" : "0"}</span>
          </div>
          {hasSession ? (
            <article className="history-entry history-entry--active" aria-current="page">
              <span className="history-entry__status" aria-hidden="true" />
              <div>
                <strong>{session.question}</strong>
                <span>{STATUS_LABELS[session.status]}</span>
              </div>
            </article>
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
          <div className="workspace-status" data-phase={runtime.phase}>
            <span aria-hidden="true" />
            {isBusy ? "Agents working" : "Workspace ready"}
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
              disabled={isBusy}
            />
            <button type="submit" disabled={isBusy || !question.trim()}>
              {isBusy ? "Researching..." : "Start research"}
              <span aria-hidden="true">→</span>
            </button>
          </div>
          {!hasSession && (
            <div className="quick-starts" aria-label="Example research questions">
              <span>Try asking</span>
              {QUICK_STARTS.map((suggestion) => (
                <button key={suggestion} type="button" onClick={() => setQuestion(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          )}
        </form>

        {runtime.error !== null && (
          <section className="runtime-alert" role="alert">
            <div>
              <strong>Research connection failed</strong>
              <p>{runtime.error}</p>
            </div>
            <button type="button" onClick={() => void runtime.startResearch(question)}>
              Try again
            </button>
          </section>
        )}

        <section
          className="state-surface"
          aria-label="Research state"
          aria-live="polite"
          data-surface="agentdesk-state"
        >
          <div className="state-surface__header">
            <div>
              <p className="eyebrow">Live workspace</p>
              <h2>{session?.question ?? "Your research will take shape here"}</h2>
            </div>
            <span className={`state-pill state-pill--${status}`}>
              {STATUS_LABELS[status]}
            </span>
          </div>

          {hasSession ? (
            <>
              <ResearchStatusPanel
                agents={agents}
                evidenceCount={evidence.length}
                isBusy={isBusy}
                message={runtime.message}
                onCancel={runtime.cancelRun}
                session={session}
              />
              <ResearchResults
                analysis={analysis}
                claims={claims}
                evidence={evidence}
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
              <div className="capability-row" aria-label="Workspace capabilities">
                <span>Plan</span>
                <i aria-hidden="true" />
                <span>Research</span>
                <i aria-hidden="true" />
                <span>Analyze</span>
                <i aria-hidden="true" />
                <span>Verify</span>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
