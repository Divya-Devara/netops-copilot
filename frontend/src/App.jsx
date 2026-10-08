import { useState, useRef, useEffect, useMemo } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Html, Line, Grid, Sparkles, Stars, Float, RoundedBox, Edges } from '@react-three/drei'
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing'
import * as THREE from 'three'
import './index.css'

/* ═════════ 1. DATA ═════════ */
const ROUTERS = {
  r1: { pos: [-2.5, 0, -2.5], as: 65001, lo: '1.1.1.1', role: 'Core', color: '#38bdf8' },
  r2: { pos: [2.5, 0, -2.5],  as: 65001, lo: '2.2.2.2', role: 'Core', color: '#38bdf8' },
  r3: { pos: [-2.5, 0, 2.5],  as: 65001, lo: '3.3.3.3', role: 'Core', color: '#38bdf8' },
  r4: { pos: [2.5, 0, 2.5],   as: 65001, lo: '4.4.4.4', role: 'Core', color: '#38bdf8' },
  r5: { pos: [-6.5, 0, -2.5], as: 65002, lo: '5.5.5.5', role: 'External', color: '#a78bfa' },
  r6: { pos: [6.5, 0, 2.5],   as: 65003, lo: '6.6.6.6', role: 'External', color: '#fbbf24' },
}
const LINKS = [['r1','r2','ospf'],['r1','r3','ospf'],['r2','r4','ospf'],['r3','r4','ospf'],['r1','r5','bgp'],['r4','r6','bgp']]
const LINK_COLOR = { ospf: '#22d3ee', bgp: '#34d399' }
const STATUS = { scan: '#22d3ee', plan: '#a78bfa', twin: '#e879f9', apply: '#fbbf24', verify: '#34d399', fail: '#f87171' }
const FLOOR = -1.7
const PIPELINE = [
  { id: 'classify', label: 'Classify' }, { id: 'diagnose', label: 'Diagnose' }, { id: 'plan', label: 'Plan' },
  { id: 'review', label: 'Review', gate: true }, { id: 'policy', label: 'Policy', gate: true }, { id: 'twin', label: 'Twin', gate: true },
  { id: 'approve', label: 'Approve' }, { id: 'apply', label: 'Apply' }, { id: 'verify', label: 'Verify' },
]

/* ═════════ 2. 3D ═════════ */
function RouterNode({ id, status, note, selected, onSelect }) {
  const r = ROUTERS[id]
  const color = STATUS[status] || r.color
  const busy = !!status
  const rings = [useRef(), useRef()], core = useRef(), halo = useRef()
  const [hover, setHover] = useState(false)

  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime, sp = busy ? 2.4 : 0.5
    rings[0].current.rotation.x += dt * sp;       rings[0].current.rotation.y += dt * sp * 0.6
    rings[1].current.rotation.z -= dt * sp * 0.8; rings[1].current.rotation.y += dt * sp * 0.3
    core.current.scale.setScalar((busy ? 1 + Math.sin(t * 7) * 0.18 : 1) * (hover || selected ? 1.2 : 1))
    core.current.rotation.y += dt * 0.8
    halo.current.material.opacity = busy ? 0.25 + Math.sin(t * 7) * 0.12 : 0.1
  })

  return (
    <group position={r.pos}
      onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = 'pointer' }}
      onPointerOut={() => { setHover(false); document.body.style.cursor = 'auto' }}
      onClick={(e) => { e.stopPropagation(); onSelect(id) }}>
      <Float speed={1.6} floatIntensity={0.5} rotationIntensity={0} floatingRange={[-0.08, 0.12]}>
        <RoundedBox args={[1.5, 0.26, 1.5]} radius={0.06} smoothness={4}>
          <meshStandardMaterial color="#0b1220" metalness={0.9} roughness={0.25} />
          <Edges color={color} threshold={15} />
        </RoundedBox>
        {[-0.45, -0.15, 0.15, 0.45].map((x) => (
          <mesh key={x} position={[x, 0.14, 0.72]}><boxGeometry args={[0.12, 0.04, 0.02]} /><meshBasicMaterial color={color} toneMapped={false} /></mesh>
        ))}
        <group position={[0, 0.85, 0]}>
          <mesh ref={core}><icosahedronGeometry args={[0.32, 1]} /><meshBasicMaterial color={color} wireframe toneMapped={false} /></mesh>
          <mesh><octahedronGeometry args={[0.14]} /><meshBasicMaterial color="#ffffff" toneMapped={false} /></mesh>
          <mesh ref={halo}><sphereGeometry args={[0.55, 24, 24]} /><meshBasicMaterial color={color} transparent opacity={0.1} depthWrite={false} toneMapped={false} /></mesh>
          <mesh ref={rings[0]}><torusGeometry args={[0.62, 0.012, 8, 64]} /><meshBasicMaterial color={color} toneMapped={false} /></mesh>
          <mesh ref={rings[1]}><torusGeometry args={[0.8, 0.008, 8, 64]} /><meshBasicMaterial color={color} transparent opacity={0.6} toneMapped={false} /></mesh>
        </group>
      </Float>
      <mesh position={[0, FLOOR / 2, 0]}><cylinderGeometry args={[0.02, 0.02, -FLOOR, 8]} /><meshBasicMaterial color={color} transparent opacity={0.35} toneMapped={false} /></mesh>
      <mesh position={[0, FLOOR + 0.01, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.9, 1.0, 48]} /><meshBasicMaterial color={color} transparent opacity={selected || busy ? 0.9 : 0.45} toneMapped={false} />
      </mesh>
      <Html position={[0, -0.75, 0]} center distanceFactor={10} zIndexRange={[5, 0]}>
        <div className="node-label" style={{ borderColor: selected ? color : undefined }}><b style={{ color }}>{id}</b><span>AS {r.as}</span></div>
      </Html>
      {note && (
        <Html position={[0, 2.3, 0]} center distanceFactor={10} zIndexRange={[8, 0]}>
          <div className="callout" style={{ color, borderColor: color, boxShadow: `0 0 24px ${color}55` }}>{note}</div>
        </Html>
      )}
    </group>
  )
}

