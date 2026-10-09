import { useCallback, useEffect, useState } from 'react'
import { THEMES } from './theme'

/* ───────── Theme switcher (3 swatches, top right) ───────── */
export function ThemeSwitcher({ themeId, onChange }) {
  return (
    <div className="theme-sw glass" role="radiogroup" aria-label="Colour theme">
      {Object.entries(THEMES).map(([id, t]) => (
        <button key={id} role="radio" aria-checked={themeId === id} title={t.label}
          className={themeId === id ? 'on' : ''} onClick={() => onChange(id)}
          style={{ background: `linear-gradient(135deg, ${t.swatch[0]}, ${t.swatch[1]})` }} />
      ))}
    </div>
  )
}

const ago = (ts) => {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`
}

async function call(url, method = 'GET') {
  const r = await fetch(url, { method })
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
  return r.json()
}

/* ───────── Monitor tab: live health + alert timeline ───────── */
function Monitor({ health, alerts, onAsk, busy }) {
  if (!health) return <p className="cp-empty">Waiting for the first health check…</p>
  return (
    <>
      <div className={`cp-status ${health.healthy ? 'good' : 'bad'}`}>
        {health.healthy ? 'All routers, adjacencies and sessions are healthy.' : `${health.issues.length} problem${health.issues.length > 1 ? 's' : ''} detected`}
      </div>
      <div className="cp-routers">
        {Object.entries(health.routers).map(([r, st]) => <span key={r} className={`cp-r ${st}`}>{r}<i /></span>)}
      </div>
      {health.issues.length > 0 && (
        <>
          <ul className="cp-list">{health.issues.map((i) => <li key={i} className="bad">{i}</li>)}</ul>
          <button className="cp-btn primary" disabled={busy} onClick={() => onAsk('What is wrong with the network right now? Explain the root cause of each problem.')}>
            Ask the agent to investigate
          </button>
        </>
      )}
      <h5>Recent events</h5>
      {alerts.length === 0 ? <p className="cp-empty">No changes since you opened the page.</p> : (
        <ul className="cp-list">{alerts.map((a, i) => <li key={i} className={a.kind}><time>{ago(a.ts)}</time>{a.kind === 'good' ? 'Recovered: ' : 'New: '}{a.text}</li>)}</ul>
      )}
    </>
  )
}

/* ───────── Break tab: failure injection ───────── */
function Break({ apiUrl, onAsk, busy }) {
  const [faults, setFaults] = useState([])
  const [msg, setMsg] = useState('')
  const [working, setWorking] = useState(false)
  const load = useCallback(() => call(`${apiUrl}/api/faults`).then(setFaults).catch((e) => setMsg(`Could not load faults: ${e.message}`)), [apiUrl])
  useEffect(() => { load() }, [load])

  const run = async (path, ok) => {
    setWorking(true); setMsg('')
    try { await call(`${apiUrl}${path}`, 'POST'); setMsg(ok); await load() } catch (e) { setMsg(`Failed: ${e.message}`) }
    setWorking(false)
  }
  return (
    <>
      <p className="cp-note">Simulates the network breaking, outside the agent. The live monitor spots it, then ask the agent to find and fix it.</p>
      {faults.map((f) => (
        <div key={f.id} className={`cp-fault ${f.active ? 'active' : ''}`}>
          <div><b>{f.title}</b><span className={`cp-tag ${f.kind}`}>{f.kind}</span><p>{f.desc}</p></div>
          <button className="cp-btn" disabled={working || f.active} onClick={() => run(`/api/faults/${f.id}/inject`, `Injected: ${f.title}. The monitor should flag it within seconds.`)}>
            {f.active ? 'Active' : 'Inject'}
          </button>
        </div>
      ))}
      <div className="cp-row">
        <button className="cp-btn" disabled={working} onClick={() => run('/api/faults/reset', 'Injected faults undone. Adjacencies take about 30s to re-form.')}>Reset injected faults</button>
        <button className="cp-btn primary" disabled={busy} onClick={() => onAsk('Something just broke. Find the root cause of every problem and explain it.')}>Ask the agent</button>
      </div>
      {msg && <p className="cp-msg">{msg}</p>}
    </>
  )
}

/* ───────── History tab: audit timeline ───────── */
const OUTCOME = { applied: 'good', answer: 'info', rejected: 'info', no_change: 'info', blocked: 'bad', rolled_back: 'bad' }
function History({ apiUrl }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(() => call(`${apiUrl}/api/audit?limit=40`).then(setRows).catch((e) => setErr(e.message)), [apiUrl])
  useEffect(() => { load() }, [load])
  if (err) return <p className="cp-msg">Could not load history: {err}</p>
  if (!rows) return <p className="cp-empty">Loading…</p>
  return (
    <>
      <div className="cp-row"><span className="cp-note">Every run is recorded in the audit log.</span><button className="cp-btn" onClick={load}>Refresh</button></div>
      <ul className="cp-hist">
        {rows.map((r) => (
          <li key={r.run_id + r.ts}>
            <span className={`cp-chip ${OUTCOME[r.outcome] || 'info'}`}>{String(r.outcome).replace('_', ' ')}</span>
            <div><b>{r.intent}</b><small>{ago(r.ts * 1000)}{r.routers?.length ? ` · ${r.routers.join(', ')}` : ''}{r.twin_ok != null ? ` · twin ${r.twin_ok ? 'passed' : 'failed'}` : ''}</small></div>
          </li>
        ))}
        {rows.length === 0 && <p className="cp-empty">No runs recorded yet.</p>}
      </ul>
    </>
  )
}

export default function ControlPanel({ open, onClose, health, alerts, apiUrl, onAsk, busy }) {
  const [tab, setTab] = useState('monitor')
  if (!open) return null
  return (
    <aside className="cpanel glass" aria-label="Lab control">
      <header>
        <b>Lab control</b>
        <button className="cp-x" onClick={onClose} aria-label="Close">✕</button>
      </header>
      <nav>
        {[['monitor', 'Monitor'], ['break', 'Break'], ['history', 'History']].map(([id, label]) => (
          <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>
      <div className="cp-body">
        {tab === 'monitor' && <Monitor {...{ health, alerts, onAsk, busy }} />}
        {tab === 'break' && <Break {...{ apiUrl, onAsk, busy }} />}
        {tab === 'history' && <History apiUrl={apiUrl} />}
      </div>
    </aside>
  )
}
