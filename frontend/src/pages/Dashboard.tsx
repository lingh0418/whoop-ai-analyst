import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CONFIDENCE_LABEL, deltaTone, fmtMinutes, fmtP, levelColor, recoveryColor, SEVERITY_LABEL, type Json } from '../api'
import { Markdown } from '../components/Markdown'
import { ScoreRing } from '../components/ScoreRing'
import { Sparkline } from '../components/Sparkline'
import { useApi } from '../components/useApi'

function Arrow({ delta }: { delta: number | null | undefined }) {
  if (delta === null || delta === undefined || Math.abs(delta) < 1e-9) return <span>→</span>
  return <span aria-hidden>{delta > 0 ? '↑' : '↓'}</span>
}

function MetricTile({ t }: { t: Json }) {
  if (!t.available) {
    return (
      <div className="card tile">
        <div className="tile-label">{t.label}</div>
        <div className="tile-value muted">—</div>
      </div>
    )
  }
  const tone = deltaTone(t.direction, t.delta_abs, t.z)
  const values = (t.recent || []).map((r: Json) => r.value)
  const color = t.metric === 'recovery' ? recoveryColor(t.value) : undefined
  return (
    <div className="card tile">
      <div className="tile-label">{t.label}</div>
      <div className="tile-value" style={color ? { color } : undefined}>{t.value_text}</div>
      {t.delta_text && (
        <div className={`tile-delta ${tone}`}>
          <Arrow delta={t.delta_abs} /> {t.delta_text.replace(/^(高|低|多|少)约? ?/, '')}
          <span className="muted small" style={{ fontWeight: 400 }}>vs 基线</span>
        </div>
      )}
      <div className="tile-base">28 日基线 {t.baseline_text}{t.consecutive_unfavorable_days >= 2 ? ` · 连续 ${t.consecutive_unfavorable_days} 天偏离` : ''}</div>
      {values.length > 1 && <Sparkline values={values} baseline={t.baseline} />}
    </div>
  )
}

