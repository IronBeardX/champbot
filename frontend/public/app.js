import { buildHistory } from "./history.js";
import { NETWORK_ERROR_MESSAGE, readReply } from "./reply.js";

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
      pending.textContent = reply.answer;
      pending.className = "turn assistant";
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
