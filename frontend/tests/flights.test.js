import assert from "node:assert/strict";
import test from "node:test";

import {
  CABIN_LABELS,
  formatDuration,
  formatFare,
  readFlights,
  readFlightsNote,
} from "../public/flights.js";

function aiFlight(overrides = {}) {
  return {
    flight_number: "AI 111",
    origin: "DEL",
    destination: "LHR",
    departure: "2026-11-06T13:30:00",
    arrival: "2026-11-06T18:20:00",
    duration_minutes: 620,
    fares: { economy: 48000, business: 180000 },
    currency: "INR",
    ...overrides,
  };
}

test("a full valid flight maps to the exact parsed shape", () => {
  const flights = readFlights([aiFlight()]);

  assert.deepEqual(flights, [
    {
      flightNumber: "AI 111",
      origin: "DEL",
      destination: "LHR",
      currency: "INR",
      departs: "13:30",
      arrives: "18:20",
      nextDay: false,
      durationMinutes: 620,
      fares: [
        { cabin: "economy", amount: 48000 },
        { cabin: "business", amount: 180000 },
      ],
    },
  ]);
});

test("fares come out economy-then-business regardless of JSON key order", () => {
  const flights = readFlights([aiFlight({ fares: { business: 180000, economy: 48000 } })]);

  assert.deepEqual(flights[0].fares, [
    { cabin: "economy", amount: 48000 },
    { cabin: "business", amount: 180000 },
  ]);
});

test("an overnight arrival sets nextDay to true", () => {
  const flights = readFlights([
    aiFlight({
      flight_number: "AI 112",
      departure: "2026-11-06T21:00:00",
      arrival: "2026-11-07T10:30:00",
    }),
  ]);

  assert.equal(flights[0].nextDay, true);
});

test("non-array flights becomes an empty list", () => {
  for (const bad of [undefined, null, "oops", { flights: [] }, 3]) {
    assert.deepEqual(readFlights(bad), []);
  }
});

test("a blank flight_number drops the entry but keeps the rest", () => {
  const flights = readFlights([aiFlight({ flight_number: "   " }), aiFlight()]);

  assert.equal(flights.length, 1);
  assert.equal(flights[0].flightNumber, "AI 111");
});

for (const badCode of ["del", "DE", "DELH", "", 3, null, undefined]) {
  test(`a malformed origin (${JSON.stringify(badCode)}) drops the entry`, () => {
    assert.deepEqual(readFlights([aiFlight({ origin: badCode })]), []);
  });

  test(`a malformed destination (${JSON.stringify(badCode)}) drops the entry`, () => {
    assert.deepEqual(readFlights([aiFlight({ destination: badCode })]), []);
  });
}

for (const badDate of ["2026-11-06", "11/06/2026T13:30:00", "", 3, null, undefined]) {
  test(`an unparseable departure (${JSON.stringify(badDate)}) drops the entry`, () => {
    assert.deepEqual(readFlights([aiFlight({ departure: badDate })]), []);
  });

  test(`an unparseable arrival (${JSON.stringify(badDate)}) drops the entry`, () => {
    assert.deepEqual(readFlights([aiFlight({ arrival: badDate })]), []);
  });
}

test("a departure/arrival without seconds still parses", () => {
  const flights = readFlights([
    aiFlight({ departure: "2026-11-06T13:30", arrival: "2026-11-06T18:20" }),
  ]);

  assert.equal(flights.length, 1);
  assert.equal(flights[0].departs, "13:30");
  assert.equal(flights[0].arrives, "18:20");
});

for (const badCurrency of ["inr", "US", "USDT", "", 3, null, undefined]) {
  test(`a malformed currency (${JSON.stringify(badCurrency)}) drops the entry`, () => {
    assert.deepEqual(readFlights([aiFlight({ currency: badCurrency })]), []);
  });
}

test("a non-integer fare amount is dropped, keeping any other valid fare", () => {
  const flights = readFlights([aiFlight({ fares: { economy: 48000.5, business: 180000 } })]);

  assert.deepEqual(flights[0].fares, [{ cabin: "business", amount: 180000 }]);
});

test("a negative fare amount is dropped", () => {
  const flights = readFlights([aiFlight({ fares: { economy: -1, business: 180000 } })]);

  assert.deepEqual(flights[0].fares, [{ cabin: "business", amount: 180000 }]);
});

test("an unknown cabin key is ignored", () => {
  const flights = readFlights([
    aiFlight({ fares: { economy: 48000, business: 180000, first: 400000 } }),
  ]);

  assert.deepEqual(flights[0].fares, [
    { cabin: "economy", amount: 48000 },
    { cabin: "business", amount: 180000 },
  ]);
});

test("no valid fare left drops the whole entry", () => {
  assert.deepEqual(readFlights([aiFlight({ fares: { economy: -1, business: "x" } })]), []);
  assert.deepEqual(readFlights([aiFlight({ fares: {} })]), []);
  assert.deepEqual(readFlights([aiFlight({ fares: null })]), []);
});

for (const badDuration of [undefined, null, 0, -5, 12.5, "620"]) {
  test(`a missing/invalid duration_minutes (${JSON.stringify(badDuration)}) keeps the flight with durationMinutes null`, () => {
    const flights = readFlights([aiFlight({ duration_minutes: badDuration })]);

    assert.equal(flights.length, 1);
    assert.equal(flights[0].durationMinutes, null);
  });
}

test("a flight_number containing HTML comes back as the literal string", () => {
  const flightNumber = "<img src=x onerror=alert(1)>";
  const flights = readFlights([aiFlight({ flight_number: flightNumber })]);

  assert.equal(flights[0].flightNumber, flightNumber);
});

test("readFlightsNote keeps a real string", () => {
  assert.equal(readFlightsNote("This is a sample schedule."), "This is a sample schedule.");
});

for (const bad of ["", "   ", null, undefined, 3, []]) {
  test(`readFlightsNote maps (${JSON.stringify(bad)}) to null`, () => {
    assert.equal(readFlightsNote(bad), null);
  });
}

test("every CABIN_LABELS entry has a non-empty label", () => {
  for (const label of Object.values(CABIN_LABELS)) {
    assert.equal(typeof label, "string");
    assert.ok(label.trim().length > 0);
  }
});

test("formatDuration shows minutes only under an hour", () => {
  assert.equal(formatDuration(45), "45m");
});

test("formatDuration shows whole hours with no minutes suffix", () => {
  assert.equal(formatDuration(480), "8h");
});

test("formatDuration shows hours and minutes together", () => {
  assert.equal(formatDuration(620), "10h 20m");
});

test("formatFare adds thousands separators and joins cabin, currency and amount", () => {
  assert.equal(formatFare("economy", 48000, "INR"), "Economy · INR 48,000");
  assert.equal(formatFare("business", 180000, "INR"), "Business · INR 180,000");
});
