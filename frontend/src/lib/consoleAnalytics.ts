import { useSyncExternalStore } from 'react'

export type ConsoleWorkspace = 'admin' | 'customer'
export type ConsoleEvent =
  | 'login_success'
  | 'workspace_view'
  | 'workspace_switch'
  | 'copy_succeeded'
  | 'credential_created'
  | 'credential_updated'
  | 'credential_toggled'
  | 'credential_deleted'
  | 'dataset_query_succeeded'
  | 'request_failed'

interface WorkspaceMetrics {
  views: number
  actions: number
  completions: number
  errors: number
}

export interface ConsoleAnalyticsSnapshot {
  version: 1
  since: string
  updated_at: string
  total_events: number
  workspaces: Record<ConsoleWorkspace, WorkspaceMetrics>
  events: Partial<Record<ConsoleEvent, number>>
}

const STORAGE_KEY = 'td.console.analytics.aggregate.v1'
const CHANGE_EVENT = 'td-console-analytics-change'
const EMPTY_WORKSPACE: WorkspaceMetrics = { views: 0, actions: 0, completions: 0, errors: 0 }

function emptySnapshot(): ConsoleAnalyticsSnapshot {
  const now = new Date().toISOString()
  return {
    version: 1,
    since: now,
    updated_at: now,
    total_events: 0,
    workspaces: {
      admin: { ...EMPTY_WORKSPACE },
      customer: { ...EMPTY_WORKSPACE },
    },
    events: {},
  }
}

let cachedRaw = ''
let cachedSnapshot = emptySnapshot()

export function readConsoleAnalytics(): ConsoleAnalyticsSnapshot {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) ?? ''
    if (!raw) return cachedSnapshot
    if (raw === cachedRaw) return cachedSnapshot
    const parsed = JSON.parse(raw) as ConsoleAnalyticsSnapshot
    if (parsed.version !== 1) return emptySnapshot()
    cachedRaw = raw
    cachedSnapshot = parsed
    return parsed
  } catch {
    return emptySnapshot()
  }
}

function metricFor(event: ConsoleEvent): keyof WorkspaceMetrics {
  if (event === 'workspace_view' || event === 'login_success') return 'views'
  if (event === 'request_failed') return 'errors'
  if (event.endsWith('_succeeded') || event.startsWith('credential_')) return 'completions'
  return 'actions'
}

export function recordConsoleEvent(event: ConsoleEvent, workspace: ConsoleWorkspace): void {
  const current = readConsoleAnalytics()
  const next: ConsoleAnalyticsSnapshot = {
    ...current,
    updated_at: new Date().toISOString(),
    total_events: current.total_events + 1,
    workspaces: {
      ...current.workspaces,
      [workspace]: {
        ...current.workspaces[workspace],
        [metricFor(event)]: current.workspaces[workspace][metricFor(event)] + 1,
      },
    },
    events: { ...current.events, [event]: (current.events[event] ?? 0) + 1 },
  }
  try {
    const raw = JSON.stringify(next)
    localStorage.setItem(STORAGE_KEY, raw)
    cachedRaw = raw
    cachedSnapshot = next
    window.dispatchEvent(new Event(CHANGE_EVENT))
  } catch {
    // Analytics is local-only and never blocks the product workflow.
  }
}

export function resetConsoleAnalytics(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
    cachedRaw = ''
    cachedSnapshot = emptySnapshot()
    window.dispatchEvent(new Event(CHANGE_EVENT))
  } catch {
    // Ignore unavailable storage.
  }
}

function subscribe(listener: () => void) {
  window.addEventListener(CHANGE_EVENT, listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener)
    window.removeEventListener('storage', listener)
  }
}

export function useConsoleAnalytics(): ConsoleAnalyticsSnapshot {
  return useSyncExternalStore(subscribe, readConsoleAnalytics, emptySnapshot)
}
