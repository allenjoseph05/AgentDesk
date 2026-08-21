import type { AgentDeskViewState } from "../agui/state";

type Analysis = NonNullable<AgentDeskViewState["analysis"]>;
type Claim = AgentDeskViewState["claims"][number];
type Evidence = AgentDeskViewState["evidence"][number];
type Verification = NonNullable<AgentDeskViewState["verification"]>;
type VerificationResult = Verification["results"][number];

interface ResearchResultsProps {
  analysis: AgentDeskViewState["analysis"];
  claims: AgentDeskViewState["claims"];
  evidence: AgentDeskViewState["evidence"];
  recommendationChallenge: AgentDeskViewState["recommendationChallenge"];
  verification: AgentDeskViewState["verification"];
  warnings: AgentDeskViewState["warnings"];
}

const VERDICT_PRESENTATION = {
  supported: { label: "Supported", tone: "success" },
  partially_supported: { label: "Partially supported", tone: "warning" },
  contradicted: { label: "Contradicted", tone: "danger" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "neutral" },
} as const satisfies Record<
  VerificationResult["verdict"],
  { label: string; tone: "success" | "warning" | "danger" | "neutral" }
>;

const SOURCE_TYPE_LABELS: Record<Evidence["sourceType"], string> = {
  official_documentation: "Official documentation",
  primary_source: "Primary source",
  secondary_source: "Secondary source",
  user_provided: "User-provided",
  fixture: "Fixture source",
};

export function ResearchResults({
  analysis,
  claims,
  evidence,
  recommendationChallenge = null,
  verification,
  warnings,
}: ResearchResultsProps) {
  const hasArtifacts =
    analysis !== null ||
    recommendationChallenge !== null ||
    evidence.length > 0 ||
    claims.length > 0 ||
    verification !== null;

  if (!hasArtifacts) {
    return (
      <section className="result-empty" aria-labelledby="result-empty-title">
        <span aria-hidden="true">Results</span>
        <div>
          <h3 id="result-empty-title">No result artifacts yet</h3>
          <p>
            Evidence, claims, and decision analysis will appear here as specialists complete
            their work.
          </p>
          <WarningList warnings={warnings} />
        </div>
      </section>
    );
  }

  const evidenceById = new Map(evidence.map((item) => [item.id, item]));
  const verificationByClaim = new Map(
    verification?.results.map((result) => [result.claimId, result]) ?? [],
  );

  return (
    <section className="research-results" aria-labelledby="research-results-title">
      <div className="result-heading">
        <div>
          <p className="eyebrow">Decision brief</p>
          <h3 id="research-results-title">Research results</h3>
        </div>
        <span>{evidence.length} sources</span>
      </div>

      <WarningList warnings={warnings} />

      {recommendationChallenge !== null && (
        <CounteranalysisCard challenge={recommendationChallenge} />
      )}

      {analysis === null ? (
        <section className="analysis-empty" aria-labelledby="analysis-empty-title">
          <div aria-hidden="true">i</div>
          <div>
            <h4 id="analysis-empty-title">Analysis is not available yet</h4>
            <p>
              The evidence collected so far remains available below. Treat it as partial until
              the comparison and recommendation are complete.
            </p>
          </div>
        </section>
      ) : (
        <>
          <RecommendationCard analysis={analysis} />
          <ComparisonTable analysis={analysis} />
          <DecisionBoundaries analysis={analysis} />
        </>
      )}

      <div className="result-grid">
        <EvidenceList evidence={evidence} />
        <ClaimList
          claims={claims}
          evidenceById={evidenceById}
          verificationByClaim={verificationByClaim}
        />
      </div>

      <VerificationPanel claims={claims} verification={verification} />
    </section>
  );
}

