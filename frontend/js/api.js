/* Thin HTTP layer. Same-origin, so no base URL and no CORS in normal use. */

export async function getJSON(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail || detail; } catch { /* keep status text */ }
    throw new Error(detail);
  }
  return res.json();
}

export const health = () => getJSON("/api/health");
export const domains = () => getJSON("/api/domains");
export const sendFeedback = (payload) => postJSON("/api/feedback", payload);

/**
 * Open the recommendation stream.
 *
 * EventSource rather than fetch+ReadableStream: it reconnects on its own, it
 * needs no polyfill on any current browser, and the traffic is one-directional
 * anyway. `onEvent` is called for every pipeline event as it arrives.
 * Returns a handle with `.close()` so a second submission cancels the first.
 */
export function streamRecommendation(
  { query, domain, topK, method, sessionId, curatedOnly },
  onEvent,
  onError,
) {
  const params = new URLSearchParams({
    query,
    domain: domain || "auto",
    top_k: String(topK || 5),
    method: method || "debate",
    session_id: sessionId || "anon",
    curated_only: String(Boolean(curatedOnly)),
  });
  const source = new EventSource(`/api/recommend/stream?${params.toString()}`);
  let finished = false;

  source.onmessage = (message) => {
    let payload;
    try {
      payload = JSON.parse(message.data);
    } catch {
      return;
    }
    if (payload.type === "done" || payload.type === "error") {
      finished = true;
      onEvent(payload);
      source.close();
      return;
    }
    onEvent(payload);
  };

  source.onerror = () => {
    // A close after the "done" event is the normal end of stream, not a failure.
    if (finished) return;
    source.close();
    onError?.(new Error("The connection to the server was interrupted."));
  };

  return { close: () => { finished = true; source.close(); } };
}
