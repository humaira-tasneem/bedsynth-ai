import test from "node:test";
import assert from "node:assert/strict";
import { landingPathForRole, restrictedDestination } from "./role-routing.mjs";

test("role landing routes use the backend role", () => {
  assert.equal(landingPathForRole("admin"), "/hospitals");
  assert.equal(landingPathForRole("user"), "/");
});

test("users are redirected away from administration and hospital editing", () => {
  assert.equal(restrictedDestination("user", "/admin"), "/");
  assert.equal(restrictedDestination("user", "/admin/datasets"), "/");
  assert.equal(restrictedDestination("user", "/users"), "/");
  assert.equal(restrictedDestination("user", "/assistant"), "/");
  assert.equal(restrictedDestination("user", "/guest/datasets/run-123"), "/");
  assert.equal(restrictedDestination("user", "/hospitals"), "/generate");
  assert.equal(restrictedDestination("user", "/hospitals/12/departments"), "/generate");
});

test("role navigation destinations remain available", () => {
  for (const path of ["/generate", "/datasets", "/analytics", "/validation", "/settings"]) {
    assert.equal(restrictedDestination("user", path), null, `${path} should remain available to users`);
  }
  for (const path of ["/hospitals", "/generate", "/datasets", "/settings"]) {
    assert.equal(restrictedDestination("admin", path), null, `${path} should remain available to administrators`);
  }
  assert.equal(restrictedDestination("admin", "/admin/datasets"), "/hospitals");
  assert.equal(restrictedDestination("admin", "/analytics"), "/hospitals");
  assert.equal(restrictedDestination("admin", "/validation"), "/hospitals");
  assert.equal(restrictedDestination("admin", "/guest/datasets/run-123"), "/hospitals");
  assert.equal(restrictedDestination("user", "/datasets"), null);
});
