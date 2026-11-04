import { NETWORK_ERROR_MESSAGE, readReply } from "./reply.js";

const form = document.querySelector("#chat-form");
const messageField = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const answerOutput = document.querySelector("#answer");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  sendButton.disabled = true;
  answerOutput.textContent = "Thinking…";

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: messageField.value }),
    });
    const reply = await readReply(response);
    answerOutput.textContent = reply.answer ?? reply.error;
  } catch {
    answerOutput.textContent = NETWORK_ERROR_MESSAGE;
  } finally {
    sendButton.disabled = false;
  }
});
