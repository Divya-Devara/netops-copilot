import { createContext, useContext } from 'react'

/* Palettes for the 3D scene. The matching CSS tokens live in themes.css (keep the two in sync). */
export const THEMES = {
  aurora: {
    label: 'Aurora', swatch: ['#22d3ee', '#a78bfa'], dark: true,
    bg: '#05070d', gridCell: '#16335a', gridSection: '#2b7bb9', chassis: '#0d1526', vent: '#1c2b4a', dot: '#ffffff',
    core: '#38bdf8', extA: '#a78bfa', extB: '#fbbf24', ospf: '#22d3ee', bgp: '#34d399', bad: '#f87171', warn: '#fbbf24', ok: '#34d399',
    sparkle: '#7dd3fc', bloom: 1.25, stars: true, ambient: 0.5, light1: '#7dd3fc', light2: '#a78bfa',
    status: { scan: '#22d3ee', plan: '#a78bfa', twin: '#e879f9', apply: '#fbbf24', verify: '#34d399', fail: '#f87171' },
  },
  amber: {
    label: 'Cyber amber', swatch: ['#fbbf24', '#fb7185'], dark: true,
    bg: '#0a0806', gridCell: '#3a2a10', gridSection: '#a8741a', chassis: '#1a130a', vent: '#3a2c18', dot: '#fff7e0',
    core: '#fbbf24', extA: '#fb7185', extB: '#38bdf8', ospf: '#fbbf24', bgp: '#a3e635', bad: '#ef4444', warn: '#fb923c', ok: '#a3e635',
    sparkle: '#fbbf24', bloom: 1.1, stars: true, ambient: 0.5, light1: '#fbbf24', light2: '#fb7185',
    status: { scan: '#fbbf24', plan: '#fb7185', twin: '#e879f9', apply: '#fb923c', verify: '#a3e635', fail: '#ef4444' },
  },
  light: {
    label: 'Mission control', swatch: ['#2563eb', '#7c3aed'], dark: false,
    bg: '#e9eef7', gridCell: '#c3d0e6', gridSection: '#8fa8d0', chassis: '#b6c2d6', vent: '#8ea0bc', dot: '#0f172a',
    core: '#2563eb', extA: '#7c3aed', extB: '#d97706', ospf: '#2563eb', bgp: '#059669', bad: '#dc2626', warn: '#d97706', ok: '#059669',
    sparkle: '#3b82f6', bloom: 0, stars: false, ambient: 1.3, light1: '#ffffff', light2: '#93c5fd',
    status: { scan: '#0891b2', plan: '#7c3aed', twin: '#c026d3', apply: '#d97706', verify: '#059669', fail: '#dc2626' },
  },
}

export const ThemeContext = createContext(THEMES.aurora)
export const useTheme = () => useContext(ThemeContext)

const KEY = 'netops.theme'
export const loadTheme = () => {
  const q = new URLSearchParams(window.location.search).get('theme')   // ?theme=light for sharing/screenshots
  if (THEMES[q]) return q
  try { const t = localStorage.getItem(KEY); if (THEMES[t]) return t } catch { /* private mode */ }
  return 'aurora'
}
export const saveTheme = (t) => { try { localStorage.setItem(KEY, t) } catch { /* private mode */ } }
