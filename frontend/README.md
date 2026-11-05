# Frontend

A multi-turn chat UI: plain HTML and JavaScript, no build step, no dependencies.

## Files

- `public/index.html`: the page. A static greeting, a conversation list, a form (message + New conversation + Send).
- `public/app.js`: DOM glue. On submit, disables both buttons, renders the user turn and a pending one, posts to `/chat` with `{message, history}`, and on success renders the answer (intent tag, answer text, source links) and commits the pair to the kept turns; on failure (or a network error) it marks the turn as failed and keeps it out of the kept turns. "New conversation" clears the kept turns and the rendered list back to the greeting.
- `public/history.js`: pure logic, no DOM. `buildHistory(pairs)` turns the kept turns into the `history` the backend accepts: the longest suffix of complete pairs within its limits (see the root `README.md` and decision 16), oldest pairs dropped first, any pair that alone violates a per-role length cap dropped outright.
- `public/reply.js`: pure logic, no DOM. `readReply(response)` maps a `/chat` response to `{ answer, intent, sources }` or `{ error }`, covering every status in the backend's error contract (see the root `README.md`). `intent` falls back to `null` unless it's one of `INTENT_LABELS`'s keys; each source keeps its `title` but gets `href: null` unless its `url` is `https` (checked with `httpsHref`, via the `URL` parser, never a string prefix). `NETWORK_ERROR_MESSAGE` is the message `app.js` shows when `fetch` itself fails.
- `public/styles.css`: minimal styling. Each turn uses `white-space: pre-wrap`.
- `public/favicon.svg`: keeps the browser's automatic favicon request from reaching the Worker.

Turns are rendered with `textContent` (or the `href` property for source links), never `innerHTML`. Source links open in a new tab (`target="_blank" rel="noopener noreferrer"`), since nothing is persisted and following one in place would lose the conversation. A reload starts a new conversation.

## Serving

`backend/wrangler.jsonc` points Workers Static Assets at `public/`. A request that matches a file there is served directly, at no Worker CPU cost; everything else, including `/chat`, `/health` and unknown paths, falls through to the FastAPI app. No file or folder under `public/` starts with `chat` or `health`, so none of them can shadow those routes.

Only `pywrangler dev` (see the root `README.md`) serves this folder locally; uvicorn does not.

## Tests

```sh
npm test
```

Runs `node --test` over `tests/`. It tests `reply.js` (the status-to-message mapping, and the intent/source validation rules) and `history.js` (the windowing rules). `app.js` is DOM wiring with no rules of its own, checked by hand instead.
