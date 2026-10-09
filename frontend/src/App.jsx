import { useState, useRef, useEffect, useMemo } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Html, Line, Grid, Sparkles, Stars, Float, RoundedBox, Edges } from '@react-three/drei'
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing'
import * as THREE from 'three'
import './index.css'
import './chat.css'
import './controls.css'
import { LandingHero, ChatPanel, ChatPill } from './ChatUI'
import GateDetails from './GateDetails'
import ControlPanel, { ThemeSwitcher } from './ControlPanel'
import { THEMES, ThemeContext, useTheme, loadTheme, saveTheme } from './theme'

/* ═════════ 1. DATA ═════════ */
const ROUTERS = {
  r1: { pos: [-2.5, 0, -2.5], as: 65001, lo: '1.1.1.1', role: 'Core' },
  r2: { pos: [2.5, 0, -2.5],  as: 65001, lo: '2.2.2.2', role: 'Core' },
  r3: { pos: [-2.5, 0, 2.5],  as: 65001, lo: '3.3.3.3', role: 'Core' },
  r4: { pos: [2.5, 0, 2.5],   as: 65001, lo: '4.4.4.4', role: 'Core' },
  r5: { pos: [-6.5, 0, -2.5], as: 65002, lo: '5.5.5.5', role: 'External' },
  r6: { pos: [6.5, 0, 2.5],   as: 65003, lo: '6.6.6.6', role: 'External' },
}
const LINKS = [['r1','r2','ospf','10.0.12.0/30'],['r1','r3','ospf','10.0.13.0/30'],['r2','r4','ospf','10.0.24.0/30'],['r3','r4','ospf','10.0.34.0/30'],['r1','r5','bgp','10.1.15.0/30'],['r4','r6','bgp','10.1.46.0/30']]
const routerColor = (id, T) => (ROUTERS[id].role === 'Core' ? T.core : id === 'r5' ? T.extA : T.extB)
const STATUS_TEXT = { scan: 'Scanning…', plan: 'Planning…', twin: 'Testing in twin…', apply: 'Applying change…', verify: 'Verifying…', fail: 'Problem found' }
const ZONES = [
  { label: 'YOUR NETWORK · AS 65001 · OSPF area 0', tone: 'ospf', c: [0, 0], size: [8.2, 8.2] },
  { label: 'EXTERNAL · AS 65002', tone: 'extA', c: [-6.5, -2.5], size: [2.6, 2.6] },
  { label: 'EXTERNAL · AS 65003', tone: 'extB', c: [6.5, 2.5], size: [2.6, 2.6] },
]
const FLOOR = -1.7
const PIPELINE = [
  { id: 'classify', label: 'Classify' }, { id: 'diagnose', label: 'Diagnose' }, { id: 'plan', label: 'Plan' },
  { id: 'policy', label: 'Policy', gate: true }, { id: 'review', label: 'Review', gate: true }, { id: 'twin', label: 'Twin', gate: true },
  { id: 'approve', label: 'Approve' }, { id: 'apply', label: 'Apply' }, { id: 'verify', label: 'Verify' },
]

/* ═════════ 2. 3D ═════════ */
/* The universal "router" glyph: a disc with four arrows pointing outward */
function RouterSymbol({ color, busy }) {
  const g = useRef()
  useFrame((_, dt) => { g.current.rotation.y += dt * (busy ? 1.6 : 0.4) })
  const mat = <meshBasicMaterial color={color} toneMapped={false} />
  return (
    <group ref={g}>
      <mesh><cylinderGeometry args={[0.2, 0.2, 0.07, 32]} />{mat}</mesh>
      {[0, 1, 2, 3].map((i) => (
        <group key={i} rotation-y={(i * Math.PI) / 2}>
          <mesh position={[0.42, 0, 0]} rotation-z={-Math.PI / 2}><coneGeometry args={[0.1, 0.22, 12]} />{mat}</mesh>
          <mesh position={[0.3, 0, 0]} rotation-z={-Math.PI / 2}><cylinderGeometry args={[0.025, 0.025, 0.2, 8]} />{mat}</mesh>
        </group>
      ))}
    </group>
  )
}

