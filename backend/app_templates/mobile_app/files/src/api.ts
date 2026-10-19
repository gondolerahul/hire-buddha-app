// Sign-in with the HireBuddha Data API; everything else through the app's own backend.
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, string>;
const ACCESS = "hb.access";
const REFRESH = "hb.refresh";

async function post(url: string, body: unknown) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

export async function signIn(email: string, password: string) {
  const tokens = await post(`${extra.dataApiUrl}/v1/auth/login`, { tenant: extra.tenant, app: extra.app, email, password });
  await SecureStore.setItemAsync(ACCESS, tokens.access_token);
  await SecureStore.setItemAsync(REFRESH, tokens.refresh_token);
}

export async function signOut() {
  await SecureStore.deleteItemAsync(ACCESS);
  await SecureStore.deleteItemAsync(REFRESH);
}

async function refresh(): Promise<boolean> {
  const token = await SecureStore.getItemAsync(REFRESH);
  if (!token) return false;
  try {
    const tokens = await post(`${extra.dataApiUrl}/v1/auth/refresh`, { refresh_token: token });
    await SecureStore.setItemAsync(ACCESS, tokens.access_token);
    await SecureStore.setItemAsync(REFRESH, tokens.refresh_token);
    return true;
  } catch {
    await signOut();
    return false;
  }
}

export async function backend(path: string, init: RequestInit = {}, retried = false): Promise<any> {
  const token = await SecureStore.getItemAsync(ACCESS);
  const response = await fetch(`${extra.backendUrl}${path}`, { ...init,
    headers: { ...(init.headers || {}), Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
  if (response.status === 401 && !retried && (await refresh())) return backend(path, init, true);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
