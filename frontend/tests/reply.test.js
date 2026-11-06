import assert from "node:assert/strict";
import test from "node:test";

import { httpsHref, INTENT_LABELS, NETWORK_ERROR_MESSAGE, readReply } from "../public/reply.js";

function jsonResponse(status, body, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

test("200 with only an answer defaults intent to null, sources/flights to empty and flightsNote to null", async () => {
  const reply = await readReply(jsonResponse(200, { answer: "Yes, you can." }));

  assert.deepEqual(reply, {
    answer: "Yes, you can.",
    intent: null,
    sources: [],
    flights: [],
    flightsNote: null,
  });
});

test("200 with extra fields ignores them and keeps the rest", async () => {
  const reply = await readReply(
    jsonResponse(200, { answer: "Yes, you can.", conversation_id: "abc-123" }),
  );

  assert.deepEqual(reply, {
    answer: "Yes, you can.",
    intent: null,
    sources: [],
    flights: [],
    flightsNote: null,
  });
});

test("200 with a full policy body returns answer, intent and sources", async () => {
  const reply = await readReply(
    jsonResponse(200, {
      answer: "20kg in economy.",
      intent: "policy",
      sources: [{ title: "Baggage policy", url: "https://example.com/baggage" }],
    }),
  );

  assert.deepEqual(reply, {
    answer: "20kg in economy.",
    intent: "policy",
    sources: [{ title: "Baggage policy", href: "https://example.com/baggage" }],
    flights: [],
    flightsNote: null,
  });
});

test("200 with a full flight_search body returns flights and flightsNote", async () => {
  const reply = await readReply(
    jsonResponse(200, {
      answer: "Flights from Delhi to London on Friday 6 November 2026:",
      intent: "flight_search",
      sources: [],
      flights: [
        {
          flight_number: "AI 111",
          origin: "DEL",
          destination: "LHR",
          departure: "2026-11-06T13:30:00",
          arrival: "2026-11-06T18:20:00",
          duration_minutes: 620,
          fares: { economy: 48000, business: 180000 },
          currency: "INR",
        },
      ],
      flights_note: "This is a sample schedule for this demo, not live fares or availability.",
    }),
  );

  assert.equal(reply.flights.length, 1);
  assert.equal(reply.flights[0].flightNumber, "AI 111");
  assert.equal(
    reply.flightsNote,
    "This is a sample schedule for this demo, not live fares or availability.",
  );
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

for (const intent of Object.keys(INTENT_LABELS)) {
  test(`200 keeps the known intent "${intent}"`, async () => {
    const reply = await readReply(jsonResponse(200, { answer: "x", intent }));

    assert.equal(reply.intent, intent);
  });
}

test("every INTENT_LABELS entry has a non-empty label", () => {
  for (const label of Object.values(INTENT_LABELS)) {
    assert.equal(typeof label, "string");
    assert.ok(label.trim().length > 0);
  }
});

for (const badIntent of ["booking", 3, null, undefined, [], {}]) {
  test(`200 maps an unrecognized intent (${JSON.stringify(badIntent)}) to null`, async () => {
    const reply = await readReply(jsonResponse(200, { answer: "x", intent: badIntent }));

    assert.equal(reply.intent, null);
  });
}

for (const badSources of [undefined, null, "oops", { title: "x" }, 3]) {
  test(`200 maps a non-array sources value (${JSON.stringify(badSources)}) to an empty list`, async () => {
    const reply = await readReply(jsonResponse(200, { answer: "x", sources: badSources }));

    assert.deepEqual(reply.sources, []);
  });
}

test("200 drops malformed source entries but keeps the valid ones", async () => {
  const reply = await readReply(
    jsonResponse(200, {
      answer: "x",
      sources: [
        { title: "Good", url: "https://example.com/a" },
        null,
        "not an object",
        {},
        { title: "" },
        { title: "   " },
        { title: 3, url: "https://example.com/b" },
      ],
    }),
  );

  assert.deepEqual(reply.sources, [{ title: "Good", href: "https://example.com/a" }]);
});

test("200 keeps a source title containing HTML verbatim, unescaped", async () => {
  const title = "<img src=x onerror=alert(1)>";
  const reply = await readReply(
    jsonResponse(200, { answer: "x", sources: [{ title, url: "https://example.com" }] }),
  );

  assert.equal(reply.sources[0].title, title);
});

test("200 keeps a non-https source's title with a null href, instead of dropping it", async () => {
  const reply = await readReply(
    jsonResponse(200, { answer: "x", sources: [{ title: "HTTP only", url: "http://example.com" }] }),
  );

  assert.deepEqual(reply.sources, [{ title: "HTTP only", href: null }]);
});

test("200 with sources and intent but no answer is still an unexpected response", async () => {
  const reply = await readReply(jsonResponse(200, { intent: "policy", sources: [] }));

  assert.equal(reply.answer, undefined);
  assert.ok(reply.error);
});

test("httpsHref accepts https URLs, case-insensitively on the scheme", () => {
  assert.equal(httpsHref("https://example.com/a"), "https://example.com/a");
  assert.equal(httpsHref("HTTPS://example.com/a"), "https://example.com/a");
});

for (const url of [
  "http://example.com",
  "javascript:alert(1)",
  "data:text/html,<script>alert(1)</script>",
  "/baggage",
  "",
  3,
  null,
  undefined,
  "not a url",
]) {
  test(`httpsHref rejects ${JSON.stringify(url)}`, () => {
    assert.equal(httpsHref(url), null);
  });
}
