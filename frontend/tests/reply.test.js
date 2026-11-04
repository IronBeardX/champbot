import assert from "node:assert/strict";
import test from "node:test";

import { NETWORK_ERROR_MESSAGE, readReply } from "../public/reply.js";

function jsonResponse(status, body, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

test("200 with an answer returns it", async () => {
  const reply = await readReply(jsonResponse(200, { answer: "Yes, you can." }));

  assert.deepEqual(reply, { answer: "Yes, you can." });
});

test("200 with extra fields ignores them and returns the answer", async () => {
  const reply = await readReply(
    jsonResponse(200, { answer: "Yes, you can.", conversation_id: "abc-123" }),
  );

  assert.deepEqual(reply, { answer: "Yes, you can." });
});

test("200 without an answer field is an unexpected response", async () => {
  const reply = await readReply(jsonResponse(200, { conversation_id: "abc-123" }));

  assert.equal(reply.answer, undefined);
  assert.ok(reply.error);
});

test("422 reports the validation message", async () => {
  const reply = await readReply(jsonResponse(422, { detail: [{ msg: "too long" }] }));

  assert.deepEqual(reply, { error: "Message must be 1-2000 characters and not blank." });
});

test("429 with a numeric Retry-After names the wait", async () => {
  const reply = await readReply(
    jsonResponse(429, { detail: "slow down" }, { "Retry-After": "37" }),
  );

  assert.deepEqual(reply, { error: "Too many requests. Try again in 37 s." });
});

test("429 without Retry-After gives a generic wait", async () => {
  const reply = await readReply(jsonResponse(429, { detail: "slow down" }));

  assert.deepEqual(reply, { error: "Too many requests. Try again shortly." });
});

test("502 reports the assistant is unavailable", async () => {
  const reply = await readReply(jsonResponse(502, { detail: "bad gateway" }));

  assert.deepEqual(reply, { error: "The assistant is unavailable right now. Try again shortly." });
});

test("504 reports the assistant took too long", async () => {
  const reply = await readReply(jsonResponse(504, { detail: "gateway timeout" }));

  assert.deepEqual(reply, { error: "The assistant took too long to answer. Try again." });
});

test("500 reports a server error", async () => {
  const reply = await readReply(jsonResponse(500, { detail: "internal error" }));

  assert.deepEqual(reply, { error: "Something went wrong on the server. Try again later." });
});

test("an unknown status is an unexpected response", async () => {
  const reply = await readReply(jsonResponse(503, { detail: "unknown" }));

  assert.equal(reply.answer, undefined);
  assert.ok(reply.error);
});

test("a non-JSON body is an unexpected response", async () => {
  const response = new Response("<html>error code: 1102</html>", {
    status: 200,
    headers: { "content-type": "text/html" },
  });

  const reply = await readReply(response);

  assert.equal(reply.answer, undefined);
  assert.ok(reply.error);
});

test("NETWORK_ERROR_MESSAGE is exported for the fetch catch", () => {
  assert.equal(typeof NETWORK_ERROR_MESSAGE, "string");
  assert.ok(NETWORK_ERROR_MESSAGE.length > 0);
});
