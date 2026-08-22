import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureRoot = new URL("../../../fixtures/agui/", import.meta.url);

async function loadFixture(name) {
  return JSON.parse(await readFile(new URL(name, fixtureRoot), "utf8"));
}

async function renderResults(state) {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const [{ ResearchResults }, { parseAgentDeskViewState }] = await Promise.all([
      vite.ssrLoadModule("/src/components/ResearchResults.tsx"),
      vite.ssrLoadModule("/src/agui/state.ts"),
    ]);
    const parsed = parseAgentDeskViewState(state);
    return renderToStaticMarkup(
      createElement(ResearchResults, {
        analysis: parsed.analysis,
        claims: parsed.claims,
        evidence: parsed.evidence,
        recommendationChallenge: parsed.recommendationChallenge,
        verification: parsed.verification,
        warnings: parsed.warnings,
      }),
    );
  } finally {
    await vite.close();
  }
}

test("golden results render recommendation, comparison, evidence, boundaries, and verification", async () => {
  const fixture = await loadFixture("postgresql-vs-mongodb.golden.json");
  const markup = await renderResults(fixture.state);

  assert.match(markup, /<h4>PostgreSQL<\/h4>/u);
  assert.match(markup, /Option comparison/u);
  assert.match(markup, /Data integrity/u);
  assert.match(markup, /PostgreSQL integrity fixture/u);
  assert.match(markup, /Grounded findings/u);
  assert.match(markup, /Risks/u);
  assert.match(markup, /Assumptions/u);
  assert.match(markup, /Reconsider the recommendation if/u);
  assert.match(markup, /data-verdict="supported"/u);
  assert.match(markup, /Decision criteria and option scores/u);
});

test("counteranalysis appears from a live recommendation challenge state update", async () => {
  const fixture = await loadFixture("postgresql-vs-mongodb.golden.json");
  fixture.state.recommendationChallenge = {
    currentRecommendation: "PostgreSQL",
    strongestAlternative: "MongoDB",
    strongestCounterargument: "Document-first writes may outweigh relational guarantees.",
    supportingClaimIds: ["claim-mongo"],
    assumptions: ["Relational joins remain central."],
    evidenceGaps: ["No production write benchmark."],
    recommendationChangesIf: ["Independent document writes become dominant."],
  };

  const markup = await renderResults(fixture.state);

  assert.match(markup, /Recommendation challenged/u);
  assert.match(markup, /Strongest alternative: MongoDB/u);
  assert.match(markup, /Document-first writes may outweigh relational guarantees/u);
  assert.match(markup, /No production write benchmark/u);
});

test("partial results retain evidence and identify missing analysis and verification", async () => {
  const fixture = await loadFixture("postgresql-vs-mongodb.partial.json");
  const markup = await renderResults(fixture.state);

  assert.match(markup, /Review before deciding/u);
  assert.match(markup, /MongoDB evidence and operational cost data are unavailable/u);
  assert.match(markup, /Analysis is not available yet/u);
  assert.match(markup, /Partial fixture/u);
  assert.match(markup, /MongoDB evidence is unavailable/u);
  assert.match(markup, /Verification pending/u);
  assert.doesNotMatch(markup, /Option comparison/u);
});

test("contradictory results expose unresolved verification without hiding claims", async () => {
  const fixture = await loadFixture("postgresql-vs-mongodb.contradictory.json");
  const markup = await renderResults(fixture.state);

  assert.match(markup, /The available sources contradict each other/u);
  assert.match(markup, /PostgreSQL has lower p95 latency/u);
  assert.match(markup, /MongoDB has lower p95 latency/u);
  assert.match(markup, /data-verdict="insufficient_evidence"/u);
  assert.match(markup, /The competing benchmark prevents a verdict/u);
});

test("every verification verdict is visible and contradictions retain the warning panel", async () => {
  const fixture = await loadFixture("postgresql-vs-mongodb.golden.json");
  const base = fixture.state.verification.results[0];
  fixture.state.verification.results = [
    { ...base, claimId: "claim-supported", verdict: "supported" },
    { ...base, claimId: "claim-partial", verdict: "partially_supported" },
    { ...base, claimId: "claim-contradicted", verdict: "contradicted" },
    { ...base, claimId: "claim-insufficient", verdict: "insufficient_evidence" },
  ];
  fixture.state.warnings = [
    "Verification contradiction for claim claim-contradicted: Evidence conflicts.",
  ];

  const markup = await renderResults(fixture.state);

  assert.match(markup, /data-verdict="supported"/u);
  assert.match(markup, /data-verdict="partially_supported"/u);
  assert.match(markup, /data-verdict="contradicted"/u);
  assert.match(markup, /data-verdict="insufficient_evidence"/u);
  assert.match(markup, />Partially supported</u);
  assert.match(markup, />Contradicted</u);
  assert.match(markup, />Insufficient evidence</u);
  assert.match(markup, /Review before deciding/u);
  assert.match(markup, /Verification contradiction for claim claim-contradicted/u);
});

test("empty and long linked evidence layouts remain explicit and safe", async () => {
  const failure = await loadFixture("postgresql-vs-mongodb.failure.json");
  const emptyMarkup = await renderResults(failure.state);
  assert.match(emptyMarkup, /No result artifacts yet/u);

  const longTitle = "A very long evidence title ".repeat(15).trim();
  const longUrl = `https://example.com/${"long-path-segment/".repeat(20)}`;
  const partial = await loadFixture("postgresql-vs-mongodb.partial.json");
  partial.state.evidence[0].title = longTitle;
  partial.state.evidence[0].sourceUrl = longUrl;
  const longMarkup = await renderResults(partial.state);
  assert.match(longMarkup, new RegExp(longTitle, "u"));
  assert.match(longMarkup, /target="_blank" rel="noopener noreferrer"/u);
  assert.match(longMarkup, /opens source/u);

  const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
  assert.match(styles, /\.evidence-list h5[\s\S]*?overflow-wrap: anywhere/u);
  assert.match(styles, /\.evidence-list article > p[\s\S]*?overflow-wrap: anywhere/u);
  assert.match(styles, /\.comparison-scroll[\s\S]*?overflow-x: auto/u);
});
