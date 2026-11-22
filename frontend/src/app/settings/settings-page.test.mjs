import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
const shell = await readFile(new URL("../../components/AppShell.tsx", import.meta.url), "utf8");

test("Settings keeps Account and Security and removes Data & privacy and About", () => {
  for (const id of ["account", "security"]) {
    assert.match(page, new RegExp(`href="#${id}"`));
    assert.match(page, new RegExp(`id="${id}"`));
  }
  for (const id of ["privacy", "about"]) {
    assert.equal(page.includes(`href="#${id}"`), false);
    assert.equal(page.includes(`id="${id}"`), false);
  }
  assert.doesNotMatch(page, /Data &amp; privacy|About BedSynth AI|settings-privacy-list|settings-about/);
  assert.match(page, /auth\/change-password/);
  assert.match(page, /Current password/);
  assert.match(page, /New password/);
  assert.equal(page.includes('href="#workspace"'), false);
  assert.equal(page.includes('id="workspace"'), false);
  for (const removed of ["Appearance &amp; display", "Appearance</a>", "Color theme", "Sidebar</strong>", "Content density", "Reduce motion", "settings-choice-group", "settings-switch"]) {
    assert.equal(page.includes(removed), false, `${removed} should not remain on Settings`);
  }
  assert.equal(page.includes('href="#appearance"'), false);
});

test("global theme and sidebar behavior remains owned by the shared app shell", () => {
  assert.match(shell, /bedsynth-theme-change/);
  assert.match(shell, /bedsynth-sidebar-change/);
  assert.match(shell, /product-privacy/);
});
