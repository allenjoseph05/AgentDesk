import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
const repositoryRoot = new URL("../../../", import.meta.url);

async function readJson(relativePath, root = webRoot) {
  return JSON.parse(await readFile(new URL(relativePath, root), "utf8"));
}

test("frontend compiler keeps strict safety checks enabled", async () => {
  const config = await readJson("tsconfig.json");

  assert.equal(config.compilerOptions.strict, true);
  assert.equal(config.compilerOptions.noUncheckedIndexedAccess, true);
  assert.equal(config.compilerOptions.noFallthroughCasesInSwitch, true);
  assert.equal(config.compilerOptions.noUnusedLocals, true);
  assert.equal(config.compilerOptions.noUnusedParameters, true);
});

test("frontend scripts and CI retain lint, type, catalog, schema, and test gates", async () => {
  const packageJson = await readJson("package.json");
  const workflow = await readFile(
    new URL(".github/workflows/ci.yml", repositoryRoot),
    "utf8",
  );

  assert.match(packageJson.scripts.lint, /^biome lint --error-on-warnings /u);
  assert.match(packageJson.scripts.typecheck, /^tsc --noEmit --pretty false/u);
  assert.match(packageJson.scripts.typecheck, /tsconfig\.e2e\.json/u);
  assert.match(packageJson.scripts.test, /node --test test\/\*\.test\.mjs/u);
  assert.match(packageJson.scripts["test:contracts"], /agui-contract-fixtures\.test\.mjs/u);
  assert.match(packageJson.scripts["test:contracts"], /component-catalog\.test\.mjs/u);
  assert.match(packageJson.scripts["test:agui"], /agui-python-interop\.test\.mjs/u);
  assert.equal(packageJson.scripts["test:e2e"], "playwright test");
  assert.match(workflow, /run: npm run test:agui/u);
  assert.match(workflow, /run: npx playwright install --with-deps chromium/u);
  assert.match(workflow, /run: npm run test:e2e/u);
  assert.match(workflow, /uses: actions\/upload-artifact@v4/u);
  assert.match(workflow, /run: npm run lint:web/u);
  assert.match(workflow, /run: npm run typecheck:web/u);
  assert.match(workflow, /run: npm run test:contracts --workspace @agentdesk\/web/u);
  assert.match(workflow, /run: npm run test:web/u);
});
