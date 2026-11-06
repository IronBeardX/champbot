const BACKEND_DEV_PORT = 8787;
const PRODUCTION_FRONTEND_HOST = "champbot-frontend.alejandroyeroval.workers.dev";
const PRODUCTION_BACKEND_ORIGIN = "https://champbot.alejandroyeroval.workers.dev";

export function apiBase({ hostname }) {
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return `http://${hostname}:${BACKEND_DEV_PORT}`;
  }
  if (hostname === PRODUCTION_FRONTEND_HOST) {
    return PRODUCTION_BACKEND_ORIGIN;
  }
  return "";
}
