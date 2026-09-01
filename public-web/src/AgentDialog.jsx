import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Copy, X } from '@phosphor-icons/react';
import contract from '../../docs/AGENT_INTEGRATIONS.md?raw';
import { AGENTS, buildAgentPrompt } from './agentPrompts.js';

export default function AgentDialog({ onClose, copy, locale }) {
  const [agent, setAgent] = useState('Codex');
  const [copyState, setCopyState] = useState('idle');
  const dialogRef = useRef(null);
  const generation = useRef(0);
  const zh = locale === 'zh';
  const prompt = useMemo(() => buildAgentPrompt(contract, {
    agent, locale, baseUrl: import.meta.env.VITE_TRADINGDATAS_API_BASE_URL || '',
  }), [agent, locale]);

  useEffect(() => {
    const previousFocus = document.activeElement;
    dialogRef.current?.focus();
    return () => { ++generation.current; if (previousFocus?.isConnected) previousFocus.focus(); };
  }, []);
  useEffect(() => { ++generation.current; setCopyState('idle'); }, [agent, locale]);

  async function copyPrompt() {
    const current = ++generation.current;
    setCopyState('pending');
    try {
      await navigator.clipboard.writeText(prompt.text);
      if (current === generation.current) setCopyState('copied');
    } catch { if (current === generation.current) setCopyState('failed'); }
  }
  function onKeyDown(event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault(); event.stopPropagation(); return;
    }
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
    if (event.key !== 'Tab') return;
    const controls = [...dialogRef.current.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]')];
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  return <div className="dialog-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <section className="agent-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-dialog-title" tabIndex="-1" ref={dialogRef} onKeyDown={onKeyDown}>
      <button className="icon-button dialog-close" type="button" onClick={onClose} aria-label={copy.close}><X size={20} /></button>
      <span className="mono-kicker">AGENT CONNECTIONS / HTTP</span>
      <h2 id="agent-dialog-title">{copy.agentTitle}</h2>
      <p>{zh ? '一份接入说明，先发现目录，再验证数据。密钥单独保存；复制不会发起请求。' : 'One setup guide: discover the catalog, then verify the data. Keep secrets separate; copying sends no requests.'}</p>
      <div className="agent-tabs" role="group" aria-label="Agent">
        {AGENTS.map(name => <button key={name} type="button" aria-pressed={agent === name} className={agent === name ? 'is-active' : ''} onClick={() => setAgent(name)}>{name}</button>)}
      </div>
      <div className="endpoint-row"><span>API · {prompt.configured ? (zh ? '已配置，待验证' : 'configured, not verified') : (zh ? '待配置' : 'not configured')}</span><code>{prompt.endpoint || (zh ? '正式地址由账户服务提供' : 'Obtain the service origin from Account')}</code></div>
      <p className="agent-readiness-note">{zh ? '这是 HTTP 工具接入说明，不代表 MCP 服务器已上线。先在 Agent 的安全设置保存 TRADINGDATA_API_KEY。' : 'These are HTTP tool instructions, not a claim of a live MCP server. Store TRADINGDATA_API_KEY in your Agent’s secure settings first.'}</p>
      <div className="prompt-block">
        <div><span>{prompt.configured ? copy.setupPrompt : (zh ? '接入草稿 · 地址待配置' : 'Setup draft · origin pending')}</span><span>{prompt.version}</span></div>
        <pre tabIndex="0" aria-label={zh ? '接入提示词' : 'Setup prompt'}>{prompt.text}</pre>
      </div>
      <div className="agent-acceptance-steps"><span>01 · Catalog</span><span>02 · Query · limit=1</span><span>03 · Receipt & limitations</span></div>
      <button className="primary-button dialog-action" type="button" onClick={copyPrompt} disabled={copyState === 'pending'}>
        {copyState === 'copied' ? <Check weight="bold" /> : <Copy weight="bold" />}
        {copyState === 'copied' ? copy.copied : copyState === 'pending' ? (zh ? '正在复制…' : 'Copying…') : prompt.configured ? copy.copyPrompt : (zh ? '复制接入草稿' : 'Copy setup draft')}
      </button>
      <p className="agent-copy-status" role="status">{copyState === 'failed' ? (zh ? '复制未成功，请手动选择上方提示词。' : 'Copy failed. Select the prompt above to copy it manually.') : copyState === 'copied' ? (zh ? '已复制。尚未执行连接或数据查询。' : 'Copied. No connection or data query has been executed.') : (zh ? '配置成功后仍需实际验证身份、字段和回执。' : 'Configuration still needs real authentication, schema and receipt verification.')}</p>
    </section>
  </div>;
}
