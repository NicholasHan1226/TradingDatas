import { useEffect, useState } from 'react'
import { DEFAULT_API_BASE } from '../lib/api'
import { Spinner } from '../components/ui'

const PIPELINE = [
  ['01', '统一目录', 'Catalog 定义数据合同'],
  ['02', '可追溯采集', 'Facts 与 receipts 同步沉淀'],
  ['03', '稳定查询', '面向研究与 Agent 的只读接口'],
]

export default function Login({
  onLogin,
}: {
  onLogin: (token: string, base: string) => Promise<string | null>
}) {
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pasteBusy, setPasteBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!showToken || !token) return
    const timer = window.setTimeout(() => setShowToken(false), 1400)
    return () => window.clearTimeout(timer)
  }, [showToken, token])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!token.trim() || busy) return
    setBusy(true)
    setError(null)
    const nextError = await onLogin(token.trim(), DEFAULT_API_BASE)
    if (nextError) setError(nextError)
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
      }
    } catch {
      // Clipboard access can be denied; normal keyboard paste remains available.
    } finally {
      setPasteBusy(false)
    }
  }

  return (
    <div className="min-h-full bg-[#090d18] p-0 text-[var(--td-ink)] sm:p-4">
      <main className="relative mx-auto grid min-h-screen max-w-[1400px] overflow-hidden bg-white shadow-[0_32px_100px_rgb(0_0_0/0.42)] sm:min-h-[calc(100vh-32px)] sm:rounded-[24px] lg:grid-cols-[minmax(520px,46%)_1fr]">
        <section className="relative flex items-center justify-center px-6 py-24 sm:px-10 lg:px-14">
          <a href="/app/" className="absolute top-8 left-8 text-[19px] font-bold tracking-[-0.06em] text-[#111318] lg:left-10" aria-label="TradingDatas 首页">TradingDatas</a>
          <div className="absolute top-9 right-8 text-[11px] text-[var(--td-faint)] lg:hidden">Financial data service</div>
          <div className="w-full max-w-[400px]">
            <div className="mb-8">
              <div className="mb-5 flex items-center gap-2 text-[11px] font-medium tracking-[0.08em] text-[var(--td-accent)]"><span className="h-px w-6 bg-[var(--td-accent)]" />SECURE WORKSPACE</div>
              <h1 className="text-[34px] font-semibold tracking-[-0.055em] text-[#111318]">进入数据工作台</h1>
              <p className="mt-3 text-sm leading-6 text-[var(--td-muted)]">使用访问密钥连接你的管理控制台或数据门户。</p>
            </div>

            <div>
              <form onSubmit={submit} noValidate>
                <label htmlFor="login-key" className="block text-[13px] font-medium text-[var(--td-ink-soft)]">访问密钥</label>
                <div className="relative mt-2">
                  <input
                    id="login-key"
                    type={showToken ? 'text' : 'password'}
                    autoFocus
                    value={token}
                    onChange={(event) => {
                      setToken(event.target.value)
                      if (error) setError(null)
                    }}
                    placeholder="粘贴或输入密钥"
                    autoComplete="off"
                    autoCapitalize="off"
                    spellCheck={false}
                    aria-describedby={error ? 'login-error' : 'login-help'}
                    aria-invalid={Boolean(error)}
                    className="h-12 w-full rounded-lg border border-[var(--td-line-strong)] bg-[#f8f9fb] px-4 pr-20 text-sm text-[var(--td-ink)] outline-none transition-[border-color,box-shadow,background-color] duration-[var(--td-duration-fast)] placeholder:text-[var(--td-faint)] hover:border-slate-400 focus:border-[var(--td-accent)] focus:bg-white focus:ring-4 focus:ring-blue-600/10"
                  />
                  <div className="absolute inset-y-0 right-2 flex items-center gap-1">
                    {!token ? (
                      <button type="button" onClick={pasteFromClipboard} disabled={pasteBusy} className="rounded px-2 py-1 text-xs font-medium text-[var(--td-muted)] hover:bg-slate-100 hover:text-[var(--td-ink)] focus-visible:outline-2 focus-visible:outline-[var(--td-accent)] disabled:opacity-50">
                        {pasteBusy ? <Spinner size={12} /> : '粘贴'}
                      </button>
                    ) : (
                      <button type="button" onClick={() => setShowToken((value) => !value)} aria-label={showToken ? '隐藏密钥' : '显示密钥'} className="flex h-8 w-8 items-center justify-center rounded text-[var(--td-muted)] hover:bg-slate-100 hover:text-[var(--td-ink)] focus-visible:outline-2 focus-visible:outline-[var(--td-accent)]">
                        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4" aria-hidden>
                          {showToken ? (
                            <><path d="m3 3 14 14" /><path d="M8.2 5.2A8.8 8.8 0 0 1 10 5c4 0 7 3.5 7 5 0 .7-.7 1.8-1.8 2.8M12.7 14.6A9 9 0 0 1 10 15c-4 0-7-3.5-7-5 0-.8.8-2 2.1-3" /></>
                          ) : (
                            <><path d="M3 10c0-1.5 3-5 7-5s7 3.5 7 5-3 5-7 5-7-3.5-7-5Z" /><circle cx="10" cy="10" r="2.2" /></>
                          )}
                        </svg>
                      </button>
                    )}
                  </div>
                </div>

                {error && (
                  <div id="login-error" role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-3 text-sm leading-5 text-rose-700">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />
                    <span>{error}</span>
                  </div>
                )}

                <button type="submit" disabled={!token.trim() || busy} className="mt-5 inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg border border-transparent bg-[#254edd] text-sm font-medium text-white shadow-[0_10px_24px_rgb(37_78_221/0.22)] transition-[background-color,box-shadow] duration-[var(--td-duration-fast)] hover:bg-[#1f43c5] hover:shadow-[0_12px_28px_rgb(37_78_221/0.28)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none">
                  {busy && <Spinner size={14} />}
                  {busy ? '正在验证…' : '继续'}
                </button>

                <p id="login-help" className="mt-5 border-t border-[var(--td-line)] pt-4 text-[11px] leading-5 text-[var(--td-faint)]">密钥只保存在当前浏览器，不会在页面中再次展示。</p>
              </form>
            </div>
          </div>
          <div className="absolute bottom-7 left-8 text-[10px] text-[var(--td-faint)] lg:left-10">© Tradingagent.cc · TradingDatas</div>
        </section>

        <aside className="relative hidden overflow-hidden bg-[#1536b8] px-12 py-12 text-white lg:flex lg:flex-col lg:justify-between">
          <div aria-hidden className="absolute inset-0 [background-image:radial-gradient(circle_at_82%_18%,rgb(61_225_255/0.38),transparent_28%),radial-gradient(circle_at_28%_90%,rgb(123_91_255/0.42),transparent_34%),linear-gradient(rgb(255_255_255/0.055)_1px,transparent_1px),linear-gradient(90deg,rgb(255_255_255/0.055)_1px,transparent_1px)] [background-size:auto,auto,40px_40px,40px_40px]" />
          <div className="relative flex items-center justify-between text-[11px] text-slate-400">
            <span className="text-blue-100">TRADINGDATAS / FINANCIAL DATA</span>
          </div>

          <div className="relative max-w-[540px]">
            <p className="text-sm font-medium text-cyan-200">Research infrastructure</p>
            <h2 className="mt-4 text-[36px] font-semibold leading-[1.18] tracking-[-0.045em]">把分散的市场数据，<br />整理成可信的研究资产。</h2>
            <p className="mt-5 max-w-md text-sm leading-6 text-blue-100/75">面向研究者与智能体的公共金融数据服务，从数据合同、采集回执到统一查询，每一层状态都可观察、可追溯。</p>

            <div className="mt-10 overflow-hidden rounded-2xl border border-white/15 bg-[#0b1d72]/35 shadow-[0_24px_60px_rgb(4_12_58/0.22)] backdrop-blur-sm">
              {PIPELINE.map(([step, title, detail], index) => (
                <div key={step} className={`grid grid-cols-[40px_124px_1fr] items-center gap-3 px-4 py-4 ${index ? 'border-t border-white/10' : ''}`}>
                  <span className={`font-mono text-[11px] ${index === 0 ? 'text-cyan-200' : index === 1 ? 'text-violet-200' : 'text-amber-200'}`}>{step}</span>
                  <span className="text-sm font-medium text-white">{title}</span>
                  <span className="text-xs text-blue-100/65">{detail}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="relative flex items-center justify-between text-[11px] text-blue-100/45">
            <span>Bearer access · role aware</span>
            <span>Catalog · Query · Lineage</span>
          </div>
        </aside>
      </main>
    </div>
  )
}
