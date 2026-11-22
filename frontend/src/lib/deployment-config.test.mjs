import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const frontendRoot = new URL("../../", import.meta.url);
const config = await readFile(new URL("next.config.ts", frontendRoot), "utf8");
const sourceRoot = new URL("../", import.meta.url);

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
    if (entry.isDirectory()) files.push(...await sourceFiles(path));
    else if (/\.(tsx|ts)$/.test(entry.name)) files.push(path);
  }
  return files;
}

test("production routes API and health through the server-side backend proxy", () => {
  assert.match(config, /process\.env\.BACKEND_API_URL/);
  assert.match(config, /const isProduction = process\.env\.NODE_ENV === "production"/);
  assert.match(config, /isProduction \? "" : "http:\/\/127\.0\.0\.1:8000"/);
  assert.match(config, /source: "\/api\/:path\*", destination: `\$\{backendApiUrl\}\/api\/:path\*`/);
  assert.match(config, /source: "\/health", destination: `\$\{backendApiUrl\}\/health`/);
  assert.match(config, /BACKEND_API_URL must be set for production/);
  assert.match(config, /backendOrigin\.protocol !== "https:"/);
  assert.match(config, /backendOrigin\.pathname !== "\/"/);
});

test("frontend requests default to same-origin and contain no localhost API fallback", async () => {
  const files = await sourceFiles(sourceRoot);
  const pages = await Promise.all(files.map((file) => readFile(file, "utf8")));
  const applicationSources = pages.join("\n");
  assert.match(applicationSources, /NEXT_PUBLIC_API_BASE_URL \|\| ""/);
  assert.doesNotMatch(applicationSources, /NEXT_PUBLIC_API_BASE_URL \|\| "http:\/\/localhost:8000"/);
});
