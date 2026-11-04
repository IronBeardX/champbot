# Frontend

A single-turn chat UI: plain HTML and JavaScript, no build step, no dependencies.

## Files

- `public/index.html`: the page. A form (message + send button) and an answer area.
- `public/app.js`: DOM glue. On submit, disables the send button, shows a pending message, posts to `/chat`, renders the reply and re-enables the button.
- `public/reply.js`: pure logic, no DOM. `readReply(response)` maps a `/chat` response to `{ answer }` or `{ error }`, covering every status in the backend's error contract (see the root `README.md`). `NETWORK_ERROR_MESSAGE` is the message `app.js` shows when `fetch` itself fails.
- `public/styles.css`: minimal styling. The answer area uses `white-space: pre-wrap`.
- `public/favicon.svg`: keeps the browser's automatic favicon request from reaching the Worker.

Answers are rendered with `textContent`, never `innerHTML`.

## Serving

`backend/wrangler.jsonc` points Workers Static Assets at `public/`. A request that matches a file there is served directly, at no Worker CPU cost; everything else, including `/chat`, `/health` and unknown paths, falls through to the FastAPI app. No file or folder under `public/` starts with `chat` or `health`, so none of them can shadow those routes.

Only `pywrangler dev` (see the root `README.md`) serves this folder locally; uvicorn does not.

## Tests

```sh
npm test
```

Runs `node --test` over `tests/`. It only tests `reply.js`, the one module with its own rules (the status-to-message mapping). `app.js` is DOM wiring with no rules of its own, checked by hand instead.
