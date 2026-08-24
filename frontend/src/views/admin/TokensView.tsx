import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../lib/api'
import type { AdminToken, TokensResponse } from '../../lib/types'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ControlBar,
  CopyButton,
  EmptyState,
  ErrorBanner,
  Field,
  LoadingPanel,
  Modal,
  PageIntro,
  ProgressBar,
  SearchField,
  ScopeChip,
  SelectInput,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TIER_LABELS,
  TIER_TONES,
  TextInput,
  ToggleSwitch,
  fmtNumber,
  useToast,
} from '../../components/ui'

const SCOPE_OPTIONS = ['read', 'query', 'catalog', 'admin']

const SCOPE_HINTS: Record<string, string> = {
  read: '读取数据（含目录与查询）',
  query: '仅查询端点',
  catalog: '仅目录端点',
  admin: '管理台（谨慎授予）',
}

interface TokenForm {
  tenant_id: string
  tier: string
  scopes: string[]
  customScopes: string
  daily_limit: string
  max_concurrent: string
  expires_at: string // yyyy-mm-dd or ''
}

const EMPTY_FORM: TokenForm = {
  tenant_id: '',
  tier: 'starter',
  scopes: ['read'],
  customScopes: '',
  daily_limit: '',
  max_concurrent: '',
  expires_at: '',
}

function formFromToken(t: AdminToken): TokenForm {
  return {
    tenant_id: t.tenant_id,
    tier: t.tier,
    scopes: t.scopes.filter((s) => SCOPE_OPTIONS.includes(s)),
    customScopes: t.scopes.filter((s) => !SCOPE_OPTIONS.includes(s)).join(', '),
    daily_limit: t.daily_limit != null ? String(t.daily_limit) : '',
    max_concurrent: t.max_concurrent != null ? String(t.max_concurrent) : '',
    expires_at: t.expires_at ? t.expires_at.slice(0, 10) : '',
  }
}

function buildPayload(form: TokenForm): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    tenant_id: form.tenant_id.trim(),
    tier: form.tier,
    scopes: [
      ...form.scopes,
      ...form.customScopes
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    ],
  }
  if (form.daily_limit.trim()) payload.daily_limit = parseInt(form.daily_limit, 10)
  if (form.max_concurrent.trim()) payload.max_concurrent = parseInt(form.max_concurrent, 10)
  if (form.expires_at) payload.expires_at = new Date(form.expires_at + 'T00:00:00Z').toISOString()
  return payload
}