function Link({ a, b, kind, active }) {
  const pa = useMemo(() => new THREE.Vector3(...ROUTERS[a].pos), [a])
  const pb = useMemo(() => new THREE.Vector3(...ROUTERS[b].pos), [b])
  const dots = useRef([]), color = LINK_COLOR[kind]
  useFrame(({ clock }) => dots.current.forEach((m, i) => {
    m.position.lerpVectors(pa, pb, (clock.elapsedTime * (active ? 0.7 : 0.18) + i / 3) % 1)
    m.scale.setScalar(active ? 1.6 : 1)
  }))
  const pts = [pa, pb]
  return (
    <group>
      <Line points={pts} color={color} lineWidth={7} transparent opacity={active ? 0.3 : 0.1} toneMapped={false} />
      <Line points={pts} color={color} lineWidth={1.6} transparent opacity={0.9} toneMapped={false} dashed={kind === 'bgp'} dashSize={0.25} gapSize={0.15} />
      {[0, 1, 2].map((i) => (
        <mesh key={i} ref={(m) => (dots.current[i] = m)}><sphereGeometry args={[0.055, 10, 10]} /><meshBasicMaterial color="#ffffff" toneMapped={false} /></mesh>
      ))}
    </group>
  )
}

function CameraRig({ focus }) {
  const controls = useThree((s) => s.controls)
  const want = useMemo(() => new THREE.Vector3(), [])
  useFrame((_, dt) => {
    if (!controls) return
    want.set(...(focus ? ROUTERS[focus].pos : [0, 0, 0]))
    controls.target.lerp(want, 1 - Math.pow(0.02, dt))
    controls.autoRotate = !focus
    controls.update()
  })
  return null
}

function Topology({ status, notes, selected, onSelect }) {
  return (
    <group>
      <mesh position={[0, FLOOR + 0.005, 0]} rotation-x={-Math.PI / 2}>
        <planeGeometry args={[6.4, 6.4]} /><meshBasicMaterial color="#22d3ee" transparent opacity={0.045} depthWrite={false} />
      </mesh>
      <Html position={[0, FLOOR, 3.7]} center><div className="zone-label">OSPF AREA 0 · AS 65001</div></Html>
      {LINKS.map(([a, b, k]) => <Link key={a + b} a={a} b={b} kind={k} active={!!status[a] && !!status[b]} />)}
      {Object.keys(ROUTERS).map((id) => (
        <RouterNode key={id} id={id} status={status[id]} note={notes[id]} selected={selected === id} onSelect={onSelect} />
      ))}
    </group>
  )
}

