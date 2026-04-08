import { getCurrentUiLocale, translate } from "../i18n";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export function apiPath(path: string): string {
  return `${API_BASE}${path}`;
}

function previewUnavailableMessage(): string {
  return translate(getCurrentUiLocale(), "errors.api.previewUnavailable");
}

function shouldTreatAsStaticPreviewFailure(status: number, detail: string, contentType: string): boolean {
  const lowerDetail = detail.toLowerCase();
  const lowerType = contentType.toLowerCase();
  return (
    (status === 404 || status === 501)
    && (
      lowerType.includes("text/html")
      || lowerDetail.includes("file not found")
      || lowerDetail.includes("unsupported method")
    )
  );
}

async function readErrorDetail(response: Response): Promise<string> {
  const contentType = response.headers.get("Content-Type") ?? "";
  const payload = await response.json().catch(() => ({ detail: response.statusText }));
  const detail = String(payload.detail || response.statusText || "").trim();

  if (shouldTreatAsStaticPreviewFailure(response.status, detail, contentType)) {
    return previewUnavailableMessage();
  }

  return detail;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiPath(path), {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(previewUnavailableMessage());
    }
    throw error;
  }

  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function requestForm<T>(path: string, formData: FormData, init?: Omit<RequestInit, "body">): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiPath(path), {
      method: "POST",
      ...init,
      body: formData,
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(previewUnavailableMessage());
    }
    throw error;
  }

  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }

  return response.json() as Promise<T>;
}
