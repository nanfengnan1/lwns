export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
let token = "";
export function setToken(value: string) {
  token = value.trim();
}
export function getToken() {
  return token;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ApiError(
      `后端未返回 JSON (${response.status})，请检查后端与 API 代理`,
      response.status,
    );
  }
  if (!response.ok)
    throw new ApiError(
      (data as { error?: string }).error || `请求失败 (${response.status})`,
      response.status,
    );
  return data as T;
}
