import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");

test("Hospital Studio loads the default workspace without a workspace switcher", () => {
  assert.match(page, /api<Workspace\[]>\("\/workspaces"\)/);
  assert.match(page, /workspace\.name\.trim\(\)\.toLowerCase\(\) === "my workspace"/);
  assert.match(page, /setWorkspaceName\(chosen\.name\)/);
  assert.match(page, /studio-workspace-display/);
  assert.doesNotMatch(page, /workspace-select|changeWorkspace|ChevronDown/);
});

test("Hospital Studio preserves published-hospital browsing for normal users", () => {
  assert.match(page, /if \(identity\.role === "admin"\)/);
  assert.match(page, /No published hospitals yet/);
  assert.match(page, /\/workspaces\/\$\{id\}\/hospitals\?include_archived=true/);
});
