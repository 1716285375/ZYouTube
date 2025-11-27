export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8866";

const normalizedBase = API_BASE_URL.replace(/\/$/, "");

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

const ensureLeadingSlash = (path: string) =>
  path.startsWith("/") ? path : `/${path}`;

export const buildApiUrl = (path: string) => {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${normalizedBase}${ensureLeadingSlash(path)}`;
};

export const toPublicAssetUrl = (path?: string | null) => {
  if (!path) return null;
  return buildApiUrl(path);
};

export async function readError(response: Response) {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (data && Object.keys(data).length > 0) {
      return JSON.stringify(data);
    }
  } catch {
    // ignore json parse error
  }
  return await response.text();
}

const mergeHeaders = (
  input?: HeadersInit,
  extra?: Record<string, string>,
): Headers => {
  const headers = new Headers(input ?? {});
  if (extra) {
    Object.entries(extra).forEach(([key, value]) => {
      headers.set(key, value);
    });
  }
  return headers;
};

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(buildApiUrl(path), init);
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return (await response.json()) as T;
}

export async function postJson<T>(
  path: string,
  body: unknown,
  init?: RequestInit,
): Promise<T> {
  const headers = mergeHeaders(init?.headers, {
    "Content-Type": "application/json",
  });
  return requestJson<T>(path, {
    ...init,
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}


