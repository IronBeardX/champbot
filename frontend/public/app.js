import { formatDuration, formatFare } from "./flights.js";
import { buildHistory } from "./history.js";
import { INTENT_LABELS, NETWORK_ERROR_MESSAGE, readReply } from "./reply.js";

const form = document.querySelector("#chat-form");
const messageField = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const newConversationButton = document.querySelector("#new-conversation");
const conversation = document.querySelector("#conversation");
const suggestions = document.querySelector(".suggestions");

const HINT_DELAY_MS = 5000;
const HINT_TEXT = "Still working, answers can take up to 20 seconds.";

let turns = [];

function addTurn(className, text) {
  const item = document.createElement("li");
  item.className = `turn ${className}`;
  item.textContent = text;
  conversation.append(item);
  return item;
}

function renderAnswer(item, reply) {
  item.replaceChildren();
  item.className = "turn assistant";

  if (reply.intent !== null) {
    const intent = document.createElement("span");
    intent.className = "intent";
    intent.textContent = INTENT_LABELS[reply.intent];
    item.append(intent);
  }

  const answer = document.createElement("div");
  answer.className = "answer";
  answer.textContent = reply.answer;
  item.append(answer);

  renderFlights(item, reply);

  if (reply.sources.length > 0) {
    const sources = document.createElement("div");
    sources.className = "sources";

    const label = document.createElement("span");
    label.textContent = "Sources";
    sources.append(label);

    const list = document.createElement("ul");
    for (const source of reply.sources) {
      const entry = document.createElement("li");
      if (source.href !== null) {
        const link = document.createElement("a");
        link.href = source.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = source.title;
        entry.append(link);
      } else {
        entry.textContent = source.title;
      }
      list.append(entry);
    }
    sources.append(list);
    item.append(sources);
  }
}

function renderFlights(item, reply) {
  if (reply.flights.length === 0) {
    return;
  }

  const flights = document.createElement("div");
  flights.className = "flights";

  for (const flight of reply.flights) {
    const card = document.createElement("div");
    card.className = "flight-card";

    const number = document.createElement("div");
    number.className = "number";
    number.textContent = flight.flightNumber;
    card.append(number);

    const route = document.createElement("div");
    route.className = "route";
    const times = document.createElement("span");
    const arrival = flight.nextDay ? `${flight.arrives} +1` : flight.arrives;
    times.textContent = `${flight.origin} ${flight.departs} → ${flight.destination} ${arrival}`;
    route.append(times);
    if (flight.durationMinutes !== null) {
      const duration = document.createElement("span");
      duration.className = "duration";
      duration.textContent = formatDuration(flight.durationMinutes);
      route.append(duration);
    }
    card.append(route);

    const fares = document.createElement("div");
    fares.className = "fares";
    for (const fare of flight.fares) {
      const row = document.createElement("span");
      row.textContent = formatFare(fare.cabin, fare.amount, flight.currency);
      fares.append(row);
    }
    card.append(fares);

    flights.append(card);
  }

  item.append(flights);

  if (reply.flightsNote !== null) {
    const note = document.createElement("div");
    note.className = "flights-note";
    note.textContent = reply.flightsNote;
    item.append(note);
  }
}

function setButtonsDisabled(disabled) {
  sendButton.disabled = disabled;
  newConversationButton.disabled = disabled;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = messageField.value;
  const history = buildHistory(turns);

  setButtonsDisabled(true);
  const userTurn = addTurn("user", message);
  const pending = addTurn("assistant pending", "Thinking…");
  const hintTimer = setTimeout(() => {
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = HINT_TEXT;
    pending.append(hint);
  }, HINT_DELAY_MS);

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
    const reply = await readReply(response);
    if (reply.answer !== undefined) {
      renderAnswer(pending, reply);
      turns.push({ user: message, assistant: reply.answer });
      messageField.value = "";
    } else {
      pending.textContent = reply.error;
      pending.className = "turn assistant error";
      userTurn.classList.add("failed");
    }
  } catch {
    pending.textContent = NETWORK_ERROR_MESSAGE;
    pending.className = "turn assistant error";
    userTurn.classList.add("failed");
  } finally {
    clearTimeout(hintTimer);
    setButtonsDisabled(false);
  }
});

suggestions.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (chip === null) {
    return;
  }
  messageField.value = chip.textContent;
  messageField.focus();
});

newConversationButton.addEventListener("click", () => {
  turns = [];
  conversation.querySelectorAll(".turn:not(.greeting)").forEach((turn) => turn.remove());
  messageField.value = "";
  messageField.focus();
});
