// Shared API response types for the TradingDatas console.
// Shapes mirror api_server.py / auth.py responses exactly.

export interface PortalInfo {
  tenant_id: string
  tier: string
  scopes: string[]
  enabled: boolean
  max_concurrent: number | null
  hourly_request_limit: number | null
  daily_limit: number | null
  expires_at: string | null
  usage: {
    today_date: string | null
    today_count: number
    hourly_count: number
    hourly_window_seconds: number
  }
}

export interface PortalMeResponse {
  api_version: string
  request_id: string
  portal: PortalInfo
}

export interface PortalUsageResponse {
  api_version: string
  request_id: string
  portal_usage: {
    tenant_id: string
    daily_limit: number | null
    today_count: number
    history: { date: string; total: number }[]
  }
}

export interface AdminToken {
  token_hash_masked?: string
  token_hash_full: string
  tenant_id: string
  tier: string
  scopes: string[]
  enabled: boolean
  daily_limit?: number | null
  daily_usage?: number
  max_concurrent?: number | null
  expires_at?: string | null
  expired?: boolean
}

export interface TokensResponse {
  tokens: AdminToken[]
  count?: number
}

export interface UsageOverview {
  daily: Record<
    string,
    { date: string; count: number; daily_limit: number | null }
  >
  hourly: Record<
    string,
    { count_in_window: number; tier_limit: number | null; window_seconds: number }
  >
  cache?: {
    dedup_entries?: number
    dedup_bytes?: number
    active_requests?: number
    request_log_tenants?: number
  }
}

export interface DatasetRow {
  dataset_id: string
  provider: string
  market: string
  domain?: string
  cadence: string
  activation: string
  entitlement: string
  runtime_state?: string
  degraded?: boolean
  freshness_state?: string
  data_through?: string | null
  observed_at?: string | null
  reasons?: string[]
}

export interface CollectionStatus {
  datasets: DatasetRow[]
  total: number
  active?: number
  paused?: number
}

export interface HealthAlert {
  severity: 'critical' | 'warning' | 'info' | string
  title: string
  detail?: string
}

export interface DataOverview {
  total_datasets?: number
  by_market?: Record<string, number>
  by_provider?: Record<string, number>
  by_cadence?: Record<string, number>
}

export interface QueryResult {
  data?: { items?: Record<string, unknown>[]; fields?: string[] }
  items?: Record<string, unknown>[]
  fields?: string[]
  next_cursor?: string | null
}

export type Role = 'admin' | 'customer'
