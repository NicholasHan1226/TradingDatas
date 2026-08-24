import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { DEFAULT_API_BASE } from '../lib/api'
import { Spinner } from '../components/ui'

// Fine grain noise, inlined as SVG turbulence — gives the brand panel a matte,
// printed-paper texture instead of flat digital black.
const NOISE_TEXTURE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E\")"

// A hand-drawn market-data shape for the living chart on the brand panel.
const SPARK_PATH =
  'M0 122 C 28 112, 44 92, 68 96 S 108 128, 138 116 S 178 62, 208 74 S 248 104, 278 88 S 318 42, 348 54 S 388 84, 418 62 S 476 26, 560 36'
const SPARK_AREA = `${SPARK_PATH} L 560 160 L 0 160 Z`

const FEATURES = [
  ['统一数据入口', '多源市场数据，集中查询'],
  ['研究可复用', '让数据沉淀为可查询资产'],
  ['Agent 就绪', '接入示例一键复制'],
]

export default function Login({
  onLogin,
}: {
  onLogin: (token: string, base: string) => Promise<string | null>
}) {
  const reducedMotion = useReducedMotion()
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [base, setBase] = useState(DEFAULT_API_BASE)
  const [busy, setBusy] = useState(false)
  const [pasteBusy, setPasteBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Keep the temporary reveal honest even if the component unmounts mid-flash.
  useEffect(() => {
    if (!showToken || !token) return
    const t = setTimeout(() => setShowToken(false), 1400)
    return () => clearTimeout(t)
  }, [showToken, token])

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
      }
    } catch {
      // Clipboard permission denied / unavailable — user can still paste manually.
    }
    setPasteBusy(false)
  }

  // The product mark is deliberately typographic: compact, neutral and
  // recognisable without borrowing a third-party icon language.
  const brandMark = (
    <span className="font-sans text-[18px] font-bold tracking-[-0.06em] text-white">
      TradingDatas
    </span>
  )

  return (
    <div className="flex min-h-full bg-white dark:bg-slate-950">
      {/* Brand panel (desktop only) */}
      <aside className="relative hidden w-[46%] max-w-xl flex-col justify-between overflow-hidden bg-slate-950 p-10 xl:p-12 lg:flex">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          {/* Aurora blobs */}
          <div className="absolute -top-44 -left-28 h-[500px] w-[540px] rounded-full bg-blue-600/20 blur-[140px]" />
          <div className="absolute -bottom-44 -right-32 h-[440px] w-[540px] rounded-full bg-cyan-500/12 blur-[130px]" />
          {/* Hairline grid */}
          <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(148,163,184,.05)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,.05)_1px,transparent_1px)] [background-size:32px_32px]" />
          {/* Matte noise */}
          <div className="absolute inset-0 opacity-[0.16] mix-blend-overlay" style={{ backgroundImage: NOISE_TEXTURE }} />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="relative"
        >
          {brandMark}
          <div className="mt-1.5 text-[10px] font-medium tracking-[0.16em] text-slate-500">RESEARCH DATA INFRASTRUCTURE</div>
        </motion.div>

        <div className="relative">
          {/* Living market-data line */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.15 }}
            className="mb-8"
            aria-hidden
          >
            <svg viewBox="0 0 560 160" className="w-full" fill="none">
              <defs>
                <linearGradient id="ld-area" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity=".22" />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
                </linearGradient>
                <linearGradient id="ld-line" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#60a5fa" />
                  <stop offset="100%" stopColor="#22d3ee" />
                </linearGradient>
              </defs>
              {[40, 80, 120].map((y) => (
                <line key={y} x1="0" x2="560" y1={y} y2={y} stroke="rgba(148,163,184,.09)" strokeDasharray="2 6" />
              ))}
              <motion.path
                d={SPARK_AREA}
                fill="url(#ld-area)"
                initial={reducedMotion ? undefined : { opacity: 0 }}
                animate={reducedMotion ? undefined : { opacity: 1 }}
                transition={{ duration: 1, delay: 0.9 }}
              />
              <motion.path
                d={SPARK_PATH}
                stroke="url(#ld-line)"
                strokeWidth="2"
                strokeLinecap="round"
                initial={reducedMotion ? false : { pathLength: 0 }}
                animate={reducedMotion ? false : { pathLength: 1 }}
                transition={{ duration: 1.4, delay: 0.35, ease: 'easeInOut' }}
              />
              {!reducedMotion && (
                <motion.circle
                  r="3.5"
                  fill="#22d3ee"
                  animate={{ cx: [418, 486, 554], cy: [62, 28, 36], opacity: [0, 1, 1] }}
                  transition={{ duration: 1.4, delay: 0.35, ease: 'easeInOut' }}
                />
              )}
            </svg>
          </motion.div>

          <motion.h2
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="text-[28px] font-semibold leading-[1.3] tracking-tight text-white"
          >
            把市场数据，
            <br />
            <span className="bg-gradient-to-r from-slate-200 to-slate-500 bg-clip-text text-transparent">
              沉淀为研究资产。
            </span>
          </motion.h2>

          <ul className="mt-8 space-y-0">
            {FEATURES.map(([title, sub], i) => (
              <motion.li
                key={title}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.55 + i * 0.1, ease: [0.22, 1, 0.36, 1] }}
                className="flex items-baseline justify-between gap-4 border-t border-white/[0.07] py-3"
              >
                <span className="shrink-0 text-sm font-medium tabular-nums text-white">{title}</span>
                <span className="truncate text-xs text-slate-500">{sub}</span>
              </motion.li>
            ))}
          </ul>
        </div>

        <p className="relative text-[11px] text-slate-600">© Tradingagent.cc · TradingDatas</p>
      </aside>

      {/* Form panel */}
      <main className="relative flex min-h-full w-full flex-col bg-[radial-gradient(circle_at_72%_44%,rgb(219_234_254_/_0.28),transparent_38%)] px-5 py-8 lg:w-[54%] lg:px-14">
        {/* Mobile-only compact brand row */}
        <div className="mb-10 lg:hidden">
          <span className="font-sans text-[15px] font-bold tracking-[-0.045em] text-slate-900 dark:text-white">
            TradingDatas
          </span>
        </div>

        <div className="flex flex-1 items-center justify-center">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
            className="w-full max-w-[416px]"
          >
            <div className="mb-4 flex items-center gap-2 text-[10px] font-semibold tracking-[0.15em] text-slate-400">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500" /> SECURE ACCESS
            </div>
            <h1 className="text-[22px] font-semibold tracking-tight text-slate-900 dark:text-white">欢迎回来</h1>
            <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">输入访问密钥继续</p>

            <form onSubmit={submit} className="mt-8">
              <label
                htmlFor="login-key"
                className="block text-[13px] font-medium text-slate-700 dark:text-slate-300"
              >
                访问密钥
              </label>
              <div className="group relative mt-2">
                <input
                  id="login-key"
                  type={showToken ? 'text' : 'password'}
                  autoFocus
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="粘贴或输入密钥"
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  className="h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 pr-[76px] text-sm text-slate-900 shadow-[0_1px_2px_rgb(15_23_42/0.04)] outline-none transition-[border-color,box-shadow] duration-[var(--td-duration-fast)] placeholder:text-slate-400 hover:border-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:placeholder:text-slate-600 dark:hover:border-slate-600 dark:focus:border-blue-500 dark:focus:ring-blue-500/15"
                />
                <div className="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-0.5">
                  {!token && (
                    <button
                      type="button"
                      onClick={pasteFromClipboard}
                      disabled={pasteBusy}
                      title="从剪贴板粘贴"
                      className="flex h-7 items-center rounded-md px-2 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    >
                      {pasteBusy ? <Spinner size={12} /> : '粘贴'}
                    </button>
                  )}
                  {!!token && (
                    <button
                      type="button"
                      onClick={() => setShowToken((v) => !v)}
                      title={showToken ? '隐藏' : '显示'}
                      aria-label={showToken ? '隐藏密钥' : '显示密钥'}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                    >
                      {showToken ? (
                        <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                          <path d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l14.5 14.5a.75.75 0 1 0 1.06-1.06l-1.86-1.86A10.3 10.3 0 0 0 19.02 10a.75.75 0 0 0-.05-.78C17.2 6.56 14 4.5 10 4.5c-1.1 0-2.14.16-3.1.46l1.2 1.2A8.9 8.9 0 0 1 10 6c3.06 0 5.66 1.53 7.35 4a9.3 9.3 0 0 1-2.29 2.4zM8.53 7.47l1.6 1.6a2.75 2.75 0 0 1-3.2-3.2z" />
                          <path d="M5.28 6.34A10.4 10.4 0 0 0 1.03 9.2a.75.75 0 0 0-.05.79C2.8 12.94 6 15.5 10 15.5q1.63 0 3.07-.44l-1.65-1.65A2.75 2.75 0 0 1 7.6 9.66z" />
                        </svg>
                      ) : (
                        <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                          <path d="M10 4.5c-4 0-7.2 2.06-8.97 4.72a.75.75 0 0 0 0 .83C2.8 12.7 6 15.5 10 15.5s7.2-2.8 8.97-5.45a.75.75 0 0 0 0-.83C17.2 6.56 14 4.5 10 4.5m0 9.25a3.75 3.75 0 1 1 0-7.5 3.75 3.75 0 0 1 0 7.5" />
                          <circle cx="10" cy="10" r="2" />
                        </svg>
                      )}
                    </button>
                  )}
                </div>
              </div>

              <AnimatePresence initial={false}>
              {showAdvanced && (
                <motion.div
                  key="advanced"
                  initial={reducedMotion ? false : { opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={reducedMotion ? { opacity: 0 } : { opacity: 0, height: 0 }}
                  transition={{ duration: 0.25 }}
                  className="overflow-hidden"
                >
                  <label htmlFor="login-base" className="mt-5 block text-[13px] font-medium text-slate-700 dark:text-slate-300">
                    服务地址
                  </label>
                  <input
                    id="login-base"
                    value={base}
                    onChange={(e) => setBase(e.target.value)}
                    spellCheck={false}
                    className="mt-2 h-10 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm text-slate-900 outline-none transition-all placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                  <p className="mt-1.5 text-xs text-slate-400 dark:text-slate-500">默认官方地址，一般无需修改</p>
                </motion.div>
              )}
              </AnimatePresence>

              <button
                type="button"
                onClick={() => setShowAdvanced((v) => !v)}
                className="mt-3 text-xs text-slate-400 transition-colors hover:text-slate-600 dark:hover:text-slate-300"
                aria-expanded={showAdvanced}
              >
                {showAdvanced ? '收起选项' : '更多选项'}
              </button>

              <AnimatePresence initial={false}>
                {error && (
                  <motion.div
                    key="err"
                    initial={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
                    transition={{ type: 'spring', stiffness: 500, damping: 32 }}
                    role="alert"
                    className="mt-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700 dark:border-rose-500/25 dark:bg-rose-500/10 dark:text-rose-300"
                  >
                    <svg className="mt-0.5 h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M18 10A8 8 0 1 1 2 10a8 8 0 0 1 16 0Zm-9-4a1 1 0 1 1 2 0v4a1 1 0 1 1-2 0V6Zm2 7a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z" clipRule="evenodd" />
                    </svg>
                    <span>{error}</span>
                  </motion.div>
                )}
              </AnimatePresence>

              <motion.button
                type="submit"
                disabled={!token.trim() || busy}
                whileTap={reducedMotion ? undefined : { scale: 0.985 }}
                className="mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-blue-600 text-sm font-medium text-white shadow-[0_8px_18px_rgb(37_99_235_/_0.18)] outline-none transition-[background-color,box-shadow,transform] duration-[var(--td-duration-fast)] hover:bg-blue-500 hover:shadow-[0_10px_24px_rgb(37_99_235_/_0.24)] focus-visible:ring-4 focus-visible:ring-blue-500/25 active:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
              >
                {busy && <Spinner size={14} />}
                {busy ? '正在验证…' : '登录'}
              </motion.button>

              <p className="mt-6 text-center text-xs leading-relaxed text-slate-400 dark:text-slate-500">
                密钥仅保存在你本人的浏览器中，丢失请联系管理员重置。
              </p>
            </form>
          </motion.div>
        </div>

        <p className="mt-8 text-center text-[11px] text-slate-300 lg:hidden dark:text-slate-600">
          © Tradingagent.cc · TradingDatas
        </p>
      </main>
    </div>
  )
}
