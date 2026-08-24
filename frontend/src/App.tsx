import { useCallback, useEffect, useState } from 'react'
import { ApiClient, clearSession, loadSession, saveSession } from './lib/api'
import type { PortalMeResponse, Role } from './lib/types'
import { ToastProvider } from './components/ui'
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
      <div className="flex h-full flex-col items-center justify-center gap-5 bg-slate-100 dark:bg-slate-950">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-600/30">
          <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6 text-white">
            <path d="M4 17l5-7 4.5 3.5L20 5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M4 21h16" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity=".45" />
          </svg>
        </div>
        <p className="text-sm text-slate-400 dark:text-slate-500">正在验证密钥…</p>
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