/* External AS: a wireframe globe (lat/long rings) = "the internet / another provider" */
function ExternalGlobe({ color, busy }) {
  const g = useRef()
  useFrame((_, dt) => { g.current.rotation.y += dt * (busy ? 1.4 : 0.35) })
  return (
    <group ref={g}>
      <mesh><sphereGeometry args={[0.36, 18, 12]} /><meshBasicMaterial color={color} wireframe transparent opacity={0.55} toneMapped={false} /></mesh>
      <mesh><sphereGeometry args={[0.2, 16, 16]} /><meshBasicMaterial color={color} transparent opacity={0.35} toneMapped={false} /></mesh>
      <mesh rotation-x={Math.PI / 2}><torusGeometry args={[0.5, 0.012, 8, 64]} /><meshBasicMaterial color={color} toneMapped={false} /></mesh>
    </group>
  )
}

function RouterNode({ id, status, health, note, selected, onSelect }) {
  const T = useTheme()
  const r = ROUTERS[id]
  const external = r.role === 'External'
  const own = routerColor(id, T)
  const unhealthy = !status && health && health !== 'ok'
  const color = T.status[status] || (unhealthy ? (health === 'down' ? T.bad : T.warn) : own)
  const busy = !!status
  const leds = useRef([]), pad = useRef(), body = useRef()
  const [hover, setHover] = useState(false)
  const PORTS = 8

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    // port LEDs: each blinks on its own phase, much faster while the agent is working on this router
    leds.current.forEach((m, i) => {
      const f = busy ? 9 : 1.6
      m.material.opacity = 0.25 + 0.75 * Math.max(0, Math.sin(t * f + i * 1.9) ** 3)
    })
    pad.current.material.opacity = selected || busy ? 0.55 + Math.sin(t * 5) * 0.25 * busy : 0.35
    body.current.scale.setScalar(hover || selected ? 1.05 : 1)
  })

  return (
    <group position={r.pos}
      onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = 'pointer' }}
      onPointerOut={() => { setHover(false); document.body.style.cursor = 'auto' }}
      onClick={(e) => { e.stopPropagation(); onSelect(id) }}>
      <Float speed={1.4} floatIntensity={0.3} rotationIntensity={0} floatingRange={[-0.05, 0.08]}>
        <group ref={body}>
          {/* chassis: a 1U network appliance with a lit front panel */}
          <RoundedBox args={[1.9, 0.38, 1.1]} radius={0.05} smoothness={4}>
            <meshStandardMaterial color={T.chassis} metalness={T.dark ? 0.85 : 0.35} roughness={0.3} />
            <Edges color={color} threshold={15} />
          </RoundedBox>
          {/* vent slats on top */}
          {[-0.3, -0.1, 0.1, 0.3].map((z) => (
            <mesh key={z} position={[-0.45, 0.195, z]}><boxGeometry args={[0.7, 0.008, 0.05]} /><meshBasicMaterial color={T.vent} /></mesh>
          ))}
          {/* power/status LED + port row on the front face */}
          <mesh position={[-0.8, 0.0, 0.555]}><circleGeometry args={[0.045, 16]} /><meshBasicMaterial color={color} toneMapped={false} /></mesh>
          {Array.from({ length: PORTS }, (_, i) => {
            const x = -0.5 + i * 0.22
            return (
              <group key={i} position={[x, -0.02, 0.555]}>
                <mesh><planeGeometry args={[0.15, 0.13]} /><meshBasicMaterial color={T.dark ? "#050810" : "#1e293b"} /></mesh>
                <mesh ref={(m) => (leds.current[i] = m)} position={[0, 0.105, 0]}>
                  <planeGeometry args={[0.07, 0.03]} /><meshBasicMaterial color={color} transparent toneMapped={false} />
                </mesh>
              </group>
            )
          })}
          {/* hologram above the box: router symbol (core) or globe (other AS) */}
          <group position={[0, 1.0, 0]}>
            {external ? <ExternalGlobe color={color} busy={busy} /> : <RouterSymbol color={color} busy={busy} />}
          </group>
        </group>
      </Float>
      {/* support pole + floor pad */}
      <mesh position={[0, FLOOR / 2, 0]}><cylinderGeometry args={[0.02, 0.02, -FLOOR, 8]} /><meshBasicMaterial color={color} transparent opacity={0.3} toneMapped={false} /></mesh>
      <mesh ref={pad} position={[0, FLOOR + 0.01, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[1.05, 1.15, 4, 1, Math.PI / 4]} /><meshBasicMaterial color={color} transparent opacity={0.4} toneMapped={false} />
      </mesh>
      <Html position={[0, -0.85, 0]} center distanceFactor={10} zIndexRange={[5, 0]}>
        <div className="node-label" style={{ borderColor: selected ? color : undefined }}>
          <b style={{ color }}>{id.toUpperCase()}</b>
          <em>{external ? 'External router' : 'Core router'}</em>
          <span className="astag" style={{ color: own, borderColor: own }}>AS {r.as}</span>
          <span className="ip">lo {r.lo}</span>
        </div>
      </Html>
      <Html position={[0, 1.9, 0]} center distanceFactor={10} zIndexRange={[6, 0]}>
        <div className={`state-badge ${busy ? (status === 'fail' ? 'bad' : 'busy') : unhealthy ? 'bad' : 'ok'}`}
          style={busy || unhealthy ? { color, borderColor: color } : undefined}>
          {busy ? STATUS_TEXT[status] : unhealthy ? (health === 'down' ? 'Unreachable' : 'Problem detected') : 'Healthy'}
        </div>
      </Html>
      {note && (
        <Html position={[0, 2.7, 0]} center distanceFactor={10} zIndexRange={[8, 0]}>
          <div className="callout" style={{ color, borderColor: color, boxShadow: `0 0 24px ${color}55` }}>{note}</div>
        </Html>
      )}
    </group>
  )
}

