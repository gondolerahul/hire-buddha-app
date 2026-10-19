// The HireBuddha Data API from the browser: app-user sign-in and records.
// Settings come from /config.js (window.HB_CONFIG), written when the app starts.

type Config = { dataApiUrl: string; tenant: string; app: string; publicKey?: string };

declare global {
  interface Window { HB_CONFIG?: Config }
}

export function config(): Config {
  const value = window.HB_CONFIG;
  if (!value || !value.dataApiUrl) throw new Error("The app has no Data API address (config.js)");
  return value;
}

const ACCESS = "hb.access";
const REFRESH = "hb.refresh";

export class DataApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function call(path: string, init: RequestInit & { auth?: string | null } = {}): Promise<any> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const auth = init.auth === undefined ? localStorage.getItem(ACCESS) : init.auth;
  if (auth) headers.set("Authorization", `Bearer ${auth}`);
  const response = await fetch(`${config().dataApiUrl.replace(/\/$/, "")}${path}`, { ...init, headers });
  if (response.status === 401 && init.auth === undefined && localStorage.getItem(REFRESH)) {
    if (await refresh()) return call(path, init);
  }
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new DataApiError(response.status, body?.code ?? "error", body?.detail ?? response.statusText);
  }
  return body;
}

function keep(tokens: { access_token: string; refresh_token?: string }) {
  localStorage.setItem(ACCESS, tokens.access_token);
  if (tokens.refresh_token) localStorage.setItem(REFRESH, tokens.refresh_token);
}

export async function login(email: string, password: string) {
  const { tenant, app } = config();
  keep(await call("/v1/auth/login", { method: "POST", auth: null,
    body: JSON.stringify({ tenant, app, email, password }) }));
  return me();
}

export async function requestMagicLink(email: string, returnUrl = window.location.origin) {
  const { tenant, app } = config();
  await call("/v1/auth/magic-link", { method: "POST", auth: null,
    body: JSON.stringify({ tenant, app, email, return_url: returnUrl }) });
}

export async function verifyMagicLink(token: string) {
  keep(await call("/v1/auth/magic-link/verify", { method: "POST", auth: null, body: JSON.stringify({ token }) }));
  return me();
}

export async function refresh(): Promise<boolean> {
  const token = localStorage.getItem(REFRESH);
  if (!token) return false;
  try {
    keep(await call("/v1/auth/refresh", { method: "POST", auth: null, body: JSON.stringify({ refresh_token: token }) }));
    return true;
  } catch {
    signOutLocally();
    return false;
  }
}

function signOutLocally() {
  localStorage.removeItem(ACCESS);
  localStorage.removeItem(REFRESH);
}

export async function logout() {
  const token = localStorage.getItem(REFRESH);
  signOutLocally();
  if (token) await call("/v1/auth/logout", { method: "POST", auth: null, body: JSON.stringify({ refresh_token: token }) }).catch(() => undefined);
}

export const signedIn = () => Boolean(localStorage.getItem(ACCESS));
export const me = () => call("/v1/auth/me");
export const schema = () => call("/v1/schema");

export type Page<T = Record<string, any>> = { object: string; items: T[]; next: string | null };

export function list(object: string, params: Record<string, string> = {}): Promise<Page> {
  const query = new URLSearchParams(params).toString();
  return call(`/v1/${object}${query ? `?${query}` : ""}`);
}

export const get = (object: string, id: string) => call(`/v1/${object}/${id}`);
export const create = (object: string, values: Record<string, unknown>, key?: string) =>
  call(`/v1/${object}`, { method: "POST", body: JSON.stringify(values), ...(key ? { auth: key } : {}) });
export const update = (object: string, id: string, rowVersion: number, values: Record<string, unknown>) =>
  call(`/v1/${object}/${id}`, { method: "PATCH", body: JSON.stringify(values), headers: { "If-Match": `"${rowVersion}"` } });
export const archive = (object: string, id: string) => call(`/v1/${object}/${id}`, { method: "DELETE" });
