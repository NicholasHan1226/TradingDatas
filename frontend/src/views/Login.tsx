import { useEffect, useState } from 'react'
import { Eye, EyeOff, Info } from 'lucide-react'
import { DEFAULT_API_BASE } from '../lib/api'
import { Spinner } from '../components/ui'

const MARKETS = [
  { label: 'A 股', color: 'bg-[#43c7ff]' },
  { label: '加密资产', color: 'bg-[#8b7cff]' },
  { label: '新闻', color: 'bg-[#ff9b5a]' },
]

function MarketSignal() {
  return (
    <div className="login-market-signal relative overflow-hidden rounded-[18px] border border-white/10 bg-white/[0.045] p-5 shadow-[0_28px_80px_rgb(0_0_0/0.24)] backdrop-blur-sm sm:p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[10px] font-medium tracking-[0.14em] text-slate-500">MARKET COVERAGE</p>
          <p className="mt-1.5 text-sm font-medium text-slate-100">多市场数据，一套查询合同</p>
        </div>
        <div className="flex items-center gap-1.5" aria-hidden>
          <span className="h-1.5 w-1.5 rounded-full bg-[#43c7ff]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#8b7cff]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#ff9b5a]" />
        </div>
      </div>

      <svg viewBox="0 0 560 176" className="login-signal-chart mt-6 h-auto w-full" role="img" aria-label="A 股、加密资产与新闻数据统一接入示意图">
        <defs>
          <linearGradient id="signalFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#43c7ff" stopOpacity="0.2" />
            <stop offset="1" stopColor="#43c7ff" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="signalLine" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#43c7ff" />
            <stop offset="0.55" stopColor="#8b7cff" />
            <stop offset="1" stopColor="#ff9b5a" />
          </linearGradient>
        </defs>
        {[28, 76, 124, 172].map((y) => <line key={y} x1="0" x2="560" y1={y} y2={y} stroke="white" strokeOpacity="0.07" />)}
        {[0, 112, 224, 336, 448, 560].map((x) => <line key={x} x1={x} x2={x} y1="0" y2="176" stroke="white" strokeOpacity="0.045" />)}
        <path d="M0 151 C42 140 52 91 96 111 S158 151 196 103 S254 52 294 83 S353 126 392 75 S459 29 560 43 L560 176 L0 176 Z" fill="url(#signalFill)" />
        <path d="M0 151 C42 140 52 91 96 111 S158 151 196 103 S254 52 294 83 S353 126 392 75 S459 29 560 43" fill="none" stroke="url(#signalLine)" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="196" cy="103" r="4.5" fill="#8b7cff" stroke="#111827" strokeWidth="3" />
        <circle cx="392" cy="75" r="4.5" fill="#ff9b5a" stroke="#111827" strokeWidth="3" />
        <circle cx="560" cy="43" r="5" fill="#43c7ff" stroke="#111827" strokeWidth="3" />
      </svg>

      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-white/8 pt-4">
        {[
          ['Catalog', '发现数据'],
          ['Query', '统一查询'],
          ['Agent', '直接调用'],
        ].map(([title, detail]) => (
          <div key={title}>
            <p className="font-mono text-[10px] text-slate-500">{title}</p>
            <p className="mt-1 text-xs font-medium text-slate-200">{detail}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Login({ onLogin }: { onLogin: (token: string, base: string) => Promise<string | null> }) {
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
    <div className="min-h-full bg-[#080b12] p-0 text-[var(--td-ink)] sm:p-3 lg:p-5">
      <main className="relative mx-auto grid min-h-screen max-w-[1500px] overflow-hidden bg-white shadow-[0_32px_120px_rgb(0_0_0/0.5)] sm:min-h-[calc(100vh-24px)] sm:rounded-[22px] lg:min-h-[calc(100vh-40px)] lg:grid-cols-[minmax(520px,44%)_1fr]">
        <section className="relative flex min-h-[700px] items-center justify-center bg-[#fbfbfc] px-6 py-28 sm:px-10 lg:min-h-0 lg:px-14">
          <div className="absolute top-8 left-7 flex items-baseline gap-3 sm:left-10 lg:top-9">
            <a href="/app/" className="text-[20px] font-bold tracking-[-0.065em] text-[#111318]" aria-label="TradingDatas 首页">TradingDatas</a>
            <span className="hidden text-[10px] font-medium tracking-[0.1em] text-[var(--td-faint)] sm:inline">FINANCIAL DATA</span>
          </div>
          <div className="absolute top-8 right-7 rounded-full border border-[var(--td-line)] bg-white px-3 py-1.5 text-[10px] font-medium text-[var(--td-muted)] shadow-[var(--td-shadow-1)] sm:right-10 lg:hidden">公共金融数据服务</div>

          <div className="w-full max-w-[420px]">
            <div className="mb-9">
              <div className="mb-5 flex items-center gap-2.5 text-[11px] font-semibold tracking-[0.11em] text-[var(--td-accent)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--td-accent)] shadow-[0_0_0_4px_rgb(49_87_213/0.1)]" />
                DATA WORKSPACE
              </div>
              <h1 className="text-[36px] font-semibold leading-[1.14] tracking-[-0.058em] text-[#111318] sm:text-[40px]">连接你的<br className="sm:hidden" />数据工作台</h1>
              <p className="mt-4 max-w-sm text-[14px] leading-6 text-[var(--td-muted)]">使用访问密钥进入对应工作区。管理员默认进入管理控制台，用户进入数据门户。</p>
            </div>

            <form onSubmit={submit} noValidate>
              <div className="flex items-center justify-between">
                <label htmlFor="login-key" className="text-[13px] font-medium text-[var(--td-ink-soft)]">访问密钥</label>
                <span className="text-[10px] text-[var(--td-faint)]">Access token</span>
              </div>
              <div className="relative mt-2.5">
                <input
                  id="login-key"
                  type={showToken ? 'text' : 'password'}
                  autoFocus
                  value={token}
                  onChange={(event) => { setToken(event.target.value); if (error) setError(null) }}
                  placeholder="粘贴或输入密钥"
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  aria-describedby={error ? 'login-error' : 'login-help'}
                  aria-invalid={Boolean(error)}
                  className="h-14 w-full rounded-[var(--td-radius)] border border-[var(--td-line-strong)] bg-white px-4 pr-20 text-sm text-[var(--td-ink)] shadow-[0_1px_0_rgb(17_19_24/0.03)] outline-none transition-[border-color,box-shadow,background-color] duration-[var(--td-duration-fast)] placeholder:text-[var(--td-faint)] hover:border-slate-400 focus:border-[var(--td-accent)] focus:ring-4 focus:ring-blue-600/10"
                />
                <div className="absolute inset-y-0 right-2.5 flex items-center gap-1">
                  {!token ? (
                    <button type="button" onClick={pasteFromClipboard} disabled={pasteBusy} className="rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--td-muted)] hover:bg-slate-100 hover:text-[var(--td-ink)] focus-visible:outline-2 focus-visible:outline-[var(--td-accent)] disabled:opacity-50">
                      {pasteBusy ? <Spinner size={12} /> : '粘贴'}
                    </button>
                  ) : (
                    <button type="button" onClick={() => setShowToken((value) => !value)} aria-label={showToken ? '隐藏密钥' : '显示密钥'} className="flex h-9 w-9 items-center justify-center rounded-md text-[var(--td-muted)] hover:bg-slate-100 hover:text-[var(--td-ink)] focus-visible:outline-2 focus-visible:outline-[var(--td-accent)]">
                      {showToken ? <EyeOff aria-hidden size={16} /> : <Eye aria-hidden size={16} />}
                    </button>
                  )}
                </div>
              </div>

              {error && (
                <div id="login-error" role="alert" className="mt-4 flex items-start gap-2.5 rounded-[var(--td-radius-sm)] border border-rose-200 bg-rose-50 px-3.5 py-3 text-sm leading-5 text-rose-700">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" /><span>{error}</span>
                </div>
              )}

              <button type="submit" disabled={!token.trim() || busy} className="mt-5 inline-flex h-13 w-full items-center justify-center gap-2 rounded-[var(--td-radius)] border border-transparent bg-[#3157d5] text-sm font-semibold text-white shadow-[0_12px_26px_rgb(49_87_213/0.22)] transition-[transform,background-color,box-shadow] duration-[var(--td-duration-fast)] hover:-translate-y-px hover:bg-[#284cc7] hover:shadow-[0_16px_30px_rgb(49_87_213/0.28)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)] active:translate-y-0 disabled:cursor-not-allowed disabled:translate-y-0 disabled:bg-slate-300 disabled:shadow-none">
                {busy && <Spinner size={14} />}{busy ? '正在验证…' : '进入工作台'}
              </button>

              <p id="login-help" className="mt-4 flex items-center gap-2 text-[11px] leading-5 text-[var(--td-faint)]">
                <Info aria-hidden className="h-3.5 w-3.5 shrink-0" />
                密钥仅保存在当前浏览器，不会在页面中再次展示。
              </p>
            </form>

            <div className="mt-10 border-t border-[var(--td-line)] pt-5 lg:hidden">
              <p className="text-[10px] font-medium tracking-[0.1em] text-[var(--td-faint)]">AVAILABLE MARKETS</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {MARKETS.map((market) => <span key={market.label} className="inline-flex items-center gap-2 rounded-full border border-[var(--td-line)] bg-white px-3 py-1.5 text-xs font-medium text-[var(--td-ink-soft)]"><span className={`h-1.5 w-1.5 rounded-full ${market.color}`} />{market.label}</span>)}
              </div>
            </div>
          </div>

          <div className="absolute bottom-7 left-7 text-[10px] text-[var(--td-faint)] sm:left-10">© Tradingagent.cc · TradingDatas</div>
        </section>

        <aside className="login-product-panel relative hidden overflow-hidden bg-[#0c1324] px-12 py-10 text-white lg:flex lg:flex-col lg:justify-between xl:px-16 xl:py-12">
          <div aria-hidden className="absolute inset-0 [background-image:radial-gradient(circle_at_88%_12%,rgb(67_199_255/0.15),transparent_28%),radial-gradient(circle_at_12%_92%,rgb(139_124_255/0.16),transparent_32%),linear-gradient(rgb(255_255_255/0.035)_1px,transparent_1px),linear-gradient(90deg,rgb(255_255_255/0.035)_1px,transparent_1px)] [background-size:auto,auto,48px_48px,48px_48px]" />
          <div className="relative flex items-center justify-between text-[10px] font-medium tracking-[0.11em] text-slate-500"><span>TRADINGDATAS / DATA INFRASTRUCTURE</span><span>PUBLIC FINANCIAL DATA</span></div>

          <div className="login-product-content relative mx-auto w-full max-w-[650px] py-12">
            <div className="login-market-tags mb-7 flex flex-wrap gap-2">
              {MARKETS.map((market) => <span key={market.label} className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.045] px-3 py-1.5 text-[11px] font-medium text-slate-300"><span className={`h-1.5 w-1.5 rounded-full ${market.color}`} />{market.label}</span>)}
            </div>
            <h2 className="login-product-title max-w-[620px] text-[38px] font-semibold leading-[1.15] tracking-[-0.052em] text-white xl:text-[46px]">让 Agent 用一种方式，<br />读取多市场金融数据。</h2>
            <p className="login-product-copy mt-5 max-w-[560px] text-sm leading-7 text-slate-400">统一目录、标准查询和可追溯数据状态，为 Claude、Codex、OpenClaw 与 Hermes 提供稳定的数据入口。</p>
            <div className="login-signal-wrap mt-10"><MarketSignal /></div>
          </div>

          <div className="relative flex items-center justify-between border-t border-white/8 pt-5 text-[10px] text-slate-600"><span>Built for agents</span><span>Catalog · Query · Lineage</span></div>
        </aside>
      </main>
    </div>
  )
}