function Link({ a, b, kind, subnet, active, broken }) {
  const T = useTheme()
  const pa = useMemo(() => new THREE.Vector3(...ROUTERS[a].pos), [a])
  const pb = useMemo(() => new THREE.Vector3(...ROUTERS[b].pos), [b])
  const dots = useRef([]), color = broken ? T.bad : T[kind]
  useFrame(({ clock }) => dots.current.forEach((m, i) => {
    m.visible = !broken                      // a broken link carries no traffic
    m.position.lerpVectors(pa, pb, (clock.elapsedTime * (active ? 0.7 : 0.18) + i / 3) % 1)
    m.scale.setScalar(active ? 1.6 : 1)
  }))
  const pts = [pa, pb]
  return (
    <group>
      <Line points={pts} color={color} lineWidth={7} transparent opacity={broken ? 0.3 : active ? 0.3 : 0.1} toneMapped={false} />
      <Line points={pts} color={color} lineWidth={1.6} transparent opacity={0.9} toneMapped={false} dashed={kind === 'bgp' || broken} dashSize={0.25} gapSize={0.15} />
      <Html position={pa.clone().lerp(pb, 0.5).toArray()} center distanceFactor={10} zIndexRange={[4, 0]}>
        <div className="link-label" style={{ color, borderColor: color }}>
          {kind === 'bgp' ? 'eBGP' : 'OSPF'}{broken ? ' · DOWN' : ''}
          <small>{subnet}</small>
        </div>
      </Html>
      {[0, 1, 2].map((i) => (
        <mesh key={i} ref={(m) => (dots.current[i] = m)}><sphereGeometry args={[0.055, 10, 10]} /><meshBasicMaterial color={T.dot} toneMapped={false} /></mesh>
      ))}
    </group>
  )
}

function CameraRig({ focus, lift = 0 }) {
  const controls = useThree((s) => s.controls)
  const want = useMemo(() => new THREE.Vector3(), [])
  useFrame((_, dt) => {
    if (!controls) return
    want.set(...(focus ? ROUTERS[focus].pos : [0, 0, 0]))
    want.y -= lift
    controls.target.lerp(want, 1 - Math.pow(0.02, dt))
    controls.autoRotate = !focus
    controls.update()
  })
  return null
}

