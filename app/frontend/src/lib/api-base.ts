/**
 * Resolve API base URL for browser calls.
 * Prefer VITE_API_URL when set at build time; otherwise same-origin /api
 * (Elestio nginx proxies /api → backend).
 */
export function getApiBaseUrl(): string {
  const fromEnv = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}/api`;
  }
  return "http://localhost:8000";
}
