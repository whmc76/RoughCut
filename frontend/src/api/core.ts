const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export function apiPath(path: string): string {
  return `${API_BASE}${path}`;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function requestForm<T>(path: string, formData: FormData, init?: Omit<RequestInit, "body">): Promise<T> {
  const response = await fetch(apiPath(path), {
    method: "POST",
    ...init,
    body: formData,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || response.statusText);
  }

  return response.json() as Promise<T>;
}
