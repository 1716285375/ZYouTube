// 在开发模式下，使用相对路径（通过Vite代理）
// 在生产模式下，使用完整的API_BASE_URL
const isDev = import.meta.env.DEV;
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

// 开发模式下使用相对路径，生产模式下使用配置的URL或默认值
const normalizedBase = isDev
  ? "" // 开发模式：使用相对路径，Vite会代理到后端
  : (apiBaseUrl || "http://localhost:8866").replace(/\/$/, "");

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
  // 如果已经是完整URL，直接返回
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  // 开发模式：使用相对路径
  if (isDev) {
    return ensureLeadingSlash(path);
  }
  // 生产模式：使用完整URL
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


