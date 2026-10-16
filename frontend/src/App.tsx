import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, type Json } from './api'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import Journal from './pages/Journal'
import Patterns from './pages/Patterns'
import Settings from './pages/Settings'
import Trends from './pages/Trends'
import Weekly from './pages/Weekly'

const NAV = [
  { to: '/', label: '今日状态', icon: '◎' },
  { to: '/trends', label: '趋势', icon: '〰' },
  { to: '/chat', label: 'AI 对话', icon: '✦' },
  { to: '/weekly', label: '周报', icon: '▦' },
  { to: '/patterns', label: '个人规律', icon: '⌁' },
  { to: '/journal', label: '记录与计划', icon: '✎' },
  { to: '/settings', label: '设置', icon: '⚙' },
]

type Theme = 'system' | 'light' | 'dark'

function readTheme(): Theme {
  try {
    return (localStorage.getItem('theme') as Theme) || 'system'
  } catch {
    return 'system'
  }
}

function applyTheme(t: Theme) {
  if (t === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', t)
  try {
    localStorage.setItem('theme', t)
  } catch {
    /* 隐私模式下忽略 */
  }
}

export default function App() {
  const [status, setStatus] = useState<Json>(null)
  const [theme, setTheme] = useState<Theme>(readTheme)
  const refresh = () => api.get('/api/status').then(setStatus).catch(() => setStatus(null))

  useEffect(() => {
    refresh()
  }, [])
  useEffect(() => applyTheme(theme), [theme])

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" />
          <div>
            <div className="brand-name">WHOOP AI Analyst</div>
            <div className="brand-sub">智能身体状态分析助手</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              <span className="nav-icon">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          {status && (
            <>
              <span>{status.user.name} · {status.data.days} 天数据</span>
              <span>{status.whoop.connected ? 'WHOOP 已连接' : status.user.is_demo ? 'Demo 模式' : 'WHOOP 未连接'} · {status.llm.enabled ? status.llm.model : '规则引擎'}</span>
            </>
          )}
          <div className="seg" style={{ alignSelf: 'flex-start' }}>
            {(['system', 'light', 'dark'] as Theme[]).map((t) => (
              <button key={t} className={theme === t ? 'on' : ''} onClick={() => setTheme(t)}>{{ system: '自动', light: '浅色', dark: '深色' }[t]}</button>
            ))}
          </div>
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard status={status} />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/chat" element={<Chat status={status} />} />
          <Route path="/weekly" element={<Weekly status={status} />} />
          <Route path="/patterns" element={<Patterns />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/settings" element={<Settings status={status} refresh={refresh} />} />
        </Routes>
      </main>
    </div>
  )
}