function Topology({ status, health, notes, selected, onSelect }) {
  const T = useTheme()
  return (
    <group>
      {ZONES.map((z) => (
        <group key={z.label} position={[z.c[0], FLOOR + 0.005, z.c[1]]}>
          <mesh rotation-x={-Math.PI / 2}><planeGeometry args={z.size} /><meshBasicMaterial color={T[z.tone]} transparent opacity={0.07} depthWrite={false} /></mesh>
          <Line points={[[-z.size[0] / 2, 0.01, -z.size[1] / 2], [z.size[0] / 2, 0.01, -z.size[1] / 2], [z.size[0] / 2, 0.01, z.size[1] / 2], [-z.size[0] / 2, 0.01, z.size[1] / 2], [-z.size[0] / 2, 0.01, -z.size[1] / 2]]}
            color={T[z.tone]} lineWidth={1.2} transparent opacity={0.45} dashed dashSize={0.3} gapSize={0.2} toneMapped={false} />
          <Html position={[0, 0, z.size[1] / 2 + 0.35]} center><div className="zone-label" style={{ color: T[z.tone] }}>{z.label}</div></Html>
        </group>
      ))}
      {LINKS.map(([a, b, k, sub]) => <Link key={a + b} a={a} b={b} kind={k} subnet={sub} active={!!status[a] && !!status[b]} broken={health?.links?.[a + '-' + b] === 'down'} />)}
      {Object.keys(ROUTERS).map((id) => (
        <RouterNode key={id} id={id} status={status[id]} health={health?.routers?.[id]} note={notes[id]} selected={selected === id} onSelect={onSelect} />
      ))}
    </group>
  )
}

function Scene({ status, health, notes, focus, selected, onSelect, lift, theme: T }) {
  return (
    <Canvas camera={{ position: [0, 7.5, 13.5], fov: 45 }} dpr={[1, 2]} onPointerMissed={() => onSelect(null)}>
      {/* r3f has its own React root, so the theme must be re-provided inside the Canvas */}
      <ThemeContext.Provider value={T}>
        <color attach="background" args={[T.bg]} />
        <fog attach="fog" args={[T.bg, 16, 40]} />
        <ambientLight intensity={T.ambient} />
        <pointLight position={[0, 6, 0]} intensity={40} color={T.light1} />
        <pointLight position={[-8, 3, 6]} intensity={25} color={T.light2} />
        {T.stars && <Stars radius={60} depth={40} count={2500} factor={3} fade speed={0.6} />}
        <Sparkles count={T.dark ? 90 : 40} scale={[20, 7, 14]} position={[0, 1, 0]} size={2.2} speed={0.35} color={T.sparkle} opacity={T.dark ? 0.6 : 0.35} />
        <Grid position={[0, FLOOR, 0]} args={[40, 40]} cellSize={1} cellThickness={0.6} cellColor={T.gridCell}
          sectionSize={5} sectionThickness={1.2} sectionColor={T.gridSection} fadeDistance={30} fadeStrength={1.6} infiniteGrid />
        <Topology status={status} health={health} notes={notes} selected={selected} onSelect={onSelect} />
        {T.bloom > 0 && (
          <EffectComposer multisampling={0}>
            <Bloom mipmapBlur intensity={T.bloom} luminanceThreshold={0.25} luminanceSmoothing={0.2} />
            <Vignette eskil={false} offset={0.2} darkness={0.85} />
          </EffectComposer>
        )}
        <OrbitControls makeDefault enableDamping dampingFactor={0.06} autoRotate autoRotateSpeed={0.35}
          minDistance={6} maxDistance={26} maxPolarAngle={Math.PI / 2.15} />
        <CameraRig focus={focus} lift={lift} />
      </ThemeContext.Provider>
    </Canvas>
  )
}


/* ═════════ 3. 2D UI ═════════ */
function PipelineStrip({ pipe }) {
  return (
    <>
      <div className="pipe glass">
        {PIPELINE.map((s) => (
          <div key={s.id} className={`step ${s.gate ? 'gate' : ''} ${pipe[s.id] || ''}`}><div className="dot" /><b>{s.label}</b></div>
        ))}
      </div>
      <div className="legend-gate">◆ = SAFETY GATE</div>
    </>
  )
}