function Hero({ d }: { d: Json }) {
  const s = d.state
  const tone = s.severity >= 2 ? 'bad' : s.severity === 1 ? 'warn' : 'good'
  return (
    <div className="card hero">
      <ScoreRing score={s.score} color={levelColor(s.level)} />
      <div className="hero-meta">
        <div className="row">
          <span className="muted">{d.date} · 今日身体状态</span>
          <span className={`chip ${tone}`}>{s.level_label ?? '—'}</span>
          <span className="chip">{s.trend.text}</span>
        </div>
        <div className="hero-state">{s.joint_label}</div>
        <div className="hero-headline">{d.joint.headline}</div>
        <div className="row small muted">
          <span>判断置信度：{CONFIDENCE_LABEL[s.confidence] ?? s.confidence}</span>
          <span>·</span>
          <span>已积累 {d.data_days} 天数据</span>
          {d.strain_today !== null && d.strain_today !== undefined && (
            <>
              <span>·</span>
              <span>今日 Strain（进行中）{d.strain_today.toFixed(1)}</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function AIAnalysis({ d, onAI, aiLoading, llmEnabled }: { d: Json; onAI: () => void; aiLoading: boolean; llmEnabled: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card">
      <div className="card-title">
        AI 今日分析 <span className="hint">由 Python 分析层计算，{d.ai_summary ? `${d.ai_model} 解读` : '规则引擎生成'}</span>
        <span className="spacer" />
        {llmEnabled && (
          <button className="btn btn-sm" onClick={onAI} disabled={aiLoading}>
            {aiLoading ? '生成中…' : d.ai_summary ? '重新生成 AI 解读' : '生成 AI 解读'}
          </button>
        )}
      </div>
      {d.ai_summary && <div className="md" style={{ marginBottom: 14 }}>{d.ai_summary}</div>}
      <ol className="conclusions">
        {d.conclusions.map((c: string, i: number) => (
          <li key={i}>
            <span className="num">{i + 1}</span>
            <span>{c}</span>
          </li>
        ))}
      </ol>
      <div style={{ marginTop: 14 }}>
        <button className="btn btn-sm" onClick={() => setOpen((x) => !x)}>{open ? '收起完整日报' : '查看完整日报'}</button>
      </div>
      {open && (
        <div style={{ marginTop: 12 }}>
          <Markdown text={d.narrative} />
        </div>
      )}
    </div>
  )
}

function Signals({ d }: { d: Json }) {
  const j = d.joint
  const color = (dir: string) => (dir === 'negative' ? 'var(--critical)' : dir === 'positive' ? 'var(--good)' : 'var(--muted)')
  const label = (dir: string) => (dir === 'negative' ? '不利' : dir === 'positive' ? '有利' : '中性')
  return (
    <div className="card">
      <div className="card-title">多指标联合判断 <span className="hint">看指标是否同向变化，而不是逐个解释</span></div>
      {j.signals.map((s: Json, i: number) => (
        <div className="signal" key={i}>
          <span className="dot" style={{ background: color(s.direction) }} />
          <div style={{ flex: 1 }}>{s.text}</div>
          <span className="chip small">{label(s.direction)}</span>
        </div>
      ))}
      {j.verdict && <p className="text-2" style={{ marginBottom: 0, whiteSpace: 'pre-line' }}>{j.verdict}</p>}
      <div className="caution">{j.caution}</div>
      {d.anomalies.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="small muted" style={{ marginBottom: 6 }}>今日异常检测</div>
          <div className="row">
            {d.anomalies.map((a: Json, i: number) => (
              <span key={i} className={`chip ${a.severity === 'high' ? 'bad' : a.severity === 'medium' ? 'warn' : ''}`} title={a.message}>
                ⚠ {a.label} · {SEVERITY_LABEL[a.severity]}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Training({ t }: { t: Json }) {
  const orig = t.original
  const adj = t.adjusted
  return (
    <div className="card">
      <div className="card-title">
        今日训练 <span className="hint">先看身体状态，再调整计划</span>
        <span className="spacer" />
        <span className={`chip ${t.level === 'normal' ? 'good' : t.level === 'caution' ? 'warn' : 'bad'}`}>{t.summary.split('；')[0]}</span>
      </div>
      {!orig ? (
        <p className="text-2">{t.summary}</p>
      ) : (
        <>
          <div className="row" style={{ marginBottom: 8 }}>
            <strong>{orig.title}</strong>
            <span className="muted small">原计划强度：{orig.intensity}</span>
          </div>
          <table className="tbl">
            <thead>
              <tr><th>动作</th><th>原计划</th><th>调整后</th></tr>
            </thead>
            <tbody>
              {orig.exercises.map((e: Json, i: number) => {
                const a = adj.exercises.find((x: Json) => x.name === e.name)
                const fmt = (x: Json) => `${x.sets ?? ''} × ${x.reps ?? ''}${x.rpe ? ` · RPE ${x.rpe}` : ''}`
                const changed = !a || fmt(a) !== fmt(e)
                return (
                  <tr key={i}>
                    <td>{e.name}{e.weight ? <span className="muted small"> · {e.weight}</span> : null}</td>
                    <td className={changed ? 'muted' : ''}>{fmt(e)}</td>
                    <td className={changed ? 'changed' : ''}>{a ? fmt(a) : <span className="strike">取消</span>}</td>
                  </tr>
                )
              })}
              {adj.exercises.filter((x: Json) => !orig.exercises.some((e: Json) => e.name === x.name)).map((x: Json, i: number) => (
                <tr key={`n${i}`}>
                  <td>{x.name}</td>
                  <td className="muted">—</td>
                  <td className="changed">{x.sets} × {x.reps}{x.rpe ? ` · RPE ${x.rpe}` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul style={{ margin: '10px 0 0', paddingLeft: 18 }} className="text-2">
            {t.changes.map((c: string, i: number) => <li key={i}>{c}</li>)}
          </ul>
        </>
      )}
    </div>
  )
}

function Nutrition({ n }: { n: Json }) {
  const p = n.plan
  return (
    <div className="card">
      <div className="card-title">饮食 <span className="hint">辅助建议</span></div>
      {p && (
        <div className="stat-grid" style={{ marginBottom: 12 }}>
          <div className="stat"><div className="k">{p.goal_label} · {p.day_type_label}</div><div className="v">{p.calories ?? '—'} kcal</div></div>
          <div className="stat"><div className="k">蛋白质</div><div className="v">{p.protein ?? '—'} g</div></div>
          <div className="stat"><div className="k">碳水</div><div className="v">{p.carbs ?? '—'} g</div></div>
          <div className="stat"><div className="k">脂肪</div><div className="v">{p.fat ?? '—'} g</div></div>
        </div>
      )}
      <ul style={{ margin: 0, paddingLeft: 18 }} className="text-2">
        {n.advice.map((a: string, i: number) => <li key={i}>{a}</li>)}
      </ul>
    </div>
  )
}

function Context({ d }: { d: Json }) {
  const sim = d.similar_days
  return (
    <div className="grid grid-3">
      <div className="card">
        <div className="card-title">相关的个人规律 <span className="hint">相关趋势 ≠ 因果</span></div>
        {d.patterns.length === 0 && <div className="muted small">今天的情况暂时没有匹配到已学到的规律。<Link to="/patterns">查看全部规律 →</Link></div>}
        {d.patterns.map((p: Json) => (
          <div className="pattern" key={p.key}>
            <div>{p.title}</div>
            <div className="small muted">样本 {p.sample_size} 天 · {fmtP(p.p_value)} · 置信度 {CONFIDENCE_LABEL[p.confidence]}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <div className="card-title">这种情况过去出现过吗</div>
        {!sim?.available ? (
          <div className="muted small">历史数据还不够。</div>
        ) : (
          <>
            <p className="text-2 small" style={{ marginTop: 0 }}>{sim.summary}</p>
            <table className="tbl">
              <thead><tr><th>日期</th><th>HRV</th><th>RHR</th><th>之后 3 天 Recovery</th></tr></thead>
              <tbody>
                {sim.items.slice(0, 4).map((x: Json) => (
                  <tr key={x.date}>
                    <td>{x.date.slice(5)}</td>
                    <td>{(x.hrv_dev * 100).toFixed(0)}%</td>
                    <td>{x.rhr_dev > 0 ? '+' : ''}{(x.rhr_dev * 100).toFixed(0)}%</td>
                    <td>{x.next_days_recovery.map((v: number | null) => (v === null ? '—' : `${v}%`)).join(' → ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
      <div className="card">
        <div className="card-title">近期记录 <span className="hint">长期记忆</span><span className="spacer" /><Link className="small" to="/journal">添加</Link></div>
        {d.events.length === 0 && <div className="muted small">最近两天没有记录。喝酒、熬夜、考试、出差等都可能影响恢复，记录下来能让分析更准。</div>}
        {d.events.map((e: Json) => (
          <div className="signal" key={e.id}>
            <span className="chip small">{e.category === 'state' ? '状态' : e.date?.slice(5)}</span>
            <div>{e.content}</div>
          </div>
        ))}
        {d.joint.sleep?.available && (
          <div className="small muted" style={{ marginTop: 10 }}>
            睡眠需求 {fmtMinutes(d.joint.sleep.sleep_need_min)} · 睡眠负债 {fmtMinutes(d.joint.sleep.sleep_debt_min)}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Dashboard({ status }: { status: Json }) {
  const { data: d, loading, error, setData } = useApi('/api/dashboard')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)

  if (loading) return <div className="loading">正在分析你的 WHOOP 数据…</div>
  if (error) return <div className="empty"><h2>加载失败</h2>{error}</div>
  if (!d?.available) {
    return (
      <div className="empty">
        <h2>还没有数据</h2>
        <p>{d?.reason}</p>
        <Link className="btn btn-primary" to="/settings">去连接 WHOOP 或生成 Demo 数据</Link>
      </div>
    )
  }

  const genAI = async () => {
    setAiLoading(true)
    setAiError(null)
    try {
      const r = await api.post(`/api/reports/daily/${d.date}/ai`)
      setData({ ...d, ...r })
    } catch (e) {
      setAiError((e as Error).message)
    } finally {
      setAiLoading(false)
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">今日身体状态</div>
          <div className="page-sub">你今天和你自己平时相比怎么样、为什么、接下来怎么调整</div>
        </div>
        {status?.user?.is_demo && <span className="chip warn">当前为 Demo 模拟数据</span>}
      </div>
      <Hero d={d} />
      <div className="grid grid-5">
        {d.tiles.map((t: Json) => <MetricTile key={t.metric + t.label} t={t} />)}
      </div>
      {aiError && <div className="banner warn">AI 解读生成失败：{aiError}</div>}
      <div className="grid grid-2">
        <AIAnalysis d={d} onAI={genAI} aiLoading={aiLoading} llmEnabled={!!status?.llm?.enabled} />
        <Signals d={d} />
      </div>
      <div className="grid grid-2">
        <Training t={d.training} />
        <Nutrition n={d.nutrition} />
      </div>
      <Context d={d} />
    </div>
  )
}
