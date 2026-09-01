import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ApiClient } from './lib/api'
import { LoadingPanel, ToastProvider } from './components/ui'
import { commitWorkspaceRoute, resolveWorkspaceRoute, type WorkspaceRoute } from './lib/workspaceRoute'

const AdminApp = lazy(() => import('./views/admin/AdminApp'))
type AdminSession = { client: ApiClient; userId: string }

// Uses the same reviewed AdminApp; never creates a second customer dashboard.
export default function AccountAdminRoot() {
  const [session, setSession] = useState<AdminSession | null>(null)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [leaving, setLeaving] = useState(false)
  const [route, setRoute] = useState<WorkspaceRoute>(resolveWorkspaceRoute)
  const clientRef = useRef<ApiClient | null>(null)
  const epoch = useRef(0)
  const zh = (navigator.language || '').toLowerCase().startsWith('zh')

  useEffect(() => {
    const generation = ++epoch.current
    const controller = new AbortController()
    clientRef.current?.dispose(); clientRef.current = null; setSession(null); setChecking(true); setError('')
    const timer = setTimeout(() => controller.abort(), 12000)
    void (async () => {
      try {
        const response = await fetch('/api/account/me', { credentials: 'same-origin', signal: controller.signal })
        if (!response.ok) throw new Error('unavailable')
        const body = await response.json()
        if (generation !== epoch.current || controller.signal.aborted) return
        const identity = body?.identity
        const access = body?.data_access
        const portal = access?.portal
        if (identity?.kind !== 'email' || identity.email_verified !== true || typeof identity.user_id !== 'string'
          || body.capabilities?.admin_console !== true || access?.state !== 'connected' || access.admin !== true
          || !Array.isArray(portal?.scopes) || !(portal.scopes.includes('admin') || portal.tier === 'internal')) throw new Error('restricted')
        const client = new ApiClient(`${window.location.origin}/api/account/admin`, '', () => {
          clientRef.current?.dispose(); clientRef.current = null; ++epoch.current; setSession(null); setChecking(false); setError('changed')
        }, identity.user_id)
        clientRef.current = client; setSession({ client, userId: identity.user_id })
      } catch { if (generation === epoch.current) setError('restricted') }
      finally { clearTimeout(timer); if (generation === epoch.current) setChecking(false) }
    })()
    return () => { ++epoch.current; clearTimeout(timer); controller.abort(); clientRef.current?.dispose(); clientRef.current = null }
  }, [revision])
  useEffect(() => {
    const visibility = () => { if (document.visibilityState === 'visible') setRevision(value => value + 1) }
    const syncRoute = () => setRoute(resolveWorkspaceRoute())
    document.addEventListener('visibilitychange', visibility); window.addEventListener('hashchange', syncRoute)
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('hashchange', syncRoute) }
  }, [])
  async function signOut() {
    if (leaving || !session) return
    setLeaving(true); setError('')
    try {
      const response = await fetch('/api/account/session', {
        method: 'DELETE', credentials: 'same-origin', signal: AbortSignal.timeout(12000),
        headers: { 'X-TD-Identity': session.userId },
      })
      const receipt = await response.json().catch(() => null)
      if (!response.ok || receipt?.signed_out !== true || receipt?.user_id !== session.userId) throw new Error('unconfirmed')
      clientRef.current?.dispose(); ++epoch.current; setSession(null); window.location.assign('/account')
    } catch { setError('signout') }
    finally { setLeaving(false) }
  }
  if (checking) return <div className="flex h-full items-center justify-center"><LoadingPanel label={zh ? '正在验证账户与管理员权限…' : 'Verifying account and administrator access…'} /></div>
  if (!session) return <main className="mx-auto max-w-lg p-10"><h1 className="text-2xl font-semibold">{zh ? '管理员工作台' : 'Administrator workspace'}</h1><p className="my-6">{zh ? '需要已验证的邮箱与服务端确认的管理员权限。这里不会自动创建管理员账户，也不接受普通客户权限。' : 'A verified email and server-confirmed administrator access are required. This page never creates an administrator or accepts ordinary customer access.'}</p><a href="/account" className="underline">{zh ? '返回账户 · 连接与验证权限' : 'Return to Account · connect and verify access'}</a><button type="button" className="ml-6 underline" onClick={() => setRevision(value => value + 1)}>{zh ? '重新验证' : 'Verify again'}</button></main>
  return <ToastProvider>
    {error === 'signout' && <p role="alert" className="p-4">{zh ? '未能确认退出，仍保留会话。请重试。' : 'Sign-out was not confirmed; the session is retained. Please retry.'}</p>}
    <Suspense fallback={<LoadingPanel label={zh ? '正在打开工作台…' : 'Opening workspace…'} />}>
      <AdminApp key={session.userId} client={session.client} section={route.workspace === 'admin' ? route.section : 'tokens'}
        onSectionChange={section => { const next: WorkspaceRoute = { workspace: 'admin', section }; setRoute(next); commitWorkspaceRoute(next) }}
        onLogout={() => { void signOut() }} onViewCustomer={() => window.location.assign('/account')} />
    </Suspense>
  </ToastProvider>
}