function ApprovalModal({ approval, onDecide }) {
  return (
    <div className="scrim">
      <div className="modal glass">
        <div className="tag">Human approval required</div>
        <h3>Apply this change to the live lab?</h3>
        <GateDetails review={approval.review} policy={approval.policy} twin={approval.twin} />
        {approval.plan?.rationale && <p>{approval.plan.rationale}</p>}
        <div className="diff">
          {Object.entries(approval.diffs).map(([router, text]) => (
            <div key={router}>
              <div className="hdr">--- {router} ---</div>
              {text.split('\n').map((l, i) => <div key={i} className={l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : ''}>{l || ' '}</div>)}
            </div>
          ))}
        </div>
        {approval.plan?.risk && <p>Risk: {approval.plan.risk}</p>}
        <div className="actions">
          <button className="btn reject" onClick={() => onDecide('reject')}>Reject</button>
          <button className="btn approve" onClick={() => onDecide('approve')}>Approve &amp; apply</button>
        </div>
      </div>
    </div>
  )
}

/* ═════════ 4. FASTAPI + WEBSOCKET INTEGRATION ═════════ */
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
export const API_URL = import.meta.env.VITE_API_URL || WS_URL.replace(/^ws/, 'http').replace(/\/ws$/, '')

function useNetops(onMessage) {
  const [connected, setConnected] = useState(false)
  const ws = useRef(null)
  // Always call the latest handler (the old version captured the first render's closure)
  const handler = useRef(onMessage)
  handler.current = onMessage

  useEffect(() => {
    let timeout
    let closed = false
    const connect = () => {
      ws.current = new WebSocket(WS_URL)
      ws.current.onopen = () => setConnected(true)
      ws.current.onclose = () => {
        setConnected(false)
        if (!closed) timeout = setTimeout(connect, 3000)
      }
      ws.current.onmessage = (e) => handler.current(JSON.parse(e.data))
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timeout)
      ws.current?.close()
    }
  }, [])

  const send = (msg) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg))
  }
  return { connected, send }
}

/* ───── session persistence (sessionStorage: survives refresh, cleared when the tab closes) ───── */
const SESSION_KEY = 'netops.session.v1'
const uid = () => Math.random().toString(36).slice(2, 10)

function loadSession() {
  try {
    const s = JSON.parse(sessionStorage.getItem(SESSION_KEY))
    if (s?.threadId) {
      s.msgs = (s.msgs || []).map((m) => {
        // A pending approval can't be resumed after a reload -> mark it expired so it is never clickable
        if (m.streaming) return { ...m, streaming: false }
        if (m.role === 'approval' && m.state === 'pending') return { ...m, state: 'expired' }
        // Pipeline steps that were mid-flight when the page closed
        if (m.role === 'run') {
          const steps = Object.fromEntries(
            Object.entries(m.steps || {}).map(([k, v]) => [k, v === 'running' || v === 'wait' ? 'stopped' : v])
          )
          return { ...m, steps }
        }
        return m
      })
      return s
    }
  } catch { /* ignore corrupt storage */ }
  return { threadId: crypto.randomUUID(), bootId: null, msgs: [], view: 'landing' }
}

