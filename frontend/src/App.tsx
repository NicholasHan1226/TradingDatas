import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { ApiClient, ApiError, clearSession, loadSession, saveSession } from './lib/api'
import type { PortalMeResponse } from './lib/types'
import { LoadingPanel, ToastProvider } from './components/ui'
import Login from './views/Login'
import { recordConsoleEvent } from './lib/consoleAnalytics'
import {
  clearWorkspaceRoute,
  commitWorkspaceRoute,
  resolveWorkspaceRoute,
  routeHash,
  type WorkspaceRoute,
} from './lib/workspaceRoute'

const AdminApp = lazy(() => import('./views/admin/AdminApp'))
const AccountAdminRoot = lazy(() => import('./AccountAdminRoot'))

interface Session {
  client: ApiClient
  tenantId: string
  tier: string
}

function hasAdminAccess(scopes: string[], tier: string): boolean {
  // Mirrors the backend admin gate: "admin" scope or internal tier.
  return scopes.includes('admin') || tier === 'internal'
}

export default function App() {
  if (window.location.pathname === '/admin' || window.location.pathname.startsWith('/admin/')) {
    return <Suspense fallback={<LoadingPanel label="正在验证账户…" />}><AccountAdminRoot /></Suspense>
  }
  return <StandaloneAdminApp />
}
function StandaloneAdminApp() {
  const [session, setSession] = useState<Session | null>(null)
  const [booting, setBooting] = useState(true)
  const [route, setRoute] = useState<WorkspaceRoute>({ workspace: 'admin', section: 'tokens' })

  const bootstrap = useCallback(async (token: string, base: string) => {
    const probe = new ApiClient(base, token)
    try {
      const me = await probe.get<PortalMeResponse>('/portal/api/me')
      if (!hasAdminAccess(me.portal.scopes, me.portal.tier)) {
        clearSession()
        return '用户账户已合并到 tradingdatas.com/account，请从官网 Account 连接。'
      }
      const nextRoute = resolveWorkspaceRoute()
      setSession({
        client: probe,
        tenantId: me.portal.tenant_id,
        tier: me.portal.tier,
      })
      setRoute(nextRoute)
      commitWorkspaceRoute(nextRoute, true)
      recordConsoleEvent('login_success', nextRoute.workspace)
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

  useEffect(() => {
    if (!session) return
    const syncFromLocation = () => {
      const next = resolveWorkspaceRoute()
      setRoute(next)
      if (window.location.hash !== routeHash(next)) {
        commitWorkspaceRoute(next, true)
      }
    }
    window.addEventListener('hashchange', syncFromLocation)
    window.addEventListener('popstate', syncFromLocation)
    return () => {
      window.removeEventListener('hashchange', syncFromLocation)
      window.removeEventListener('popstate', syncFromLocation)
    }
  }, [session])

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
    clearWorkspaceRoute()
  }, [])

  const navigate = useCallback((next: WorkspaceRoute) => {
    setRoute(next)
    commitWorkspaceRoute(next)
    recordConsoleEvent('workspace_view', next.workspace)
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
      <Suspense fallback={<div className="flex h-full items-center justify-center"><LoadingPanel label="正在打开工作台…" /></div>}>
        <AdminApp
          client={session.client}
          section={route.workspace === 'admin' ? route.section : 'tokens'}
          onSectionChange={(section) => navigate({ workspace: 'admin', section })}
          onLogout={handleLogout}
          onViewCustomer={() => {
            window.location.assign('https://tradingdatas.com/account')
          }}
        />
      </Suspense>
    </ToastProvider>
  )
}
