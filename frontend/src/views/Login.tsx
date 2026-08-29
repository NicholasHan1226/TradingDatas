import { useEffect, useState } from 'react'
import { ArrowRight, Eye, EyeOff, Info } from 'lucide-react'
import { DEFAULT_API_BASE } from '../lib/api'
import { Spinner } from '../components/ui'
import brandMark from '../assets/tradingdata-mark.png'

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
      // Keyboard paste remains available when clipboard permission is denied.
    } finally {
      setPasteBusy(false)
    }
  }

  return (
    <div className="min-h-full bg-[var(--td-canvas)] px-3 py-3 text-[var(--td-ink)] sm:px-5 sm:py-4">
      <header className="mx-auto flex min-h-16 max-w-[1440px] items-center justify-between rounded-full border border-[var(--td-line)] bg-[rgb(255_254_250/0.88)] px-5 shadow-[0_14px_42px_rgb(29_43_39/0.10)] backdrop-blur-xl sm:px-7">
        <a href="https://tradingdatas.com/" className="flex items-center gap-2.5" aria-label="返回 TradingDatas 首页">
          <img src={brandMark} alt="" className="h-8 w-8" />
          <span className="text-[23px] font-medium tracking-[-0.045em]">TradingDatas</span>
        </a>
        <a href="https://tradingdatas.com/data" className="hidden text-[12px] text-[var(--td-muted)] transition-colors hover:text-[var(--td-ink)] sm:inline">浏览公开数据状态 →</a>
      </header>

      <main className="mx-auto grid min-h-[calc(100vh-104px)] max-w-[1240px] items-center gap-14 py-16 lg:grid-cols-[minmax(0,1fr)_430px] lg:py-10">
        <section className="max-w-[680px]">
          <p className="font-mono text-[10px] tracking-[0.13em] text-[var(--td-accent)]">ADMIN / SECURE ACCESS</p>
          <h1 className="mt-6 text-[48px] font-semibold leading-[1.02] tracking-[-0.065em] text-[var(--td-ink)] sm:text-[66px]">只把需要处理的事，<br />留给管理员。</h1>
          <p className="mt-7 max-w-[570px] text-[16px] leading-8 text-[var(--td-muted)]">用户账户已经统一到官网 Account；这里仅用于管理客户权限、运行异常、平台用量和认证数据核验。</p>
          <dl className="mt-10 grid max-w-[620px] border-y border-[var(--td-line)] sm:grid-cols-3 sm:divide-x sm:divide-[var(--td-line)]">
            {[
              ['01', '客户', '账户、套餐与授权'],
              ['02', '异常', '需要处理的运行问题'],
              ['03', '核验', '认证目录与样本回读'],
            ].map(([number, title, detail]) => (
              <div key={number} className="py-5 sm:px-5 sm:first:pl-0">
                <dt className="font-mono text-[9px] text-[var(--td-accent)]">{number}</dt>
                <dd className="mt-2 text-[13px] font-semibold">{title}</dd>
                <p className="mt-1 text-[11px] leading-5 text-[var(--td-muted)]">{detail}</p>
              </div>
            ))}
          </dl>
        </section>

        <section className="rounded-[22px] border border-[var(--td-line)] bg-[rgb(255_254_250/0.82)] p-6 shadow-[0_24px_70px_rgb(29_43_39/0.10)] sm:p-8" aria-labelledby="login-heading">
          <p className="font-mono text-[9px] tracking-[0.12em] text-[var(--td-faint)]">SECURE ACCESS</p>
          <h2 id="login-heading" className="mt-4 text-[27px] font-semibold tracking-[-0.045em]">进入管理员控制台</h2>
          <p className="mt-2 text-[12px] leading-6 text-[var(--td-muted)]">仅接受带 admin scope 或 internal tier 的访问密钥。</p>
          <form onSubmit={submit} noValidate className="mt-8">
            <div className="flex items-center justify-between">
              <label htmlFor="login-key" className="text-[12px] font-medium">访问密钥</label>
              <span className="font-mono text-[9px] text-[var(--td-faint)]">ACCESS TOKEN</span>
            </div>
            <div className="relative mt-2.5">
              <input id="login-key" type={showToken ? 'text' : 'password'} autoFocus value={token} onChange={(event) => { setToken(event.target.value); if (error) setError(null) }} placeholder="粘贴或输入密钥" autoComplete="off" autoCapitalize="off" spellCheck={false} aria-describedby={error ? 'login-error' : 'login-help'} aria-invalid={Boolean(error)} className="h-14 w-full rounded-[10px] border border-[var(--td-line-strong)] bg-white px-4 pr-20 text-sm outline-none transition-[border-color,box-shadow] placeholder:text-[var(--td-faint)] focus:border-[var(--td-accent)] focus:ring-4 focus:ring-blue-600/10" />
              <div className="absolute inset-y-0 right-2.5 flex items-center">
                {!token ? <button type="button" onClick={pasteFromClipboard} disabled={pasteBusy} className="rounded-full px-3 py-1.5 text-[11px] text-[var(--td-muted)] hover:bg-[var(--td-surface-subtle)]">{pasteBusy ? <Spinner size={12} /> : '粘贴'}</button> : <button type="button" onClick={() => setShowToken((value) => !value)} aria-label={showToken ? '隐藏密钥' : '显示密钥'} className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--td-muted)] hover:bg-[var(--td-surface-subtle)]">{showToken ? <EyeOff aria-hidden size={16} /> : <Eye aria-hidden size={16} />}</button>}
              </div>
            </div>
            {error && <div id="login-error" role="alert" className="mt-4 rounded-[10px] border border-rose-200 bg-rose-50 px-3.5 py-3 text-[12px] leading-5 text-rose-700">{error}</div>}
            <button type="submit" disabled={!token.trim() || busy} className="mt-5 inline-flex h-13 w-full items-center justify-center gap-2 rounded-[10px] bg-[var(--td-accent)] text-[13px] font-semibold text-white shadow-[0_12px_28px_rgb(49_87_213/0.20)] transition-colors hover:bg-[var(--td-accent-strong)] disabled:cursor-not-allowed disabled:bg-[#b8bfca] disabled:shadow-none">{busy && <Spinner size={14} />}{busy ? '正在验证…' : '进入控制台'}{!busy && <ArrowRight aria-hidden size={15} />}</button>
            <p id="login-help" className="mt-4 flex items-start gap-2 text-[10px] leading-5 text-[var(--td-faint)]"><Info aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />密钥仅保存在当前浏览器，不会显示在页面内容中。</p>
          </form>
        </section>
      </main>
    </div>
  )
}