function Scene({ status, notes, focus, selected, onSelect }) {
  return (
    <Canvas camera={{ position: [0, 7.5, 13.5], fov: 45 }} dpr={[1, 2]} onPointerMissed={() => onSelect(null)}>
      <color attach="background" args={['#05070d']} />
      <fog attach="fog" args={['#05070d', 16, 40]} />
      <ambientLight intensity={0.5} />
      <pointLight position={[0, 6, 0]} intensity={40} color="#7dd3fc" />
      <pointLight position={[-8, 3, 6]} intensity={25} color="#a78bfa" />
      <Stars radius={60} depth={40} count={2500} factor={3} fade speed={0.6} />
      <Sparkles count={90} scale={[20, 7, 14]} position={[0, 1, 0]} size={2.2} speed={0.35} color="#7dd3fc" opacity={0.6} />
      <Grid position={[0, FLOOR, 0]} args={[40, 40]} cellSize={1} cellThickness={0.6} cellColor="#16335a"
        sectionSize={5} sectionThickness={1.2} sectionColor="#2b7bb9" fadeDistance={30} fadeStrength={1.6} infiniteGrid />
      <Topology status={status} notes={notes} selected={selected} onSelect={onSelect} />
      <EffectComposer multisampling={0}>
        <Bloom mipmapBlur intensity={1.25} luminanceThreshold={0.25} luminanceSmoothing={0.2} />
        <Vignette eskil={false} offset={0.2} darkness={0.85} />
      </EffectComposer>
      <OrbitControls makeDefault enableDamping dampingFactor={0.06} autoRotate autoRotateSpeed={0.35}
        minDistance={6} maxDistance={26} maxPolarAngle={Math.PI / 2.15} />
      <CameraRig focus={focus} />
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
        <div className="gatesum"><span>✓ Reviewer</span><span>✓ Policy</span><span>✓ Twin</span></div>
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
function useNetops(onMessage) {
  const [connected, setConnected] = useState(false)
  const ws = useRef(null)

  useEffect(() => {
    let timeout
    const connect = () => {
      const url = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
      ws.current = new WebSocket(url)
      ws.current.onopen = () => setConnected(true)
      ws.current.onclose = () => {
        setConnected(false)
        timeout = setTimeout(connect, 3000)
      }
      ws.current.onmessage = (e) => onMessage(JSON.parse(e.data))
    }
    connect()
    
    return () => {
      clearTimeout(timeout)
      if (ws.current) ws.current.close()
    }
  }, [])

  const send = (msg) => {
    if (ws.current && connected) ws.current.send(JSON.stringify(msg))
  }

  return { connected, send }
}

const EXAMPLES = ['Set OSPF cost on r1 eth1 to 100', 'Why can r5 not reach r6?', 'policy: test blocking']

export default function App() {
  const [msgs, setMsgs] = useState([])
  const [intent, setIntent] = useState('')
  const [phase, setPhase] = useState('idle')
  const [pipe, setPipe] = useState({})                
  const [status, setStatus] = useState({})            
  const [notes, setNotes] = useState({})              
  const [focus, setFocus] = useState(null)            
  const [approval, setApproval] = useState(null)
  const [selected, setSelected] = useState(null)
  const [toast, setToast] = useState(null)
  const [open, setOpen] = useState(false)
  
  // Create ONE thread ID when the app loads so LangGraph remembers the chat history
  const threadRef = useRef(crypto.randomUUID())
  const feed = useRef(null)

  useEffect(() => { feed.current?.scrollTo({ top: 1e6, behavior: 'smooth' }) }, [msgs, open])
  
  // Extend toast duration for answers so you have more time to read, otherwise standard 7s
  useEffect(() => { 
    if (toast) { 
      const duration = toast.tone === 'info' ? 12000 : 7000
      const t = setTimeout(() => setToast(null), duration)
      return () => clearTimeout(t) 
    } 
  }, [toast])

  const say = (role, text, tone = '') => setMsgs((m) => [...m, { role, text, tone }])
  const S = (id, s) => setPipe((p) => ({ ...p, [id]: s }))
  const setRouters = (ids, mode) => setStatus(Object.fromEntries(ids.map((id) => [id, mode])))
  const note = (router, text) => setNotes(router ? { [router]: text } : {})

  const finish = (tone, text) => { 
    setToast({ tone, text })
    if (tone === 'info' || tone === 'bad') {
      say('agent', text, tone)
      // Automatically open the drawer so the user can easily read long answers
      setOpen(true)
    }
    setStatus({})
    setNotes({})
    setFocus(null)
    setPhase('idle') 
  }

  const handleMessage = (msg) => {
    if (msg.type === 'stage') {
      S(msg.node, msg.status)
      const r = (msg.routers && msg.routers.length > 0) ? msg.routers[0] : 'r1'
      setRouters(msg.routers || ['r1'], msg.mode)
      note(r, msg.detail)
      setFocus(r)
      if (msg.status === 'running') say('step', msg.detail)
    } 
    else if (msg.type === 'approval_request') {
      setApproval({ plan: msg.plan, diffs: msg.diffs })
      S('approve', 'wait')
      setPhase('awaiting')
    } 
    else if (msg.type === 'final') {
      const toneMap = { applied: 'good', blocked: 'bad', rolled_back: 'bad', error: 'bad', rejected: 'info', answer: 'info' }
      finish(toneMap[msg.outcome] || 'info', msg.text)
    }
  }

  const { connected, send } = useNetops(handleMessage)

  const submit = (e) => { 
    e.preventDefault()
    if (!intent.trim() || phase !== 'idle' || !connected) return
    const x = intent.trim()
    setIntent('')
    setPhase('running')
    setPipe({})
    setToast(null)
    say('user', x)
    
    // We send the persistent thread ID with every WebSocket intent payload
    send({ type: 'intent', text: x, thread_id: threadRef.current })
  }

  const handleDecision = (decision) => {
    setApproval(null)
    S('approve', 'done')
    setPhase('running')
    send({ type: 'decision', value: decision, thread_id: threadRef.current })
  }

  const info = selected && ROUTERS[selected]

  return (
    <div className="stage">
      <Scene status={status} notes={notes} focus={focus} selected={selected} onSelect={setSelected} />

      <div className="hud-title">
        <h1><span>NetOps</span> Copilot</h1>
        <p>
          <i className="live-dot" style={{ background: connected ? '#34d399' : '#f87171', boxShadow: connected ? '0 0 10px #34d399' : 'none' }} />
          {connected ? 'Live network twin · 6 nodes' : 'Backend Disconnected...'}
        </p>
      </div>

      <PipelineStrip pipe={pipe} />
      
      {/* Added pre-wrap styling here so toast paragraphs format cleanly */}
      {toast && <div className={`toast glass ${toast.tone}`} style={{ whiteSpace: 'pre-wrap' }}>{toast.text}</div>}

      {info && (
        <div className="inspector glass">
          <h3 style={{ color: info.color }}>{selected}</h3>
          <dl><dt>Role</dt><dd>{info.role}</dd><dt>AS</dt><dd>{info.as}</dd><dt>Loopback</dt><dd>{info.lo}</dd><dt>State</dt><dd>{status[selected] || 'idle'}</dd></dl>
        </div>
      )}

      <div className="legend">
        <span className="chip"><i style={{ background: '#22d3ee' }} />OSPF link</span>
        <span className="chip"><i style={{ background: '#34d399' }} />eBGP peering</span>
      </div>

      <button className="drawer-btn glass" onClick={() => setOpen(!open)}>
        {phase === 'running' && <span className="live" />}Activity <span className="badge">{msgs.length}</span>
      </button>
      
      <aside className={`drawer glass ${open ? 'open' : ''}`}>
        <h2>Agent activity log</h2>
        <div className="feed" ref={feed}>
          {msgs.length === 0 && <div className="empty">Nothing yet. Run a command below.</div>}
          
          {/* Added pre-wrap styling here so drawer paragraphs format cleanly */}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role} ${m.tone}`} style={{ whiteSpace: 'pre-wrap' }}>
              {m.text}
            </div>
          ))}
        </div>
      </aside>

      <div className="dock">
        {phase === 'idle' && !intent && connected && (
          <div className="suggest">{EXAMPLES.map((x) => <button key={x} onClick={() => setIntent(x)}>{x}</button>)}</div>
        )}
        <form className="composer" onSubmit={submit}>
          <span className="prompt">›</span>
          <input 
            value={intent} 
            onChange={(e) => setIntent(e.target.value)} 
            disabled={phase !== 'idle' || !connected}
            placeholder={
              !connected ? 'Connecting to backend...' : 
              phase === 'idle' ? 'Tell the network what to do…' : 
              phase === 'awaiting' ? 'Waiting for your approval…' : 'Agent is working…'
            } 
          />
          <button disabled={phase !== 'idle' || !intent.trim() || !connected}>Execute</button>
        </form>
      </div>

      {approval && <ApprovalModal approval={approval} onDecide={handleDecision} />}
    </div>
  )
}