import { useState } from 'react'
import { motion } from 'motion/react'
import { DEFAULT_API_BASE } from '../lib/api'
import { Button, ErrorBanner, Field, TextInput } from '../components/ui'

export default function Login({
  onLogin,
}: {
  onLogin: (token: string, base: string) => Promise<string | null>
}) {
  const [token, setToken] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [base, setBase] = useState(DEFAULT_API_BASE)
  const [busy, setBusy] = useState(false)
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

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden bg-slate-950 px-4 py-10">
      {/* Ambient background */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute -top-32 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-blue-600/20 blur-[120px]" />
        <div className="absolute right-[-120px] bottom-[-160px] h-[360px] w-[520px] rounded-full bg-indigo-500/10 blur-[100px]" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
        className="relative w-full max-w-md"
      >
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-600/30">
            <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7 text-white">
              <path d="M4 17l5-7 4.5 3.5L20 5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 21h16" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" opacity=".45" />
            </svg>
          </div>
          <h1 className="mt-4 text-xl font-semibold tracking-tight text-white">
            TradingDatas 数据服务
          </h1>
          <p className="mt-1.5 text-sm text-slate-400">
            使用 API 密钥登录控制台 · 管理员与客户同一入口
          </p>
        </div>

        <form
          onSubmit={submit}
          className="rounded-2xl border border-white/10 bg-white/[0.06] p-6 shadow-2xl backdrop-blur-xl"
        >
          <Field label="API 密钥">
            <TextInput
              type="password"
              autoFocus
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="粘贴你的 API 密钥"
              autoComplete="off"
              spellCheck={false}
            />
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
            className="mt-3 text-xs text-slate-400 transition-colors hover:text-slate-200"
          >
            {showAdvanced ? '− 收起高级设置' : '+ 高级设置'}
          </button>

          {error && (
            <div className="mt-4">
              <ErrorBanner message={error} />
            </div>
          )}

          <Button type="submit" loading={busy} className="mt-5 w-full !py-2.5">
            进入控制台
          </Button>

          <p className="mt-4 text-center text-[11px] leading-relaxed text-slate-500">
            密钥仅保存在你本人的浏览器中；请勿与他人共享。
            <br />
            密钥丢失请联系管理员重置。
          </p>
        </form>
      </motion.div>
    </div>
  )
}
