import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { MAX_RENDERED_TEXT_LENGTH } from "../src/agui/state.ts";
import {
	MAX_INTAKE_TEXT_LENGTH,
	parseScopeProposalArtifact,
	validateIntakeResponse,
} from "../src/intake/contracts.ts";

const fixtureRoot = new URL("../../../fixtures/intake/", import.meta.url);
const manifest = JSON.parse(
	readFileSync(new URL("manifest.json", fixtureRoot), "utf8"),
);

function loadFixture(fixtureId) {
	const entry = manifest.fixtures.find(
		(candidate) => candidate.fixture_id === fixtureId,
	);
	assert.ok(entry, `Unknown intake fixture: ${fixtureId}`);
	return JSON.parse(readFileSync(new URL(entry.file, fixtureRoot), "utf8"));
}

for (const entry of manifest.fixtures) {
	test(`validates shared intake fixture: ${entry.fixture_id}`, () => {
		const fixture = loadFixture(entry.fixture_id);
		const artifact = parseScopeProposalArtifact(fixture.artifact);
		const response = validateIntakeResponse(artifact.payload, fixture.response);

		assert.deepEqual(artifact, fixture.artifact);
		assert.deepEqual(response, fixture.response);
	});
}

const malformed = JSON.parse(
	readFileSync(new URL(manifest.malformed_file, fixtureRoot), "utf8"),
);
for (const fixtureCase of malformed.cases) {
	test(`rejects shared malformed intake case: ${fixtureCase.case_id}`, () => {
		const fixture = structuredClone(loadFixture(fixtureCase.fixture_id));
		applyMutations(fixture, fixtureCase.operations);

		if (fixtureCase.target === "artifact") {
			assert.throws(() => parseScopeProposalArtifact(fixture.artifact));
			return;
		}
		const artifact = parseScopeProposalArtifact(fixture.artifact);
		assert.throws(() =>
			validateIntakeResponse(artifact.payload, fixture.response),
		);
	});
}

test("intake text uses the existing AG-UI rendered-text ceiling", () => {
	assert.equal(MAX_INTAKE_TEXT_LENGTH, MAX_RENDERED_TEXT_LENGTH);
});

test("three domains use materially different bounded field configurations", () => {
	const configurations = manifest.fixtures.map((entry) => {
		const fixture = loadFixture(entry.fixture_id);
		return fixture.artifact.payload.fields
			.map((field) => `${field.destination}:${field.kind}`)
			.sort();
	});

	assert.equal(
		new Set(configurations.map((value) => JSON.stringify(value))).size,
		3,
	);
	assert.ok(configurations.flat().includes("option:multi_select"));
	assert.ok(configurations.flat().includes("constraint:boolean"));
	assert.ok(configurations.flat().includes("constraint:short_text"));
});

function applyMutations(document, operations) {
	for (const mutation of operations) {
		const segments = mutation.path
			.slice(1)
			.split("/")
			.map((segment) => segment.replaceAll("~1", "/").replaceAll("~0", "~"));
		let parent = document;
		for (const segment of segments.slice(0, -1)) {
			parent = Array.isArray(parent)
				? parent[Number(segment)]
				: parent[segment];
		}
		const final = segments.at(-1);
		const value = mutation.repeat
			? mutation.repeat.value.repeat(mutation.repeat.count)
			: structuredClone(mutation.value);
		if (Array.isArray(parent)) {
			const index = Number(final);
			if (mutation.operation === "remove") parent.splice(index, 1);
			else if (mutation.operation === "add") parent.splice(index, 0, value);
			else parent[index] = value;
		} else if (mutation.operation === "remove") {
			delete parent[final];
		} else {
			parent[final] = value;
		}
	}
}
