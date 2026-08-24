import type { Role } from './types'
import { readStoredValue, writeStoredValue } from './persistence'

export const ADMIN_SECTIONS = ['tokens', 'usage', 'collection', 'health', 'browser'] as const
export const CUSTOMER_SECTIONS = ['overview', 'access', 'docs'] as const
export const DOC_SECTIONS = ['quickstart', 'agents', 'reference'] as const

export type AdminSection = (typeof ADMIN_SECTIONS)[number]
export type CustomerSection = (typeof CUSTOMER_SECTIONS)[number]
export type DocSection = (typeof DOC_SECTIONS)[number]

export type WorkspaceRoute =
  | { workspace: 'admin'; section: AdminSection }
  | { workspace: 'customer'; section: CustomerSection; doc: DocSection }

const ADMIN_KEY = 'td.console.route.admin.v1'
const CUSTOMER_KEY = 'td.console.route.customer.v1'

function includes<T extends string>(values: readonly T[], value: string | undefined): value is T {
  return Boolean(value && values.includes(value as T))
}

export function defaultWorkspaceRoute(role: Role): WorkspaceRoute {
  if (role === 'admin') {
    const section = readStoredValue<AdminSection>(ADMIN_KEY, 'tokens')
    return { workspace: 'admin', section: includes(ADMIN_SECTIONS, section) ? section : 'tokens' }
  }
  const stored = readStoredValue<{ section: CustomerSection; doc: DocSection }>(CUSTOMER_KEY, {
    section: 'overview',
    doc: 'quickstart',
  })
  return {
    workspace: 'customer',
    section: includes(CUSTOMER_SECTIONS, stored.section) ? stored.section : 'overview',
    doc: includes(DOC_SECTIONS, stored.doc) ? stored.doc : 'quickstart',
  }
}

export function resolveWorkspaceRoute(role: Role, hash = window.location.hash): WorkspaceRoute {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (role === 'admin' && parts[0] === 'admin' && includes(ADMIN_SECTIONS, parts[1])) {
    return { workspace: 'admin', section: parts[1] }
  }
  if (parts[0] === 'portal' && includes(CUSTOMER_SECTIONS, parts[1])) {
    return {
      workspace: 'customer',
      section: parts[1],
      doc: includes(DOC_SECTIONS, parts[2]) ? parts[2] : 'quickstart',
    }
  }
  return defaultWorkspaceRoute(role)
}

export function routeHash(route: WorkspaceRoute): string {
  if (route.workspace === 'admin') return `#/admin/${route.section}`
  return route.section === 'docs'
    ? `#/portal/docs/${route.doc}`
    : `#/portal/${route.section}`
}

export function saveWorkspaceRoute(route: WorkspaceRoute): void {
  if (route.workspace === 'admin') {
    writeStoredValue(ADMIN_KEY, route.section)
    return
  }
  writeStoredValue(CUSTOMER_KEY, { section: route.section, doc: route.doc })
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