export default function App() {
  const initial = useRef(null)
  if (!initial.current) initial.current = loadSession()

  // ── persisted session state ──
  const [threadId, setThreadId] = useState(initial.current.threadId)
  const [bootId, setBootId] = useState(initial.current.bootId)
  const bootRef = useRef(initial.current.bootId)  // sync copy so duplicate 'hello's can't both see a stale id
  const [msgs, setMsgs] = useState(initial.current.msgs)
  const [view, setView] = useState(initial.current.view)   // 'landing' | 'chat' | 'minimized'

  // ── live (non-persisted) state ──
  const [intent, setIntent] = useState('')
  const [phase, setPhase] = useState('idle')               // idle | running | awaiting
  const [pipe, setPipe] = useState({})
  const [status, setStatus] = useState({})
  const [notes, setNotes] = useState({})
  const [focus, setFocus] = useState(null)
  const [approval, setApproval] = useState(null)
  const [selected, setSelected] = useState(null)
  const [toast, setToast] = useState(null)
  const [unread, setUnread] = useState(0)
  const [themeId, setThemeId] = useState(loadTheme)
  const [health, setHealth] = useState(null)               // live lab health pushed by the backend monitor
  const [alerts, setAlerts] = useState([])                 // recent monitor events (newest first)
  const [dismissed, setDismissed] = useState('')           // issue-set the user already acknowledged
  const [panel, setPanel] = useState(false)                // lab control panel
  const T = THEMES[themeId]

  useEffect(() => { document.documentElement.dataset.theme = themeId; saveTheme(themeId) }, [themeId])

  useEffect(() => {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({ threadId, bootId, msgs, view })) } catch { /* quota */ }
  }, [threadId, bootId, msgs, view])

  // Toast is only for when the chat is minimized (otherwise the answer is already in the chat)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.tone === 'info' ? 12000 : 7000)
    return () => clearTimeout(t)
  }, [toast])

  // Esc minimizes the chat (but never while an approval is open)
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && view === 'chat' && !approval) setView('minimized') }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [view, approval])

  // ── helpers ──
  const push = (m) => setMsgs((ms) => [...ms, { id: uid(), ts: Date.now(), ...m }])
  const updateRun = (fn) => setMsgs((ms) => {
    let idx = -1
    for (let i = ms.length - 1; i >= 0; i--) if (ms[i].role === 'run') { idx = i; break }
    if (idx < 0) return ms
    return ms.map((m, i) => (i === idx ? { ...m, steps: fn(m.steps || {}) } : m))
  })
  const updateRunTools = (fn) => setMsgs((ms) => {
    const idx = ms.findLastIndex((m) => m.role === 'run')
    return idx < 0 ? ms : ms.map((m, i) => (i === idx ? { ...m, tools: fn(m.tools || []) } : m))
  })
  const S = (id, s) => setPipe((p) => ({ ...p, [id]: s }))
  const setRouters = (ids, mode) => setStatus(Object.fromEntries(ids.map((id) => [id, mode])))
  const note = (router, text) => setNotes(router ? { [router]: text } : {})

  const finish = (tone, text, extra = {}) => {
  // If the answer was streamed token by token, finalize that bubble instead of adding a duplicate
  setMsgs((ms) => {
    const last = ms[ms.length - 1]
    if (last && last.role === 'agent' && last.streaming) return [...ms.slice(0, -1), { ...last, text, tone, streaming: false, ...extra }]
    return [...ms, { id: uid(), ts: Date.now(), role: 'agent', text, tone, ...extra }]
  })
  if (view === 'minimized') { setToast({ tone, text }); setUnread((u) => u + 1) }

    // Close out any step still marked running/waiting when the run ends
  const closeOut = (obj, to) =>
    Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, v === 'running' || v === 'wait' ? to : v]))
  updateRun((steps) => closeOut(steps, tone === 'bad' ? 'stopped' : 'done'))
  if (tone !== 'bad') setPipe((p) => closeOut(p, 'done'))

  setStatus({}); setNotes({}); setFocus(null); setPhase('idle')
}

  const handleMessage = (msg) => {
    if (msg.type === 'hello') {
      // Backend restarted -> in-memory LangGraph checkpoints are gone even though the UI still shows history
      const prev = bootRef.current
      bootRef.current = msg.boot_id
      if (prev && prev !== msg.boot_id && msgs.length > 0) {
        push({ role: 'system', text: 'The backend restarted, so the agent no longer remembers earlier messages. The history above is for reference only.' })
        setPhase('idle'); setApproval(null)
      }
      setBootId(msg.boot_id)
    }
    else if (msg.type === 'token') {
      setMsgs((ms) => {
        const last = ms[ms.length - 1]
        if (last && last.role === 'agent' && last.streaming) return [...ms.slice(0, -1), { ...last, text: last.text + msg.text }]
        return [...ms, { id: uid(), ts: Date.now(), role: 'agent', tone: 'info', streaming: true, text: msg.text }]
      })
    }
    else if (msg.type === 'health') {
      setHealth({ routers: msg.routers, links: msg.links, issues: msg.issues, healthy: msg.healthy })
      const ev = [...(msg.appeared || []).map((t) => ({ kind: 'bad', text: t })), ...(msg.cleared || []).map((t) => ({ kind: 'good', text: t }))]
      if (ev.length) setAlerts((a) => [...ev.map((e) => ({ ...e, ts: msg.ts * 1000 })), ...a].slice(0, 30))
    }
    else if (msg.type === 'tool') {
      // the agent is running a command: light up the router it targets and log the step in the run card
      if (msg.router) { setRouters([msg.router], 'scan'); note(msg.router, `${msg.tool} ${Object.values(msg.args || {}).filter((v) => v !== msg.router).join(' ')}`.trim()); setFocus(msg.router) }
      updateRunTools((tools) => [...tools, { tool: msg.tool, args: msg.args, done: false }])
    }
    else if (msg.type === 'tool_result') {
      updateRunTools((tools) => { const i = tools.findLastIndex((t) => !t.done); return tools.map((t, k) => (k === i ? { ...t, done: true, ok: msg.ok } : t)) })
    }
    else if (msg.type === 'stage') {
      S(msg.node, msg.status)
      updateRun((steps) => ({ ...steps, [msg.node]: msg.status }))
      const r = msg.routers && msg.routers.length > 0 ? msg.routers[0] : 'r1'
      setRouters(msg.routers || ['r1'], msg.mode)
      note(r, msg.detail)
      setFocus(r)
    }
    else if (msg.type === 'approval_request') {
      setApproval({ plan: msg.plan, diffs: msg.diffs, review: msg.review, policy: msg.policy, twin: msg.twin })
      S('approve', 'wait')
      updateRun((steps) => ({ ...steps, approve: 'wait' }))
      push({ role: 'approval', plan: msg.plan, diffs: msg.diffs, review: msg.review, policy: msg.policy, twin: msg.twin, state: 'pending' })
      setPhase('awaiting')
      if (view === 'minimized') setUnread((u) => u + 1)
    }
    else if (msg.type === 'final') {
      const toneMap = { applied: 'good', blocked: 'bad', rolled_back: 'bad', error: 'bad', rejected: 'info', answer: 'info' }
      finish(toneMap[msg.outcome] || 'info', msg.text, { evidence: msg.evidence, citations: msg.citations })
    }
  }

  const { connected, send } = useNetops(handleMessage)

  const submit = (text) => {
    const x = (typeof text === 'string' ? text : intent).trim()
    if (!x || phase !== 'idle' || !connected) return
    setIntent('')
    setPhase('running')
    setPipe({})
    setToast(null)
    push({ role: 'user', text: x })
    push({ role: 'run', steps: {} })
    setView('chat')
    setUnread(0)
    send({ type: 'intent', text: x, thread_id: threadId })
  }

  const handleDecision = (decision) => {
    setApproval(null)
    S('approve', 'done')
    updateRun((steps) => ({ ...steps, approve: 'done' }))
    setMsgs((ms) => ms.map((m) =>
      m.role === 'approval' && m.state === 'pending'
        ? { ...m, state: decision === 'approve' ? 'approved' : 'rejected', decidedAt: Date.now() }
        : m
    ))
    setPhase('running')
    send({ type: 'decision', value: decision, thread_id: threadId })
  }

  const newSession = () => {
    setThreadId(crypto.randomUUID())
    setMsgs([]); setApproval(null); setPhase('idle'); setPipe({}); setStatus({}); setNotes({})
    setFocus(null); setToast(null); setUnread(0); setIntent(''); setView('landing')
  }

  const openChat = () => { setView('chat'); setUnread(0) }
  const info = selected && ROUTERS[selected]

  return (
  <div className="stage">
    <Scene status={status} health={health} notes={notes} focus={focus} selected={selected} onSelect={setSelected} lift={view === 'landing' ? 2.4 : 0.6} theme={T} />

      <div className="hud-title">
        <h1><span>NetOps</span> Copilot</h1>
        <p>
          <i className="live-dot" style={{ background: connected ? 'var(--green)' : 'var(--red)', boxShadow: connected ? '0 0 10px var(--green)' : 'none' }} />
          {connected ? 'Live network twin · 6 nodes' : 'Backend Disconnected...'}
        </p>
      </div>

      <PipelineStrip pipe={pipe} />

      <div className="topright">
        <ThemeSwitcher themeId={themeId} onChange={setThemeId} />
        <button className={`lab-btn glass ${health && !health.healthy ? 'warn' : ''}`} onClick={() => setPanel((p) => !p)}>
          <span className="lab-dot" />Lab control{health && health.issues.length > 0 ? <em>{health.issues.length}</em> : null}
        </button>
      </div>
      <ControlPanel open={panel} onClose={() => setPanel(false)} health={health} alerts={alerts} apiUrl={API_URL}
        onAsk={(q) => { setPanel(false); submit(q) }} busy={phase !== 'idle'} />

      {health && !health.healthy && dismissed !== health.issues.join('|') && phase === 'idle' && view !== 'chat' && (
        <div className="alert-banner glass">
          <b>⚠ {health.issues.length} problem{health.issues.length > 1 ? 's' : ''} detected</b>
          <span>{health.issues[0]}{health.issues.length > 1 ? ` (+${health.issues.length - 1} more)` : ''}</span>
          <button onClick={() => submit('What is wrong with the network right now? Explain the root cause of each problem.')}>Investigate</button>
          <button className="x" aria-label="Dismiss" onClick={() => setDismissed(health.issues.join('|'))}>✕</button>
        </div>
      )}

      {toast && view === 'minimized' && (
        <div className={`toast glass ${toast.tone}`} style={{ whiteSpace: 'pre-wrap' }}>{toast.text}</div>
      )}

      {info && (
        <div className="inspector glass">
          <h3 style={{ color: routerColor(selected, T) }}>{selected}</h3>
          <dl><dt>Role</dt><dd>{info.role}</dd><dt>AS</dt><dd>{info.as}</dd><dt>Loopback</dt><dd>{info.lo}</dd><dt>State</dt><dd>{status[selected] || health?.routers?.[selected] || 'idle'}</dd></dl>
          <button className="ask-btn" onClick={() => { setIntent(`What is the current state of ${selected}?`); openChat() }}>
            Ask about {selected}
          </button>
        </div>
      )}

      <div className="legend glass">
        <h4>How to read this</h4>
        <div className="lg"><svg width="26" height="18" viewBox="0 0 26 18"><circle cx="13" cy="9" r="4" fill={T.core} /><path d="M13 1v3M13 14v3M3 9h3M20 9h3" stroke={T.core} strokeWidth="2" /></svg><span><b>Router symbol</b> core router (AS 65001)</span></div>
        <div className="lg"><svg width="26" height="18" viewBox="0 0 26 18"><circle cx="13" cy="9" r="7" fill="none" stroke={T.extA} strokeWidth="1.5" /><ellipse cx="13" cy="9" rx="3" ry="7" fill="none" stroke={T.extA} /></svg><span><b>Globe</b> external network / ISP</span></div>
        <div className="lg"><svg width="26" height="18"><line x1="1" y1="9" x2="25" y2="9" stroke={T.ospf} strokeWidth="2" /></svg><span><b>Solid line</b> OSPF, inside your network</span></div>
        <div className="lg"><svg width="26" height="18"><line x1="1" y1="9" x2="25" y2="9" stroke={T.bgp} strokeWidth="2" strokeDasharray="5 3" /></svg><span><b>Dashed line</b> eBGP, to an external AS</span></div>
        <div className="lg"><svg width="26" height="18"><line x1="1" y1="9" x2="25" y2="9" stroke={T.bad} strokeWidth="2" strokeDasharray="3 3" /></svg><span><b>Red dashed</b> link or session is down</span></div>
        <div className="lg"><svg width="26" height="18"><circle cx="13" cy="9" r="3" fill={T.dot} /></svg><span><b>Moving dots</b> routing updates / traffic</span></div>
        <div className="lg"><svg width="26" height="18"><circle cx="13" cy="9" r="5" fill={T.warn} /></svg><span><b>Colour badge</b> agent activity or a problem</span></div>
      </div>

      {view === 'landing' && (
        <LandingHero intent={intent} setIntent={setIntent} onSubmit={submit} phase={phase} connected={connected} />
      )}

      {view === 'chat' && (
        <ChatPanel
          msgs={msgs} pipeline={PIPELINE} phase={phase} connected={connected}
          intent={intent} setIntent={setIntent} onSubmit={submit}
          onMinimize={() => setView('minimized')} onNewSession={newSession}
        />
      )}

      {view === 'minimized' && (
        <ChatPill onClick={openChat} unread={unread} phase={phase} count={msgs.filter((m) => m.role === 'user' || m.role === 'agent').length} />
      )}

      {approval && <ApprovalModal approval={approval} onDecide={handleDecision} />}
    </div>
  )
}