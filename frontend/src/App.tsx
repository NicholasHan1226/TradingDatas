import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { ApiClient, ApiError, clearSession, loadSession, saveSession } from './lib/api'
import type { PortalMeResponse, Role } from './lib/types'
import { LoadingPanel, ToastProvider } from './components/ui'
import Login from './views/Login'
import { recordConsoleEvent } from './lib/consoleAnalytics'
import {
  clearWorkspaceRoute,
  commitWorkspaceRoute,
  defaultWorkspaceRoute,
  resolveWorkspaceRoute,
  routeHash,
  type WorkspaceRoute,
} from './lib/workspaceRoute'

const AdminApp = lazy(() => import('./views/admin/AdminApp'))
const CustomerApp = lazy(() => import('./views/customer/CustomerApp'))

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
  const [route, setRoute] = useState<WorkspaceRoute>({ workspace: 'admin', section: 'tokens' })

  const bootstrap = useCallback(async (token: string, base: string) => {
    const probe = new ApiClient(base, token)
    try {
      const me = await probe.get<PortalMeResponse>('/portal/api/me')
      const role = resolveRole(me.portal.scopes, me.portal.tier)
      const nextRoute = resolveWorkspaceRoute(role)
      setSession({
        client: probe,
        role,
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
      const next = resolveWorkspaceRoute(session.role)
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
        {session.role === 'admin' && route.workspace === 'admin' ? (
          <AdminApp
            client={session.client}
            section={route.section}
            onSectionChange={(section) => navigate({ workspace: 'admin', section })}
            onLogout={handleLogout}
            onViewCustomer={() => {
              recordConsoleEvent('workspace_switch', 'admin')
              navigate(defaultWorkspaceRoute('customer'))
            }}
          />
        ) : (
          <CustomerApp
            client={session.client}
            tenantId={session.tenantId}
            section={route.workspace === 'customer' ? route.section : 'overview'}
            docSection={route.workspace === 'customer' ? route.doc : 'quickstart'}
            onSectionChange={(section) => navigate({
              workspace: 'customer',
              section,
              doc: route.workspace === 'customer' ? route.doc : 'quickstart',
            })}
            onDocSectionChange={(doc) => navigate({ workspace: 'customer', section: 'docs', doc })}
            onLogout={handleLogout}
            onViewAdmin={session.role === 'admin' ? () => {
              recordConsoleEvent('workspace_switch', 'customer')
              navigate(defaultWorkspaceRoute('admin'))
            } : undefined}
          />
        )}
      </Suspense>
    </ToastProvider>
  )
}
