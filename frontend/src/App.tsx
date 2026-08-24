import { useCallback, useEffect, useState } from 'react'
import { ApiClient, ApiError, clearSession, loadSession, saveSession } from './lib/api'
import type { PortalMeResponse, Role } from './lib/types'
import { LoadingPanel, ToastProvider } from './components/ui'
import Login from './views/Login'
import AdminApp from './views/admin/AdminApp'
import CustomerApp from './views/customer/CustomerApp'

interface Session {
  client: ApiClient
  role: Role
  tenantId: string
  tier: string
}

function resolveRole(scopes: string[], tier: string): Role {
  // Mirrors the backend admin gate: "admin" scope or internal tier.
  return scopes.includes('admin') || tier === 'internal' ? 'admin' : 'customer'
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [booting, setBooting] = useState(true)

  const bootstrap = useCallback(async (token: string, base: string) => {
    const probe = new ApiClient(base, token)
    try {
      const me = await probe.get<PortalMeResponse>('/portal/api/me')
      setSession({
        client: probe,
        role: resolveRole(me.portal.scopes, me.portal.tier),
        tenantId: me.portal.tenant_id,
        tier: me.portal.tier,
      })
      return null
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        return '访问密钥未被当前服务识别。请使用当前有效密钥，或联系管理员重置。'
      }
      return err instanceof Error ? err.message : '登录失败，请稍后重试'
    }
  }, [])

  useEffect(() => {
    const { token, base } = loadSession()
    if (!token) {
      setBooting(false)
      return
    }
    bootstrap(token, base).finally(() => setBooting(false))
  }, [bootstrap])

  const handleLogin = useCallback(
    async (token: string, base: string) => {
      const error = await bootstrap(token, base)
      if (error === null) saveSession(token, base)
      return error
    },
    [bootstrap],
  )

  const handleLogout = useCallback(() => {
    clearSession()
    setSession(null)
  }, [])

  if (booting) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingPanel label="正在验证密钥…" />
      </div>
    )
  }

  if (!session) {
    return <Login onLogin={handleLogin} />
  }

  return (
    <ToastProvider>
      {session.role === 'admin' ? (
        <AdminApp client={session.client} onLogout={handleLogout} />
      ) : (
        <CustomerApp
          client={session.client}
          tenantId={session.tenantId}
          onLogout={handleLogout}
        />
      )}
    </ToastProvider>
  )
}
