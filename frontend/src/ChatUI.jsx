import { useEffect, useRef } from 'react'
import GateDetails from './GateDetails'

export const SUGGESTIONS = [
  'Show OSPF neighbors on r1',
  'Why can r5 not reach r6?',
  'Set OSPF cost on r1 eth1 to 100',
  'policy: test blocking',
]

const clock = (ts) => (ts ? new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '')

/* ───────── Composer (shared by landing + chat) ───────── */
function Composer({ intent, setIntent, onSubmit, phase, connected, autoFocus }) {
  const ref = useRef(null)
  useEffect(() => { if (autoFocus && phase === 'idle') ref.current?.focus() }, [autoFocus, phase])
  const placeholder = !connected
    ? 'Connecting to backend…'
    : phase === 'idle' ? 'Ask a question or tell the network what to do…'
    : phase === 'awaiting' ? 'Waiting for your approval…'
    : 'Agent is working…'
  return (
    <form className="composer2" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
      <input
        ref={ref}
        value={intent}
        onChange={(e) => setIntent(e.target.value)}
        disabled={phase !== 'idle' || !connected}
        placeholder={placeholder}
      />
      <button disabled={phase !== 'idle' || !intent.trim() || !connected}>Ask</button>
    </form>
  )
}

/* ───────── Landing ───────── */
export function LandingHero({ intent, setIntent, onSubmit, phase, connected }) {
  return (
    <div className="landing">
      <div className="landing-card">
        <h2>NetOps Copilot</h2>
        <p>An AI assistant for your FRR lab. Ask anything about the network. Nothing changes without your OK.</p>
        <Composer {...{ intent, setIntent, onSubmit, phase, connected }} autoFocus />
        <div className="chips2">
          {SUGGESTIONS.slice(0, 3).map((s) => (
            <button key={s} disabled={!connected || phase !== 'idle'} onClick={() => onSubmit(s)}>{s}</button>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ───────── Message pieces ───────── */
function RunCard({ steps, pipeline }) {
  const items = pipeline.filter((p) => steps[p.id])
  if (!items.length) return <div className="cmsg run"><div className="run-card"><span className="rchip running">Starting…</span></div></div>
  return (
    <div className="cmsg run">
      <div className="run-card">
        {items.map((p) => (
          <span key={p.id} className={`rchip ${steps[p.id]}`}>
            {p.gate ? '◆ ' : ''}{p.label}
          </span>
        ))}
      </div>
    </div>
  )
}

const APPROVAL_LABEL = {
  pending: 'Waiting for your decision',
  approved: 'Approved',
  rejected: 'Rejected',
  expired: 'Expired (session was reloaded). Ask again to retry.',
}

function ApprovalCard({ m }) {
  return (
    <div className={`cmsg approval ${m.state}`}>
      <div className="acard">
        <div className="ahead">
          <b>Change proposal</b>
          <span className={`abadge ${m.state}`}>
            {APPROVAL_LABEL[m.state]}{m.decidedAt ? ` · ${clock(m.decidedAt)}` : ''}
          </span>
        </div>
        {m.plan?.rationale && <p>{m.plan.rationale}</p>}
        <GateDetails review={m.review} policy={m.policy} twin={m.twin} />
        <details open={m.state === 'pending'}>
          <summary>Config diff ({Object.keys(m.diffs || {}).length} router{Object.keys(m.diffs || {}).length === 1 ? '' : 's'})</summary>
          <div className="cdiff">
            {Object.entries(m.diffs || {}).map(([router, text]) => (
              <div key={router}>
                <div className="dh">--- {router} ---</div>
                {String(text).split('\n').map((l, i) => (
                  <div key={i} className={l.startsWith('+') ? 'dadd' : l.startsWith('-') ? 'ddel' : ''}>{l || ' '}</div>
                ))}
              </div>
            ))}
          </div>
        </details>
        {m.plan?.risk && <p className="arisk">Risk: {m.plan.risk}</p>}
      </div>
    </div>
  )
}

function Message({ m, pipeline }) {
  if (m.role === 'run') return <RunCard steps={m.steps || {}} pipeline={pipeline} />
  if (m.role === 'approval') return <ApprovalCard m={m} />
  if (m.role === 'system') return <div className="cmsg system">{m.text}</div>
  return (
    <div className={`cmsg ${m.role} ${m.tone || ''}`}>
      <div className="bubble">{m.text}</div>
      <time>{clock(m.ts)}</time>
    </div>
  )
}

/* ───────── Centered chat panel ───────── */
export function ChatPanel({ msgs, pipeline, phase, connected, intent, setIntent, onSubmit, onMinimize, onNewSession }) {
  const feed = useRef(null)
  useEffect(() => { feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: 'smooth' }) }, [msgs, phase])

  return (
    <>
      <div className="chat-backdrop" onClick={onMinimize} />
      <section className="chat-panel" role="dialog" aria-label="Agent chat">
        <header>
          <div>
            <b>Agent chat</b>
            <span className="sess">{connected ? 'Session saved for this tab' : 'Reconnecting…'}</span>
          </div>
          <div className="hbtns">
            <button onClick={() => { if (window.confirm('Start a new session? This clears the chat and the agent\'s memory of it.')) onNewSession() }}>New session</button>
            <button onClick={onMinimize} aria-label="Minimize chat" title="Minimize (Esc)">Minimize</button>
          </div>
        </header>

        <div className="cfeed" ref={feed}>
          {msgs.length === 0 && (
            <div className="cempty">
              <p>Ask about the network or request a change.</p>
              <div className="chips2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} disabled={!connected || phase !== 'idle'} onClick={() => onSubmit(s)}>{s}</button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m) => <Message key={m.id} m={m} pipeline={pipeline} />)}
          {phase === 'running' && <div className="typing"><i /><i /><i /><span>Agent is working</span></div>}
        </div>

        <footer>
          <Composer {...{ intent, setIntent, onSubmit, phase, connected }} autoFocus />
        </footer>
      </section>
    </>
  )
}

/* ───────── Minimized pill ───────── */
export function ChatPill({ onClick, unread, phase, count }) {
  const label = phase === 'awaiting' ? 'Approval needed' : phase === 'running' ? 'Agent working…' : 'Open chat'
  return (
    <button className={`chat-pill ${phase === 'awaiting' ? 'urgent' : ''}`} onClick={onClick}>
      {phase === 'running' && <span className="pdot run" />}
      {phase === 'awaiting' && <span className="pdot warn" />}
      {label}
      {count > 0 && <span className="pcount">{count}</span>}
      {unread > 0 && <span className="punread">{unread} new</span>}
    </button>
  )
}