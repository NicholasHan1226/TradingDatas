// Thin API client for the TradingDatas console.
//
// Standalone console remains bearer-only. The public site's /admin/ entry uses
// a same-origin identity gateway; cookies NEVER go to the wildcard-CORS backend.

export const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE || 'https://td-admin-api.tradingagent.cc'

const TOKEN_KEY = 'td_app_token'
const BASE_KEY = 'td_app_base'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export function loadSession(): { token: string; base: string } {
  let token = ''
  let base = DEFAULT_API_BASE
  try {
    token = localStorage.getItem(TOKEN_KEY) ?? ''
    base = localStorage.getItem(BASE_KEY) || DEFAULT_API_BASE
  } catch {
    // Storage unavailable (private mode etc.) — fall back to in-memory only.
  }
  return { token, base }
}

export function saveSession(token: string, base: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(BASE_KEY, base)
  } catch {
    // Non-fatal: session still works for this page lifetime.
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Ignore.
  }
}

export class ApiClient {
  private base: string
  private token: string
  private onUnauthorized?: () => void
  private identity?: string
  private requests = new Set<AbortController>()
  private disposed = false

  constructor(base: string, token: string, onUnauthorized?: () => void, identity?: string) {
    this.base = base.replace(/\/+$/, '')
    this.token = token
    this.onUnauthorized = onUnauthorized
    this.identity = identity
    if (identity && new URL(this.base).origin !== window.location.origin) throw new Error('Account gateway must be same-origin')
  }

  get baseUrl(): string {
    return this.base
  }

  get bearerToken(): string {
    return this.token
  }
  dispose(): void {
    this.disposed = true
    for (const request of this.requests) request.abort()
    this.requests.clear()
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    query?: Record<string, string>,
  ): Promise<T> {
    if (this.disposed) throw new ApiError(401, 'session_changed', '账户会话已改变，请重新验证')
    const url = new URL(this.base + path)
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        url.searchParams.set(key, value)
      }
    }
    let response: Response
    let payload: unknown = null
    const controller = new AbortController()
    this.requests.add(controller)
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      response = await fetch(url.toString(), {
        method,
        headers: {
          ...(this.identity ? { 'X-TD-Identity': this.identity } : { Authorization: `Bearer ${this.token}` }),
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        },
        credentials: this.identity ? 'same-origin' : 'omit',
        signal: controller.signal,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      })
      try { payload = await response.json() } catch { /* Generic error for non-JSON responses. */ }
      if (controller.signal.aborted) throw new Error('request_aborted')
    } catch {
      throw new ApiError(0, 'network_error', '无法连接到 API 服务，请检查网络或 API 地址')
    } finally {
      clearTimeout(timeout)
      this.requests.delete(controller)
    }
    if (this.disposed) throw new ApiError(401, 'session_changed', '账户会话已改变，请重新验证')
    if (!response.ok) {
      if (response.status === 401 || (this.identity && [403, 409].includes(response.status))) {
        this.onUnauthorized?.()
      }
      const err = (payload as { error?: { code?: string; message?: string } })?.error
      throw new ApiError(
        response.status,
        err?.code ?? 'http_error',
        err?.message ??
          (response.status === 401
            ? 'API 密钥无效或已失效'
            : `请求失败 (${response.status})`),
      )
    }
    return payload as T
  }

  get<T>(path: string, query?: Record<string, string>): Promise<T> {
    return this.request<T>('GET', path, undefined, query)
  }

  post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>('POST', path, body)
  }

  patch<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>('PATCH', path, body)
  }

  del<T>(path: string): Promise<T> {
    return this.request<T>('DELETE', path)
  }
}
