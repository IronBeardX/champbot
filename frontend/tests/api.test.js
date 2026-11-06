import assert from "node:assert/strict";
import test from "node:test";

import { apiBase } from "../public/api.js";

test("apiBase resolves the production frontend host to the production backend origin", () => {
  assert.equal(
    apiBase({ hostname: "champbot-frontend.alejandroyeroval.workers.dev" }),
    "https://champbot.alejandroyeroval.workers.dev",
  );
});

test("apiBase resolves localhost to the backend dev port", () => {
  assert.equal(apiBase({ hostname: "localhost" }), "http://localhost:8787");
});

test("apiBase resolves 127.0.0.1 to the backend dev port", () => {
  assert.equal(apiBase({ hostname: "127.0.0.1" }), "http://127.0.0.1:8787");
});

test("apiBase falls back to same-origin for the backend's own host", () => {
  assert.equal(apiBase({ hostname: "champbot.alejandroyeroval.workers.dev" }), "");
});

test("apiBase falls back to same-origin for an unrelated host", () => {
  assert.equal(apiBase({ hostname: "example.com" }), "");
});
