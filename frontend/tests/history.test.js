import assert from "node:assert/strict";
import test from "node:test";

import { MAX_HISTORY_ITEMS, MAX_HISTORY_TEXT_LENGTH, buildHistory } from "../public/history.js";

function pair(userLength, assistantLength) {
  return { user: "u".repeat(userLength), assistant: "a".repeat(assistantLength) };
}

test("no pairs gives no history", () => {
  assert.deepEqual(buildHistory([]), []);
});

test("two pairs become four alternating items with the exact texts", () => {
  const pairs = [
    { user: "My name is Alejandro.", assistant: "Nice to meet you." },
    { user: "What's the weather like?", assistant: "I can't check that." },
  ];

  assert.deepEqual(buildHistory(pairs), [
    { role: "user", text: "My name is Alejandro." },
    { role: "assistant", text: "Nice to meet you." },
    { role: "user", text: "What's the weather like?" },
    { role: "assistant", text: "I can't check that." },
  ]);
});

test("exactly 10 pairs (20 items) are all kept", () => {
  const pairs = Array.from({ length: 10 }, () => pair(10, 10));

  assert.equal(buildHistory(pairs).length, 20);
});

test("11 pairs drop the oldest one, keeping the newest 10", () => {
  const pairs = Array.from({ length: 11 }, (_, index) => pair(10, 10 + index));

  const history = buildHistory(pairs);

  assert.equal(history.length, 20);
  assert.ok(!history.some((item) => item.text === "a".repeat(10)));
});

test("pairs totalling exactly 40 000 characters are all kept", () => {
  const pairs = Array.from({ length: 5 }, () => pair(2000, 6000));

  const history = buildHistory(pairs);

  assert.equal(history.length, 10);
  const total = history.reduce((sum, item) => sum + item.text.length, 0);
  assert.equal(total, 40_000);
});

test("one character over the 40 000 budget drops the oldest pair", () => {
  const pairs = [
    pair(2000, 6001),
    pair(2000, 6000),
    pair(2000, 6000),
    pair(2000, 6000),
    pair(2000, 6000),
  ];

  const history = buildHistory(pairs);

  assert.equal(history.length, 8);
  assert.ok(!history.some((item) => item.text.length === 6001));
});

test("stops at the first pair that doesn't fit instead of skipping to an older, smaller one", () => {
  const filler = Array.from({ length: 4 }, () => pair(2000, 7999));
  const tooBigToSkipTo = pair(2000, 7999);
  const tinyButOlder = pair(1, 1);

  const pairs = [tinyButOlder, tooBigToSkipTo, ...filler];
  const history = buildHistory(pairs);

  assert.equal(history.length, 8);
  assert.ok(!history.some((item) => item.text === "u"));
});

test("an assistant text of 8001 characters is dropped, older pairs are still sent", () => {
  const pairs = [pair(10, 10), pair(10, 8001)];

  const history = buildHistory(pairs);

  assert.deepEqual(history, [
    { role: "user", text: "u".repeat(10) },
    { role: "assistant", text: "a".repeat(10) },
  ]);
});

test("an assistant text of exactly 8000 characters is kept", () => {
  const pairs = [pair(10, 8000)];

  assert.equal(buildHistory(pairs).length, 2);
});

test("a user text over 2000 characters drops the pair, exactly 2000 is kept", () => {
  const pairs = [pair(2001, 10), pair(2000, 10)];

  const history = buildHistory(pairs);

  assert.equal(history.length, 2);
  assert.equal(history[0].text.length, 2000);
});

test("several oversized pairs scattered through the history are all dropped, in order", () => {
  const pairs = [pair(10, 8001), pair(10, 10), pair(2001, 10), pair(20, 20), pair(10, 8001)];

  const history = buildHistory(pairs);

  assert.deepEqual(history, [
    { role: "user", text: "u".repeat(10) },
    { role: "assistant", text: "a".repeat(10) },
    { role: "user", text: "u".repeat(20) },
    { role: "assistant", text: "a".repeat(20) },
  ]);
});

test("a pair with a whitespace-only user or assistant text is dropped", () => {
  const pairs = [{ user: "   ", assistant: "fine" }, pair(10, 10)];

  const history = buildHistory(pairs);

  assert.equal(history.length, 2);
  assert.notEqual(history[0].text, "   ");
});

test("counts code points, not UTF-16 units, so 8000 emoji are kept", () => {
  const assistantText = "😀".repeat(8000);
  const pairs = [{ user: "How many?", assistant: assistantText }];

  const history = buildHistory(pairs);

  assert.equal(history.length, 2);
  assert.equal(history[1].text, assistantText);
});

test("the output always alternates, starts with user, and respects both limits", () => {
  const pairs = [
    pair(10, 10),
    { user: "", assistant: "blank user is invalid" },
    pair(10, 8001),
    pair(2000, 7000),
    pair(5, 5),
    pair(2001, 10),
    pair(1500, 6000),
  ];

  const history = buildHistory(pairs);

  assert.ok(history.length % 2 === 0);
  assert.ok(history.length <= MAX_HISTORY_ITEMS);
  history.forEach((item, index) => {
    assert.equal(item.role, index % 2 === 0 ? "user" : "assistant");
  });
  const total = history.reduce((sum, item) => sum + [...item.text].length, 0);
  assert.ok(total <= MAX_HISTORY_TEXT_LENGTH);
});
