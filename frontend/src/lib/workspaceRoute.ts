import { readStoredValue, writeStoredValue } from './persistence'

export const ADMIN_SECTIONS = ['tokens', 'usage', 'collection', 'health', 'browser'] as const
export type AdminSection = (typeof ADMIN_SECTIONS)[number]
export type WorkspaceRoute = { workspace: 'admin'; section: AdminSection }

const ADMIN_KEY = 'td.console.route.admin.v1'

function isAdminSection(value: string | undefined): value is AdminSection {
  return Boolean(value && ADMIN_SECTIONS.includes(value as AdminSection))
}

function normalizeSection(value: string | undefined): AdminSection {
  if (value === 'collection') return 'health'
  return isAdminSection(value) ? value : 'tokens'
}

export function defaultWorkspaceRoute(): WorkspaceRoute {
  return { workspace: 'admin', section: normalizeSection(readStoredValue<AdminSection>(ADMIN_KEY, 'tokens')) }
}

export function resolveWorkspaceRoute(hash = window.location.hash): WorkspaceRoute {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'admin') return { workspace: 'admin', section: normalizeSection(parts[1]) }
  return defaultWorkspaceRoute()
}

export function routeHash(route: WorkspaceRoute): string {
  return `#/admin/${route.section}`
}

export function saveWorkspaceRoute(route: WorkspaceRoute): void {
  writeStoredValue(ADMIN_KEY, route.section)
}

export function commitWorkspaceRoute(route: WorkspaceRoute, replace = false): void {
  saveWorkspaceRoute(route)
  const next = `${window.location.pathname}${window.location.search}${routeHash(route)}`
  if (replace) window.history.replaceState(null, '', next)
  else window.history.pushState(null, '', next)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export function clearWorkspaceRoute(): void {
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
}
