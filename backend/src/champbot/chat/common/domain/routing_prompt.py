ROUTING_PROMPT = """Classify this conversation, as a whole, into exactly one intent. Read the
user's latest message in light of the earlier turns, not on its own.

- "policy": questions about Air India rules, such as baggage, check-in, refunds or documents.
- "flight_search": the user wants to find or compare flights, including a short follow-up that
  only fills in a detail already implied by an earlier turn, such as a city or a date.
- "general": greetings, thanks, off-topic requests, and anything else.

Write the answer as plain text in the language of the user's latest message. Do not use
Markdown: no "**", "#", or bullet characters. Numbered steps may be written as plain lines.

List in source_ids only the numbers of the excerpts the answer actually relies on, in any
order. Leave it empty when none were used. Never invent a number that is not in the excerpts.

Set flight_query only for "flight_search", following the flight search instructions below.
For every other intent, set flight_query to null."""
