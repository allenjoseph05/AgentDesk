import { useRef, useState } from "react";

import { createCoordinatorAgent, runResearch } from "../agui/client";
import { INITIAL_AGENTDESK_STATE, type AgentDeskViewState } from "../agui/state";

const plannedServices = ["Research", "Analyst", "Verifier"] as const;

function AgUiProtocolSpike() {
  const agentRef = useRef<ReturnType<typeof createCoordinatorAgent> | null>(null);
  agentRef.current ??= createCoordinatorAgent();
  const [question, setQuestion] = useState("Should we use PostgreSQL or MongoDB?");
  const [viewState, setViewState] = useState<AgentDeskViewState>(INITIAL_AGENTDESK_STATE);
  const [message, setMessage] = useState("Ready to start an AG-UI run.");
  const [running, setRunning] = useState(false);

  const submit = async () => {
    setRunning(true);
    setMessage("Connecting to the Coordinator...");
    try {
      await runResearch(agentRef.current!, question, {
        onState: setViewState,
        onMessage: setMessage,
        onFinished: () => setRunning(false),
        onCancelled: () => {
          setMessage("AG-UI stream cancelled.");
          setRunning(false);
        },
        onError: (error) => {
          setMessage(error);
          setRunning(false);
        },
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "AG-UI run failed.");
      setRunning(false);
    }
  };

  return (
    <section className="agui-spike" aria-labelledby="agui-title">
      <div className="agui-spike__header">
        <div>
          <p className="eyebrow">AD-006 · AG-UI vertical slice</p>
          <h2 id="agui-title">Browser-to-Coordinator event stream</h2>
        </div>
        <span className="status-badge">{viewState.status}</span>
      </div>
      <label className="research-input">
        Research question
        <input value={question} onChange={(event) => setQuestion(event.target.value)} />
      </label>
      <div className="agui-spike__actions">
        <button type="button" onClick={() => void submit()} disabled={running}>
          {running ? "Running…" : "Start AG-UI run"}
        </button>
        <button
          type="button"
          onClick={() => agentRef.current?.abortRun()}
          disabled={!running}
        >
          Cancel stream
        </button>
      </div>
      <div className="agui-spike__state" aria-live="polite">
        <p>{message}</p>
        <dl>
          <div>
            <dt>Thread</dt>
            <dd>{agentRef.current.threadId}</dd>
          </div>
          <div>
            <dt>Run/session</dt>
            <dd>{viewState.sessionId ?? "Not started"}</dd>
          </div>
          <div>
            <dt>Active step</dt>
            <dd>{viewState.activeStep ?? "None"}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

export function App() {
  return (
    <main className="page-shell">
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">Adaptive research workspace</p>
        <h1 id="page-title">AgentDesk</h1>
        <p className="lede">
          AG-UI connects this workspace to the Coordinator; A2A connects the Coordinator to
          independently deployed specialist agents.
        </p>
      </section>

      <section className="status-panel" aria-labelledby="status-title">
        <div>
          <p className="eyebrow">Protocol foundation</p>
          <h2 id="status-title">AG-UI + A2A</h2>
        </div>
        <span className="status-badge">Connected architecture</span>
      </section>

      <section className="service-grid" aria-label="Planned specialist services">
        {plannedServices.map((service) => (
          <article className="service-card" key={service}>
            <span className="service-dot" aria-hidden="true" />
            <div>
              <h2>{service} Agent</h2>
              <p>Independent A2A service boundary.</p>
            </div>
          </article>
        ))}
      </section>

      <AgUiProtocolSpike />
    </main>
  );
}
