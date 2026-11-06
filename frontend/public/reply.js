import { readFlights, readFlightsNote } from "./flights.js";

export const NETWORK_ERROR_MESSAGE =
  "Could not reach the server. Check your connection and try again.";

export const INTENT_LABELS = {
  policy: "Policy",
  flight_search: "Flight search",
  general: "General",
};

const UNEXPECTED_RESPONSE_MESSAGE = "Unexpected response from the server.";

export const TIMEOUT_MESSAGE = "The assistant took too long to answer. Try again.";

const FIXED_STATUS_MESSAGES = {
  422: "Message must be 1-2000 characters and not blank.",
  502: "The assistant is unavailable right now. Try again shortly.",
  504: TIMEOUT_MESSAGE,
  500: "Something went wrong on the server. Try again later.",
};

export function retryAfterSeconds(response) {
  const raw = response.headers.get("Retry-After");
  if (raw === null || raw.trim() === "") {
    return null;
  }
  const seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds < 0) {
    return null;
  }
  return Math.ceil(seconds);
}

export function failureMessage(error) {
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return TIMEOUT_MESSAGE;
  }
  return NETWORK_ERROR_MESSAGE;
}

function rateLimitMessage(response) {
  const seconds = retryAfterSeconds(response);
  if (seconds !== null) {
    return `Too many requests. Try again in ${seconds} s.`;
  }
  return "Too many requests. Try again shortly.";
}

export function httpsHref(url) {
  if (typeof url !== "string") {
    return null;
  }
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  return parsed.protocol === "https:" ? parsed.href : null;
}

function readIntent(raw) {
  return typeof raw === "string" && raw in INTENT_LABELS ? raw : null;
}

function readSources(raw) {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .filter((entry) => typeof entry?.title === "string" && entry.title.trim() !== "")
    .map((entry) => ({ title: entry.title, href: httpsHref(entry.url) }));
}

async function readAnswer(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    return { error: UNEXPECTED_RESPONSE_MESSAGE };
  }
  if (typeof body?.answer === "string") {
    return {
      answer: body.answer,
      intent: readIntent(body.intent),
      sources: readSources(body.sources),
      flights: readFlights(body.flights),
      flightsNote: readFlightsNote(body.flights_note),
    };
  }
  return { error: UNEXPECTED_RESPONSE_MESSAGE };
}

export async function readReply(response) {
  if (response.status === 200) {
    return readAnswer(response);
  }
  if (response.status === 429) {
    return { error: rateLimitMessage(response), retryAfter: retryAfterSeconds(response) };
  }
  const message = FIXED_STATUS_MESSAGES[response.status];
  if (message !== undefined) {
    return { error: message };
  }
  return { error: UNEXPECTED_RESPONSE_MESSAGE };
}