function CounteranalysisCard({
  challenge,
}: {
  challenge: NonNullable<AgentDeskViewState["recommendationChallenge"]>;
}) {
  return (
    <article className="counteranalysis-card" aria-labelledby="counteranalysis-title">
      <div>
        <p className="eyebrow">Recommendation challenged</p>
        <h4 id="counteranalysis-title">
          Strongest alternative: {challenge.strongestAlternative}
        </h4>
        <p>{challenge.strongestCounterargument}</p>
      </div>
      <div className="counteranalysis-details">
        <section>
          <h5>Assumptions under pressure</h5>
          <ul>
            {challenge.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </section>
        <section>
          <h5>The recommendation changes if</h5>
          <ul>
            {challenge.recommendationChangesIf.map((condition) => (
              <li key={condition}>{condition}</li>
            ))}
          </ul>
        </section>
      </div>
      {challenge.evidenceGaps.length > 0 && (
        <p className="counteranalysis-gaps">
          Evidence gaps: {challenge.evidenceGaps.join("; ")}
        </p>
      )}
    </article>
  );
}

function WarningList({ warnings }: { warnings: AgentDeskViewState["warnings"] }) {
  if (warnings.length === 0) {
    return null;
  }
  return (
    <aside className="result-warnings" aria-label="Research warnings">
      <strong>Review before deciding</strong>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </aside>
  );
}

function RecommendationCard({ analysis }: { analysis: Analysis }) {
  return (
    <article className="recommendation-card">
      <div className="recommendation-mark" aria-hidden="true">
        <span />
      </div>
      <div>
        <p className="eyebrow">Recommendation</p>
        <h4>{analysis.recommendation}</h4>
        <p>{analysis.executiveSummary}</p>
      </div>
    </article>
  );
}

function ComparisonTable({ analysis }: { analysis: Analysis }) {
  const options = Array.from(
    new Set(analysis.criteria.flatMap((criterion) => Object.keys(criterion.scores))),
  );
  return (
    <section className="comparison-section" aria-labelledby="comparison-title">
      <div className="result-section-heading">
        <div>
          <p className="eyebrow">Weighted assessment</p>
          <h4 id="comparison-title">Option comparison</h4>
        </div>
        <span>Scores out of 10</span>
      </div>
      <div className="comparison-scroll" tabIndex={0}>
        <table>
          <caption>Decision criteria and option scores</caption>
          <thead>
            <tr>
              <th scope="col">Criterion</th>
              <th scope="col">Weight</th>
              {options.map((option) => (
                <th scope="col" key={option}>{option}</th>
              ))}
              <th scope="col">Rationale</th>
            </tr>
          </thead>
          <tbody>
            {analysis.criteria.map((criterion) => (
              <tr key={criterion.criterion}>
                <th scope="row">{criterion.criterion}</th>
                <td>{formatPercent(criterion.weight)}</td>
                {options.map((option) => (
                  <td className="comparison-score" key={option}>
                    {criterion.scores[option] ?? "—"}
                  </td>
                ))}
                <td>{criterion.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DecisionBoundaries({ analysis }: { analysis: Analysis }) {
  const groups = [
    { title: "Why this fits", items: analysis.argumentsFor, tone: "positive" },
    { title: "Tradeoffs", items: analysis.argumentsAgainst, tone: "neutral" },
    { title: "Risks", items: analysis.risks, tone: "risk" },
    { title: "Assumptions", items: analysis.assumptions, tone: "assumption" },
  ] as const;
  return (
    <section className="decision-boundaries" aria-labelledby="decision-boundaries-title">
      <div className="result-section-heading">
        <div>
          <p className="eyebrow">Decision boundaries</p>
          <h4 id="decision-boundaries-title">Benefits, tradeoffs, and conditions</h4>
        </div>
      </div>
      <div className="boundary-grid">
        {groups.map((group) => (
          <article data-tone={group.tone} key={group.title}>
            <h5>{group.title}</h5>
            <ul>
              {group.items.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </article>
        ))}
      </div>
      <article className="change-conditions">
        <h5>Reconsider the recommendation if</h5>
        <ul>
          {analysis.recommendationChangesIf.map((condition) => (
            <li key={condition}>{condition}</li>
          ))}
        </ul>
      </article>
    </section>
  );
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return (
    <section className="evidence-section" aria-labelledby="evidence-title">
      <div className="result-section-heading">
        <div>
          <p className="eyebrow">Source material</p>
          <h4 id="evidence-title">Evidence</h4>
        </div>
        <span>{evidence.length}</span>
      </div>
      {evidence.length === 0 ? (
        <p className="artifact-empty">No evidence has been accepted for this session.</p>
      ) : (
        <ol className="evidence-list">
          {evidence.map((item) => (
            <li key={item.id}>
              <article>
                <div className="evidence-meta">
                  <span>{SOURCE_TYPE_LABELS[item.sourceType]}</span>
                  <span>{relevanceLabel(item.relevance)}</span>
                </div>
                <h5>
                  {item.sourceUrl === null ? item.title : (
                    <a href={item.sourceUrl} target="_blank" rel="noreferrer">
                      {item.title}<span className="external-link-note"> (opens source)</span>
                    </a>
                  )}
                </h5>
                <p>{item.summary}</p>
              </article>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ClaimList({
  claims,
  evidenceById,
  verificationByClaim,
}: {
  claims: Claim[];
  evidenceById: Map<string, Evidence>;
  verificationByClaim: Map<string, VerificationResult>;
}) {
  return (
    <section className="claim-section" aria-labelledby="claims-title">
      <div className="result-section-heading">
        <div>
          <p className="eyebrow">Grounded findings</p>
          <h4 id="claims-title">Claims</h4>
        </div>
        <span>{claims.length}</span>
      </div>
      {claims.length === 0 ? (
        <p className="artifact-empty">No supported claims are available yet.</p>
      ) : (
        <ol className="claim-list">
          {claims.map((claim) => {
            const result = verificationByClaim.get(claim.id);
            return (
              <li key={claim.id}>
                <article>
                  <div className="claim-meta">
                    <span>{claim.confidence === null ? "Uncalibrated" : `${formatPercent(claim.confidence)} confidence`}</span>
                    {result !== undefined && <VerdictChip verdict={result.verdict} />}
                  </div>
                  <h5>{claim.statement}</h5>
                  <p className="claim-sources">
                    Evidence: {claim.evidenceIds.map((id) => evidenceById.get(id)?.title ?? id).join(", ")}
                  </p>
                  {claim.caveats.length > 0 && (
                    <ul className="claim-caveats">
                      {claim.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
                    </ul>
                  )}
                </article>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function VerificationPanel({
  claims,
  verification,
}: {
  claims: Claim[];
  verification: AgentDeskViewState["verification"];
}) {
  if (verification === null) {
    return (
      <section className="verification-empty" aria-labelledby="verification-title">
        <div aria-hidden="true">?</div>
        <div>
          <h4 id="verification-title">Verification pending</h4>
          <p>Claims are visible, but no verification report is available for this result.</p>
        </div>
      </section>
    );
  }
  const claimsById = new Map(claims.map((claim) => [claim.id, claim]));
  return (
    <section className="verification-section" aria-labelledby="verification-title">
      <div className="result-section-heading">
        <div>
          <p className="eyebrow">Quality check</p>
          <h4 id="verification-title">Verification</h4>
        </div>
        <span>{verification.results.length} checks</span>
      </div>
      {verification.results.length === 0 ? (
        <p className="artifact-empty">The verification report contains no claim checks.</p>
      ) : (
        <ul className="verification-list">
          {verification.results.map((result) => (
            <li data-verdict={result.verdict} key={result.claimId}>
              <VerdictChip verdict={result.verdict} />
              <div>
                <h5>{claimsById.get(result.claimId)?.statement ?? result.claimId}</h5>
                <p>{result.rationale}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function VerdictChip({ verdict }: { verdict: VerificationResult["verdict"] }) {
  const presentation = VERDICT_PRESENTATION[verdict];
  return <span className={`verdict-chip verdict-chip--${presentation.tone}`}>{presentation.label}</span>;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function relevanceLabel(relevance: number): string {
  if (relevance >= 0.85) return "High relevance";
  if (relevance >= 0.6) return "Relevant";
  return "Supporting context";
}
