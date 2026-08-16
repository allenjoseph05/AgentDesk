import { useRef } from "react";

import { A2uiSurface } from "../a2ui/compatibility";
import {
  createFixtureRuntime,
  type FixtureRuntime,
  updateFixtureSummary,
} from "../a2ui/fixture-surface";

const plannedServices = ["Research", "Analyst", "Verifier"] as const;

function A2uiRendererSpike() {
  const runtimeRef = useRef<FixtureRuntime | null>(null);
  runtimeRef.current ??= createFixtureRuntime();
  const runtime = runtimeRef.current;

  const applyDataUpdate = () => {
    updateFixtureSummary(runtime.processor, "Data model updated without remounting AgentDesk.");
  };

  return (
    <section className="a2ui-spike" aria-labelledby="a2ui-title">
      <div className="a2ui-spike__header">
        <div>
          <p className="eyebrow">AD-005 · A2UI v0.9.1</p>
          <h2 id="a2ui-title">Local renderer proof</h2>
        </div>
        <button type="button" onClick={applyDataUpdate}>
          Update data model
        </button>
      </div>
      <div className="a2ui-spike__surface" data-surface-id={runtime.surface.id}>
        <A2uiSurface surface={runtime.surface} />
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
          The development foundation is ready. A2A protocol discovery and streaming are the
          next gated implementation step.
        </p>
      </section>

      <section className="status-panel" aria-labelledby="status-title">
        <div>
          <p className="eyebrow">AD-001</p>
          <h2 id="status-title">Workspace initialized</h2>
        </div>
        <span className="status-badge">Foundation</span>
      </section>

      <section className="service-grid" aria-label="Planned specialist services">
        {plannedServices.map((service) => (
          <article className="service-card" key={service}>
            <span className="service-dot" aria-hidden="true" />
            <div>
              <h2>{service} Agent</h2>
              <p>Independent service boundary reserved.</p>
            </div>
          </article>
        ))}
      </section>

      <A2uiRendererSpike />
    </main>
  );
}
