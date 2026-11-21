import test from "node:test";
import assert from "node:assert/strict";
import { guestApiPrefix, guestDatasetPath, guestRouteAllowed } from "./guest-access.mjs";

test("guest generation uses isolated API namespace and result URL", () => {
  assert.equal(guestApiPrefix(true), "/api/v1/guest");
  assert.equal(guestApiPrefix(false), "/api/v1");
  assert.equal(guestDatasetPath("run/with space"), "/guest/datasets/run%2Fwith%20space");
});

test("guest navigation allows generator and own result routes only", () => {
  assert.equal(guestRouteAllowed("/"), true);
  assert.equal(guestRouteAllowed("/generate"), true);
  assert.equal(guestRouteAllowed("/guest/datasets/abc"), true);
  assert.equal(guestRouteAllowed("/datasets/abc"), false);
  assert.equal(guestRouteAllowed("/analytics"), false);
  assert.equal(guestRouteAllowed("/hospitals"), false);
});
