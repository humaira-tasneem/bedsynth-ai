import test from "node:test";
import assert from "node:assert/strict";
import { landingPathForRole, restrictedDestination } from "./role-routing.mjs";

test("role landing routes use the backend role", () => {
  assert.equal(landingPathForRole("admin"), "/admin");
  assert.equal(landingPathForRole("user"), "/");
});

test("users are redirected away from admin route trees", () => {
  assert.equal(restrictedDestination("user", "/admin"), "/");
  assert.equal(restrictedDestination("user", "/admin/datasets"), "/");
  assert.equal(restrictedDestination("user", "/users"), "/");
  assert.equal(restrictedDestination("admin", "/admin/datasets"), null);
  assert.equal(restrictedDestination("user", "/datasets"), null);
});
