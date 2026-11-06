import assert from "node:assert/strict";
import test from "node:test";

import { remainingSeconds, retryLabel } from "../public/retry.js";

test("remainingSeconds reports the exact number of whole seconds left", () => {
  assert.equal(remainingSeconds(10_000, 0), 10);
});

test("remainingSeconds rounds a partial second up", () => {
  assert.equal(remainingSeconds(10_001, 0), 11);
});

test("remainingSeconds never goes below zero once the deadline has passed", () => {
  assert.equal(remainingSeconds(1_000, 5_000), 0);
});

test('retryLabel(0) reads "Retry"', () => {
  assert.equal(retryLabel(0), "Retry");
});

test('retryLabel(5) reads "Retry in 5 s"', () => {
  assert.equal(retryLabel(5), "Retry in 5 s");
});
