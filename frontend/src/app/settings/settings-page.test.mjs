import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
const shell = await readFile(new URL("../../components/AppShell.tsx", import.meta.url), "utf8");

test("Settings keeps account and platform sections without appearance controls", () => {
  for (const id of ["account", "security", "workspace", "privacy", "about"]) {
    assert.match(page, new RegExp(`href="#${id}"`));
    assert.match(page, new RegExp(`id="${id}"`));
  }
  for (const removed of ["Appearance &amp; display", "Appearance</a>", "Color theme", "Sidebar</strong>", "Content density", "Reduce motion", "settings-choice-group", "settings-switch"]) {
    assert.equal(page.includes(removed), false, `${removed} should not remain on Settings`);
  }
  assert.equal(page.includes('href="#appearance"'), false);
});

test("global theme and sidebar behavior remains owned by the shared app shell", () => {
  assert.match(shell, /bedsynth-theme-change/);
  assert.match(shell, /bedsynth-sidebar-change/);
});
