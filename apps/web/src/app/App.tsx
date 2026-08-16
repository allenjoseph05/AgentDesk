const plannedServices = ["Research", "Analyst", "Verifier"] as const;

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
    </main>
  );
}

