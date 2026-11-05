import { buildHistory } from "./history.js";
import { INTENT_LABELS, NETWORK_ERROR_MESSAGE, readReply } from "./reply.js";

const form = document.querySelector("#chat-form");
const messageField = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const newConversationButton = document.querySelector("#new-conversation");
const conversation = document.querySelector("#conversation");

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
    setButtonsDisabled(false);
  }
});

newConversationButton.addEventListener("click", () => {
  turns = [];
  conversation.querySelectorAll(".turn:not(.greeting)").forEach((turn) => turn.remove());
  messageField.value = "";
  messageField.focus();
});
