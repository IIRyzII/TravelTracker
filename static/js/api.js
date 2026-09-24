/* ORBIT — talking to the server. The session cookie says who you are. */

export const apiHooks = { unauthorized: () => {} };

export async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error(navigator.onLine === false
      ? "You're offline — try again when you're back online."
      : "Couldn't reach ORBIT — check your connection.");
  }
  let data = null;
  try { data = await res.json(); } catch { /* not JSON (proxy error page, etc.) */ }
  if (res.status === 401 && !path.startsWith("/api/auth/")) apiHooks.unauthorized();
  if (!res.ok) throw new Error(data?.error || "Something went wrong — please try again.");
  return data;
}
