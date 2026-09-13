// Same-origin fetch through the Nginx gateway, with the JWT that the api sets as
// an HttpOnly cookie. Shared by the console and the agent panel so there is one
// convention for "how we talk to the api" and one for "how an error reads".

export const api = (path, opts = {}) =>
  fetch(path, { credentials: "include", ...opts });

// FastAPI reports errors as {"detail": ...}: a sentence for our own messages, or
// a list for pydantic validation. Surface the sentence, not the JSON dump.
export const errorText = (body, status) => {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d))
    return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
  return body ? JSON.stringify(body) : `request failed (HTTP ${status})`;
};
