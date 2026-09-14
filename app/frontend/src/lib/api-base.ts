/**
 * Resolve API base URL for browser calls.
 * Prefer VITE_API_URL when set to a real non-localhost value; otherwise
 * same-origin /api (Elestio nginx proxies /api → backend).
 */
export function getApiBaseUrl(): string {
  const fromEnv = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  const looksLocal =
    !fromEnv ||
    fromEnv.includes("localhost") ||
    fromEnv.includes("127.0.0.1");

  if (typeof window !== "undefined" && window.location?.origin) {
    const onHttps = window.location.protocol === "https:";
    if (looksLocal && onHttps) {
      return `${window.location.origin}/api`;
    }
  }

  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }

  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}/api`;
  }
  return "http://localhost:8000";
}
