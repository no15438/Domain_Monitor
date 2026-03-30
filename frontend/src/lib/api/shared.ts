const BASE =
  typeof window !== "undefined" && process.env.NEXT_PUBLIC_API_BASE
    ? process.env.NEXT_PUBLIC_API_BASE
    : "http://localhost:8000";

const DEV = process.env.NODE_ENV === "development";

function apiWarn(msg: string, ...args: unknown[]) {
  if (DEV) console.warn(`[api] ${msg}`, ...args);
}

function emitToast(
  message: string,
  level: "error" | "warn" | "info" = "error",
) {
  try {
    // Dynamic require avoids circular reference since store imports from api.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { useStore } = require("@/stores/useStore");
    useStore.getState().addToast(message, level);
  } catch {
    // Store is not ready yet.
  }
}

export async function fetchWithRetry(
  url: string,
  options?: RequestInit,
  maxRetries = 2,
): Promise<Response> {
  const delays = [1000, 3000];
  let lastError: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || (res.status >= 400 && res.status < 500)) return res;
      lastError = new Error(`HTTP ${res.status}`);
    } catch (e) {
      lastError = e;
      if (options?.signal?.aborted) throw e;
    }
    if (attempt < maxRetries) {
      await new Promise((resolve) =>
        setTimeout(resolve, delays[attempt] ?? 3000),
      );
    }
  }
  throw lastError;
}

export async function safeJson<T>(
  res: Response,
  fallback: T,
  shape?: (keyof NonNullable<T & object>)[],
  options?: { silent?: boolean },
): Promise<T> {
  if (!res.ok) {
    apiWarn(`${res.url} -> HTTP ${res.status}`);
    if (!options?.silent && res.status >= 500) {
      emitToast(`Server error (${res.status}) — please try again later`);
    }
    return fallback;
  }
  let data: T;
  try {
    data = await res.json();
  } catch (e) {
    apiWarn(`${res.url} -> invalid JSON`, e);
    if (!options?.silent) emitToast("Received invalid response from server", "warn");
    return fallback;
  }
  if (shape && data != null && typeof data === "object") {
    const missing = shape.filter((key) => !(key in (data as object)));
    if (missing.length > 0) {
      apiWarn(`${res.url} -> response missing fields: ${missing.join(", ")}`, data);
    }
  }
  return data;
}

export { BASE, DEV };
