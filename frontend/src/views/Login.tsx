import { useState } from 'react'
import { motion } from 'motion/react'
import { DEFAULT_API_BASE } from '../lib/api'
import { Button, ErrorBanner, Field, Spinner, TextInput } from '../components/ui'

const ROLE_HINTS = [
  { label: '客户密钥', desc: '进入「我的套餐」：权益、用量与接入指南' },
  { label: '管理员密钥', desc: '进入管理控制台：账号、用量与采集状态' },
]

export default function Login({
  onLogin,
}: {
  onLogin: (token: string, base: string) => Promise<string | null>
}) {
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [base, setBase] = useState(DEFAULT_API_BASE)
  const [busy, setBusy] = useState(false)
  const [pasteBusy, setPasteBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token.trim() || busy) return
    setBusy(true)
    setError(null)
    const err = await onLogin(token.trim(), base.trim() || DEFAULT_API_BASE)
    if (err) setError(err)
    setBusy(false)
  }

  const pasteFromClipboard = async () => {
    if (pasteBusy) return
    setPasteBusy(true)
    try {
      const text = await navigator.clipboard.readText()
      if (text.trim()) {
        setToken(text.trim())
        setError(null)
        setShowToken(true)
        setTimeout(() => setShowToken(false), 1200)
      }
    } catch {
      // Clipboard permission denied / unavailable — user can still paste manually.
    }
    setPasteBusy(false)
  }

  const brandMark = (
    <div className="flex items-center gap-2.5">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-600/30">
        <svg viewBox="0 0 24 24" fill="none" className="h-4.5 w-4.5 text-white">
          <path d="M4 17l5-7 4.5 3.5L20 5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M4 21h16" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity=".45" />
        </svg>
      </div>
      <span className="text-base font-semibold tracking-tight">TradingDatas</span>
    </div>
  )

  return (
    <div className="flex min-h-full bg-white">
      {/* Brand panel (desktop only) */}
      <aside className="relative hidden w-[44%] max-w-xl flex-col justify-between overflow-hidden bg-slate-950 p-10 lg:flex">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute -top-40 -left-24 h-[480px] w-[520px] rounded-full bg-blue-600/25 blur-[130px]" />
          <div className="absolute bottom-[-180px] right-[-140px] h-[420px] w-[520px] rounded-full bg-indigo-500/15 blur-[110px]" />
          <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(rgba(148,163,184,.06)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,.06)_1px,transparent_1px)] [background-size:36px_36px]" />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
          className="relative text-slate-100"
        >
          {brandMark}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.08, ease: 'easeOut' }}
          className="relative"
        >
          <h2 className="text-2xl font-semibold leading-snug tracking-tight text-white">
            一个 API，
            <br />
            驱动你的交易研究。
          </h2>
          <ul className="mt-6 space-y-3.5">
            {[
              ['192 个数据集', 'A股与全球资讯，持续扩充'],
              ['用量全透明', '套餐额度与调用量随时可查'],
              ['Agent 就绪', '接入提示词与工具定义一键复制'],
            ].map(([title, sub]) => (
              <li key={title} className="flex items-start gap-3">
                <svg viewBox="0 0 20 20" fill="currentColor" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400">
                  <path fillRule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clipRule="evenodd" />
                </svg>
                <p className="text-sm leading-relaxed">
                  <span className="font-medium text-white">{title}</span>
                  <span className="ml-2 text-xs text-slate-400">{sub}</span>
                </p>
              </li>
            ))}
          </ul>
        </motion.div>

        <p className="relative text-[11px] text-slate-500">© Tradingagent.cc · TradingDatas 数据服务</p>
      </aside>

      {/* Form panel */}
      <main className="relative flex min-h-full w-full flex-col px-4 py-8 lg:w-[56%] lg:px-12">
        {/* Mobile-only compact brand row */}
        <div className="mb-8 flex items-center justify-between lg:hidden">
          <div className="[&_span]:text-slate-900 [&_span]:text-sm">{brandMark}</div>
        </div>

        <div className="flex flex-1 items-center justify-center">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
            className="w-full max-w-md"
          >
            <h1 className="text-xl font-semibold tracking-tight text-slate-900">登录</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
              使用 API 密钥登录，系统自动识别身份：
            </p>

            <ul className="mt-4 space-y-2">
              {ROLE_HINTS.map((r) => (
                <li
                  key={r.label}
                  className="flex items-start gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5"
                >
                  <span className="mt-0.5 inline-flex shrink-0 items-center rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700 ring-1 ring-inset ring-blue-200">
                    {r.label}
                  </span>
                  <span className="text-xs leading-relaxed text-slate-600">{r.desc}</span>
                </li>
              ))}
            </ul>

            <form onSubmit={submit} className="mt-6">
              <Field label="API 密钥">
                <div className="relative">
                  <TextInput
                    type={showToken ? 'text' : 'password'}
                    autoFocus
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="粘贴你的 API 密钥"
                    autoComplete="off"
                    spellCheck={false}
                    className="pr-20"
                  />
                  <div className="absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-0.5">
                    {!token && (
                      <button
                        type="button"
                        onClick={pasteFromClipboard}
                        disabled={pasteBusy}
                        title="从剪贴板粘贴"
                        className="flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50"
                      >
                        {pasteBusy ? <Spinner size={11} /> : '粘贴'}
                      </button>
                    )}
                    {!!token && (
                      <button
                        type="button"
                        onClick={() => setShowToken((v) => !v)}
                        title={showToken ? '隐藏' : '显示'}
                        aria-label={showToken ? '隐藏密钥' : '显示密钥'}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                      >
                        {showToken ? (
                          <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                            <path fillRule="evenodd" d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l14.5 14.5a.75.75 0 1 0 1.06-1.06l-1.745-1.745A10.4 10.4 0 0 0 19.03 10.5a.75.75 0 0 0 0-.71l-.003-.005-.002-.004a.75.75 0 0 0-.073-.107c-.38-.49-.93-1.05-1.62-1.59C15.72 6.86 13.37 5.5 10 5.5q-.66 0-1.273.07L3.28 2.22Zm2.31 4.46 1.55 1.55a3.25 3.25 0 0 0 4.57 4.57l1.55 1.55A8.65 8.65 0 0 1 10 15.5c-2.9 0-4.94-1.16-6.23-2.26A9.1 9.1 0 0 1 1.68 10.7a.75.75 0 0 1 0-.9 10.7 10.7 0 0 1 3.91-3.12Z" clipRule="evenodd" />
                            <path d="M10 .5C6.28.5 3.53 2.06 1.68 3.9L16.1 18.32C17.94 16.47 19.5 13.72 19.5 10A9.5 9.5 0 0 0 10 .5Z" opacity=".0" />
                          </svg>
                        ) : (
                          <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                            <path d="M10 5.5c-3.37 0-5.72 1.36-7.33 2.79A10.5 10.5 0 0 0 1.05 9.78a.75.75 0 0 0-.02.93 11 11 0 0 0 2.74 2.98C5.06 14.84 7.1 16 10 16s4.94-1.16 6.23-2.31a11 11 0 0 0 2.74-2.98.75.75 0 0 0-.02-.93 10.5 10.5 0 0 0-1.62-1.49C15.72 6.86 13.37 5.5 10 5.5Zm0 7.75a2.75 2.75 0 1 1 0-5.5 2.75 2.75 0 0 1 0 5.5Z" />
                            <path fillRule="evenodd" d="M2.22 1.216a.75.75 0 0 1 1.06.024l14.5 15a.75.75 0 1 1-1.08 1.04l-14.5-15a.75.75 0 0 1 .02-1.064Z" clipRule="evenodd" />
                          </svg>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </Field>

              {showAdvanced && (
                <div className="mt-4">
                  <Field label="API 地址" hint="默认官方地址，一般无需修改">
                    <TextInput value={base} onChange={(e) => setBase(e.target.value)} spellCheck={false} />
                  </Field>
                </div>
              )}

              <button
                type="button"
                onClick={() => setShowAdvanced((v) => !v)}
                className="mt-3 text-xs text-slate-400 transition-colors hover:text-slate-700"
              >
                {showAdvanced ? '− 收起高级设置' : '+ 高级设置'}
              </button>

              {error && (
                <div className="mt-4">
                  <ErrorBanner message={error} />
                </div>
              )}

              <Button type="submit" loading={busy} className="mt-5 w-full !py-2.5">
                登录
              </Button>

              <p className="mt-4 text-center text-[11px] leading-relaxed text-slate-400">
                密钥仅保存在你本人的浏览器中，请勿与他人共享。
                <br />
                密钥丢失请联系管理员重置。
              </p>
            </form>
          </motion.div>
        </div>

        <p className="mt-6 text-center text-[11px] text-slate-300 lg:hidden">© Tradingagent.cc · TradingDatas 数据服务</p>
      </main>
    </div>
  )
}
