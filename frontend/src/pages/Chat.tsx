import { useEffect, useRef, useState } from 'react'
import { api, type Json } from '../api'
import { Markdown } from '../components/Markdown'
import { useApi } from '../components/useApi'

const TOOL_LABEL: Record<string, string> = {
  get_today_whoop: '今日 WHOOP',
  get_recovery_history: 'Recovery 历史',
  get_hrv_history: 'HRV 历史',
  get_rhr_history: 'RHR 历史',
  get_sleep_history: '睡眠历史',
  get_strain_history: 'Strain 历史',
  get_workout_history: '训练记录',
  get_personal_baseline: '个人基线',
  get_metric_trend: '指标趋势',
  detect_anomalies: '异常检测',
  get_recent_events: '近期事件',
  get_user_profile: '用户背景',
  get_training_plan: '训练计划',
  search_relevant_memory: '检索记忆',
  get_learned_patterns: '个人规律',
  find_similar_days: '相似日子',
  analyze_recovery_drivers: '恢复驱动因素',
  get_daily_report: '日报',
  get_weekly_report: '周报',
  save_memory: '保存记忆',
}

function ToolCalls({ calls }: { calls: Json[] }) {
  const [open, setOpen] = useState<number | null>(null)
  if (!calls?.length) return null
  return (
    <>
      <div className="tools">
        {calls.map((c, i) => (
          <span key={i} className={`chip tool-chip ${c.name === 'save_memory' ? 'good' : 'info'}`} onClick={() => setOpen(open === i ? null : i)} title="点击查看调用详情">
            ⚙ {TOOL_LABEL[c.name] ?? c.name}
            {c.args && Object.keys(c.args).length > 0 && <span style={{ opacity: 0.7 }}>({Object.values(c.args).filter((v) => typeof v !== 'boolean').join(', ').slice(0, 30)})</span>}
          </span>
        ))}
      </div>
      {open !== null && (
        <div className="tool-detail">
          {calls[open].name}({JSON.stringify(calls[open].args)}){'\n'}→ {calls[open].result}
        </div>
      )}
    </>
  )
}

export default function Chat({ status }: { status: Json }) {
  const convs = useApi<Json[]>('/api/conversations')
  const sugg = useApi<string[]>('/api/chat/suggestions')
  const [cid, setCid] = useState<number | null>(null)
  const [messages, setMessages] = useState<Json[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  const openConv = async (id: number) => {
    const c = await api.get(`/api/conversations/${id}`)
    setCid(id)
    setMessages(c.messages)
  }

  const send = async (text?: string) => {
    const msg = (text ?? input).trim()
    if (!msg || sending) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: msg, id: `tmp-${Date.now()}` }])
    setSending(true)
    try {
      const r = await api.post('/api/chat', { message: msg, conversation_id: cid })
      setCid(r.conversation_id)
      setMessages((m) => [...m, r.message])
      convs.reload()
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', content: `请求失败：${(e as Error).message}`, id: `err-${Date.now()}` }])
    } finally {
      setSending(false)
    }
  }

  const llm = status?.llm
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">AI 对话</div>
          <div className="page-sub">
            每个回答都先调用真实 WHOOP 数据 ·{' '}
            {llm?.enabled ? `模型：${llm.model}` : '当前为规则引擎模式（未配置大模型）'}
          </div>
        </div>
        <button className="btn" onClick={() => { setCid(null); setMessages([]) }}>＋ 新对话</button>
      </div>
      <div className="chat">
        <div className="card conv-list">
          {(convs.data ?? []).map((c) => (
            <div key={c.id} className={`conv-item ${cid === c.id ? 'on' : ''}`} onClick={() => openConv(c.id)} title={c.title}>
              {c.title}
            </div>
          ))}
          {convs.data?.length === 0 && <div className="muted small" style={{ padding: 8 }}>还没有对话</div>}
        </div>
        <div className="card chat-main">
          <div className="messages">
            {messages.length === 0 && (
              <div style={{ margin: 'auto 0' }}>
                <h3 style={{ marginBottom: 6 }}>问问你的 WHOOP 数据</h3>
                <p className="muted" style={{ marginTop: 0 }}>Agent 会先调用分析工具拿到真实数据，再结合你的个人基线、长期规律和记忆回答。你也可以直接告诉它“昨晚喝了酒”“这周开始减脂”，它会记住。</p>
                <div className="suggests">
                  {(sugg.data ?? []).map((s) => (
                    <span key={s} className="chip suggest" onClick={() => send(s)}>{s}</span>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                {m.role === 'assistant' && <ToolCalls calls={m.tool_calls} />}
                {m.role === 'assistant' ? <Markdown text={m.content} /> : m.content}
              </div>
            ))}
            {sending && <div className="typing">正在调用数据工具并分析…</div>}
            <div ref={bottom} />
          </div>
          <div className="composer">
            <textarea
              className="input"
              rows={1}
              placeholder="例如：为什么我今天 Recovery 这么低？（Enter 发送，Shift+Enter 换行）"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <button className="btn btn-primary" onClick={() => send()} disabled={sending || !input.trim()}>发送</button>
          </div>
        </div>
      </div>
    </div>
  )
}
