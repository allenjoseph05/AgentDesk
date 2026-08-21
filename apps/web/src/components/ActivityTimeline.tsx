import type { AgentDeskViewState } from "../agui/state";
import { semanticLabel, type TimelineItem } from "../agui/timeline";

interface ActivityTimelineProps {
  agents: AgentDeskViewState["agents"];
  items: TimelineItem[];
}

const ACTIVITY_STATUS_LABELS = {
  working: "Working",
  waiting: "Waiting",
  completed: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
} as const;

export function ActivityTimeline({ agents, items }: ActivityTimelineProps) {
  if (items.length === 0) {
    return null;
  }
  const agentNames = new Map(agents.map((agent) => [agent.agentId, agent.name]));

  return (
    <section className="activity-timeline" aria-labelledby="activity-timeline-title">
      <div className="timeline-heading">
        <div>
          <p className="eyebrow">Run narrative</p>
          <h3 id="activity-timeline-title">Messages and activity</h3>
        </div>
        <span>{items.length} updates</span>
      </div>
      <ol className="timeline-list" aria-live="polite">
        {items.map((item) => (
          <li
            data-kind={item.kind}
            data-run-id={item.runId}
            data-status={item.status}
            key={item.id}
          >
            <span className="timeline-marker" aria-hidden="true"><i /></span>
            {item.kind === "message" && (
              <article className="timeline-message">
                <div className="timeline-item-heading">
                  <strong>{item.role === "assistant" ? "Coordinator" : "You"}</strong>
                  {item.status === "streaming" && <span>Writing…</span>}
                </div>
                <p>{item.content || "Preparing an update…"}</p>
              </article>
            )}
            {item.kind === "step" && (
              <article className="timeline-step">
                <div className="timeline-item-heading">
                  <strong>{item.label}</strong>
                  <span>{item.status === "active" ? "In progress" : "Complete"}</span>
                </div>
                <p>Coordinator workflow step</p>
              </article>
            )}
            {item.kind === "activity" && (
              <article
                className="timeline-specialist-activity"
                data-agent-id={item.agentId ?? undefined}
              >
                <div className="timeline-item-heading">
                  <strong>
                    {item.agentId === null
                      ? "Specialist activity"
                      : agentNames.get(item.agentId) ?? item.agentId}
                  </strong>
                  <span>{ACTIVITY_STATUS_LABELS[item.status]}</span>
                </div>
                <p>{item.summary}</p>
                <small>{semanticLabel(item.activityType)}</small>
              </article>
            )}
            <span className="timeline-correlation" title={`Run ${item.runId}`}>
              Run {shortId(item.runId)}
            </span>
          </li>
        ))}
      </ol>
      <p className="timeline-safety-note">
        This timeline contains user-safe run events and specialist summaries, not private model
        reasoning.
      </p>
    </section>
  );
}

function shortId(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value;
}
