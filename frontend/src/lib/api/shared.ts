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

async function extractErrorMessage(res: Response): Promise<string | null> {
  try {
    const clone = res.clone();
    const contentType = clone.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await clone.json();
      if (typeof data?.message === "string" && data.message.trim()) return data.message.trim();
      if (typeof data?.detail === "string" && data.detail.trim()) return data.detail.trim();
    }
    const text = (await clone.text()).trim();
    if (text) return text.slice(0, 240);
  } catch {
    // ignore parse errors
  }
  return null;
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
    const errMsg = await extractErrorMessage(res);
    apiWarn(`${res.url} -> HTTP ${res.status}`);
    if (!options?.silent) {
      if (errMsg) emitToast(errMsg, res.status >= 500 ? "error" : "warn");
      else if (res.status >= 500) emitToast(`Server error (${res.status}) — please try again later`);
    }
    if (fallback && typeof fallback === "object") {
      const next = { ...(fallback as object) } as Record<string, unknown>;
      if ("status" in next) next.status = "error";
      if ("message" in next && errMsg) next.message = errMsg;
      if ("detail" in next && errMsg) next.detail = errMsg;
      return next as T;
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

type ActionRunnerOptions = {
  errorMessage?: string;
};

export function taskActionKey(taskType: string, topicId: number | string | null | undefined): string {
  return `task:${taskType}:${topicId ?? "all"}`;
}

export function uiActionKey(scope: string, id: string | number): string {
  return `ui:${scope}:${id}`;
}

export async function runWithAction<T>(
  actionKey: string,
  task: () => Promise<T>,
  options?: ActionRunnerOptions,
): Promise<T> {
  let store: { beginAction: (key: string) => void; endAction: (key: string, status: "success" | "error", error?: string | null, result?: string | null) => void; } | null = null;
  try {
    // Dynamic require avoids circular dependency with store<->api imports.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { useStore } = require("@/stores/useStore");
    store = useStore.getState();
    store?.beginAction(actionKey);
  } catch {
    store = null;
  }

  try {
    const result = await task();
    store?.endAction(actionKey, "success");
    return result;
  } catch (e) {
    const message =
      e instanceof Error && e.message
        ? e.message
        : options?.errorMessage || "Action failed";
    store?.endAction(actionKey, "error", message);
    throw e;
  }
}

export { BASE, DEV };