export default function TokensView({ client }: { client: ApiClient }) {
  const toast = useToast()
  const [tokens, setTokens] = useState<AdminToken[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [busyHash, setBusyHash] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<TokenForm>(EMPTY_FORM)
  const [creating, setCreating] = useState(false)
  const [revealedToken, setRevealedToken] = useState<string | null>(null)

  const [editTarget, setEditTarget] = useState<AdminToken | null>(null)
  const [editForm, setEditForm] = useState<TokenForm>(EMPTY_FORM)
  const [editing, setEditing] = useState(false)

  const [deleteTarget, setDeleteTarget] = useState<AdminToken | null>(null)
  const [deleting, setDeleting] = useState(false)

  const reload = useCallback(async () => {
    setError(null)
    try {
      const data = await client.get<TokensResponse>('/admin/api/tokens')
      setTokens([...data.tokens].sort((a, b) => a.tenant_id.localeCompare(b.tenant_id)))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    }
  }, [client])

  useEffect(() => {
    void reload()
  }, [reload])

  const filtered = useMemo(() => {
    if (!tokens) return []
    const q = search.trim().toLowerCase()
    if (!q) return tokens
    return tokens.filter(
      (t) =>
        t.tenant_id.toLowerCase().includes(q) ||
        t.tier.toLowerCase().includes(q) ||
        t.scopes.some((s) => s.toLowerCase().includes(q)),
    )
  }, [tokens, search])

  const toggleEnabled = async (t: AdminToken) => {
    setBusyHash(t.token_hash_full)
    try {
      await client.patch(`/admin/api/tokens/${t.token_hash_full}`, { enabled: !t.enabled })
      toast('ok', t.enabled ? `已暂停 ${t.tenant_id}` : `已恢复 ${t.tenant_id}`)
      await reload()
    } catch (err) {
      toast('err', err instanceof Error ? err.message : '操作失败')
    } finally {
      setBusyHash(null)
    }
  }

  const submitCreate = async () => {
    const form = createForm
    if (!form.tenant_id.trim()) {
      toast('err', '请填写客户 ID')
      return
    }
    setCreating(true)
    try {
      const result = await client.post<{ token?: string }>('/admin/api/tokens', buildPayload(form))
      if (result.token) setRevealedToken(result.token)
      else toast('err', '创建返回异常：未包含密钥')
      setCreateOpen(false)
      setCreateForm(EMPTY_FORM)
      await reload()
    } catch (err) {
      toast('err', err instanceof Error ? err.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const submitEdit = async () => {
    if (!editTarget) return
    setEditing(true)
    try {
      await client.patch(`/admin/api/tokens/${editTarget.token_hash_full}`, buildPayload(editForm))
      toast('ok', `已更新 ${editTarget.tenant_id}`)
      setEditTarget(null)
      await reload()
    } catch (err) {
      toast('err', err instanceof Error ? err.message : '更新失败')
    } finally {
      setEditing(false)
    }
  }

  const submitDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await client.del(`/admin/api/tokens/${deleteTarget.token_hash_full}`)
      toast('ok', `已删除 ${deleteTarget.tenant_id}`)
      setDeleteTarget(null)
      await reload()
    } catch (err) {
      toast('err', err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="ACCESS CONTROL"
        title="客户与访问凭证"
        description="集中管理客户套餐、访问范围与调用上限；变更会即时写入当前服务。"
      />
      <ControlBar>
        <SearchField
          className="min-w-56 flex-1"
          aria-label="搜索客户密钥"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索客户 ID / 套餐 / 权限…"
        />
        <Button variant="secondary" onClick={() => void reload()}>
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
            <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 1 0 0-1.5H4.598a.75.75 0 0 0-.75.75v3.998a.75.75 0 0 0 1.5 0v-2.993l.358.357a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.106-.799ZM5.25 6.747a5.5 5.5 0 0 1 9.201-2.466l.312.311V3.626a.75.75 0 0 1 1.5 0V7.62a.75.75 0 0 1-.75.75h-4.116a.75.75 0 0 1 0-1.5h2.33l-.357-.357a7 7 0 0 0-11.712 3.138.75.75 0 0 0 1.106.8Z" clipRule="evenodd" />
          </svg>
          刷新
        </Button>
        <Button
          onClick={() => {
            setCreateForm(EMPTY_FORM)
            setCreateOpen(true)
          }}
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
            <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
          </svg>
          新建客户密钥
        </Button>
      </ControlBar>

      {error && <ErrorBanner message={error} />}

      <Card title="访问凭证" action={<span className="text-xs text-slate-400">{filtered.length} 项</span>} className="overflow-hidden" bodyClassName="!p-0">
        {tokens === null ? (
          <LoadingPanel />
        ) : error ? (
          <div className="p-5" />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={tokens.length === 0 ? '还没有任何客户密钥' : '没有匹配的客户'}
            hint={tokens.length === 0 ? '点击右上角「新建客户密钥」开始' : '试试其他搜索条件'}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={TABLE_HEAD_CLASS}>
                  <th className="px-5 py-3">客户</th>
                  <th className="px-3 py-3">套餐</th>
                  <th className="px-3 py-3">API 权限</th>
                  <th className="px-3 py-3">并发</th>
                  <th className="px-3 py-3">今日用量</th>
                  <th className="px-3 py-3">有效期至</th>
                  <th className="px-3 py-3">状态</th>
                  <th className="px-5 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.token_hash_full} className={TABLE_ROW_CLASS}>
                    <td className="px-5 py-3.5">
                      <div className="font-medium text-slate-800">{t.tenant_id}</div>
                      <div className="mt-0.5 font-mono text-[10px] text-slate-400">{t.token_hash_masked ?? ''}</div>
                    </td>
                    <td className="px-3 py-3.5">
                      <Badge tone={TIER_TONES[t.tier] ?? 'slate'}>{TIER_LABELS[t.tier] ?? t.tier}</Badge>
                    </td>
                    <td className="px-3 py-3.5">
                      <div className="flex max-w-52 flex-wrap gap-1">
                        {(t.scopes ?? []).map((s) => (
                          <ScopeChip key={s} scope={s} />
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-3.5 font-mono text-xs text-slate-600">{fmtNumber(t.max_concurrent)}</td>
                    <td className="px-3 py-3.5">
                      <div className="font-mono text-xs text-slate-700">
                        {t.daily_usage ?? 0} <span className="text-slate-400">/ {fmtNumber(t.daily_limit)}</span>
                      </div>
                      <div className="mt-1">
                        <ProgressBar value={t.daily_usage ?? 0} limit={t.daily_limit ?? null} />
                      </div>
                    </td>
                    <td className="px-3 py-3.5 text-xs whitespace-nowrap text-slate-600">
                      {t.expires_at ? (
                        <span className={t.expired ? 'font-medium text-rose-600' : ''}>
                          {t.expires_at.slice(0, 10)}
                          {t.expired && ' 已过期'}
                        </span>
                      ) : (
                        <span className="text-slate-400">长期有效</span>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      <ToggleSwitch
                        checked={t.enabled}
                        busy={busyHash === t.token_hash_full}
                        label={`${t.enabled ? '暂停' : '启用'} ${t.tenant_id}`}
                        onChange={() => void toggleEnabled(t)}
                      />
                    </td>
                    <td className="px-5 py-3.5 text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditForm(formFromToken(t))
                          setEditTarget(t)
                        }}
                      >
                        编辑
                      </Button>
                      <Button variant="ghost" size="sm" className="!text-rose-600 hover:!bg-rose-50" onClick={() => setDeleteTarget(t)}>
                        删除
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Create modal */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建客户密钥" width="max-w-xl">
        <TokenFields form={createForm} setForm={setCreateForm} isNew />
        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700 ring-1 ring-amber-200 ring-inset">
          密钥只在创建成功的那一刻显示一次，请提醒客户立即保存。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setCreateOpen(false)}>取消</Button>
          <Button loading={creating} onClick={() => void submitCreate()}>创建密钥</Button>
        </div>
      </Modal>

      {/* Token reveal modal — deliberately separate from create modal */}
      <Modal open={revealedToken !== null} onClose={() => setRevealedToken(null)} title="✅ 密钥已创建">
        <p className="text-sm text-slate-600">
          请立即复制并妥善保存，<strong className="text-rose-600">关闭后无法再次查看</strong>：
        </p>
        <div className="mt-3 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-lg bg-slate-900 px-3 py-2.5 font-mono text-xs break-all text-emerald-300">
            {revealedToken}
          </code>
          {revealedToken && <CopyButton text={revealedToken} label="复制密钥" />}
        </div>
        <div className="mt-5 flex justify-end">
          <Button onClick={() => setRevealedToken(null)}>我已保存</Button>
        </div>
      </Modal>

      {/* Edit modal */}
      <Modal open={editTarget !== null} onClose={() => setEditTarget(null)} title={`编辑客户 · ${editTarget?.tenant_id ?? ''}`} width="max-w-xl">
        <TokenFields form={editForm} setForm={setEditForm} />
        <p className="mt-4 text-[11px] leading-relaxed text-slate-400">
          清空某个限制字段并保存，即表示解除该限制（恢复为套餐默认）。修改权限或套餐立即生效。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setEditTarget(null)}>取消</Button>
          <Button loading={editing} onClick={() => void submitEdit()}>保存修改</Button>
        </div>
      </Modal>

      {/* Delete confirm */}
      <Modal open={deleteTarget !== null} onClose={() => setDeleteTarget(null)} title="确认删除" width="max-w-md">
        <p className="text-sm leading-relaxed text-slate-600">
          将永久删除客户 <strong className="font-mono">{deleteTarget?.tenant_id}</strong> 的 API
          密钥。该密钥会立即失效，客户的接口调用将收到 401 拒绝。此操作不可撤销。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>取消</Button>
          <Button loading={deleting} className="!bg-rose-600 hover:!bg-rose-700 disabled:!bg-rose-300" onClick={() => void submitDelete()}>
            确认删除
          </Button>
        </div>
      </Modal>
    </div>
  )
}

function TokenFields({
  form,
  setForm,
  isNew = false,
}: {
  form: TokenForm
  setForm: React.Dispatch<React.SetStateAction<TokenForm>>
  isNew?: boolean
}) {
  const update = (patch: Partial<TokenForm>) => setForm((prev) => ({ ...prev, ...patch }))
  const toggleScope = (scope: string, checked: boolean) =>
    update({
      scopes: checked
        ? [...form.scopes, scope]
        : form.scopes.filter((s) => s !== scope),
    })

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field label="客户 ID（tenant）" hint="如 acme-capital，创建后不可改">
        <TextInput value={form.tenant_id} onChange={(e) => update({ tenant_id: e.target.value })} disabled={!isNew} spellCheck={false} />
      </Field>
      <Field label="套餐档位" hint="决定默认并发与每小时请求上限">
        <SelectInput value={form.tier} onChange={(e) => update({ tier: e.target.value })}>
          {Object.entries(TIER_LABELS)
            .filter(([k]) => k !== 'internal')
            .map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
        </SelectInput>
      </Field>

      <Field label="每日请求上限" hint="留空表示不限量">
        <TextInput type="number" min={1} value={form.daily_limit} onChange={(e) => update({ daily_limit: e.target.value })} placeholder="不限" />
      </Field>
      <Field label="最大并发请求数" hint="留空使用套餐默认档位">
        <TextInput type="number" min={1} value={form.max_concurrent} onChange={(e) => update({ max_concurrent: e.target.value })} placeholder="套餐默认" />
      </Field>

      <Field label="有效期至" hint="留空表示长期有效">
        <TextInput type="date" value={form.expires_at} onChange={(e) => update({ expires_at: e.target.value })} />
      </Field>
      <Field label="附加权限（可选）" hint="逗号分隔的自定义 scope">
        <TextInput value={form.customScopes} onChange={(e) => update({ customScopes: e.target.value })} spellCheck={false} />
      </Field>

      <div className="sm:col-span-2">
        <span className="mb-1.5 block text-xs font-medium text-slate-600">API 权限范围</span>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-slate-200 px-3.5 py-3">
          {SCOPE_OPTIONS.map((scope) => (
            <Checkbox
              key={scope}
              checked={form.scopes.includes(scope)}
              onChange={(checked) => toggleScope(scope, checked)}
              label={
                <span className="flex items-center gap-1.5">
                  <ScopeChip scope={scope} />
                  <span className="text-[11px] text-slate-400">{SCOPE_HINTS[scope]}</span>
                </span>
              }
            />
          ))}
        </div>
      </div>
    </div>
  )
}
