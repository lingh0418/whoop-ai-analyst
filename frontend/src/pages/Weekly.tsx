import { useEffect, useState } from 'react'
import { api, CONFIDENCE_LABEL, fmtMinutes, fmtNum, fmtPct, WEEKDAYS, type Json } from '../api'
import { EChart } from '../components/EChart'
import { Markdown } from '../components/Markdown'
import { useApi } from '../components/useApi'

function Compare({ label, cur, prev, change, unit, fmt, changeFmt, betterWhen }: {
  label: string; cur: number | null; prev: number | null; change: number | null; unit?: string
  fmt?: (v: number | null) => string; changeFmt?: (v: number | null) => string; betterWhen: 'up' | 'down' | 'none'
}) {
  const f = fmt ?? ((v: number | null) => (v === null ? '—' : `${fmtNum(v)}${unit ?? ''}`))
  const cf = changeFmt ?? f
  let tone = 'neutral'
  if (change !== null && betterWhen !== 'none' && Math.abs(change) > 0.01) {
    tone = (change > 0) === (betterWhen === 'up') ? 'good' : 'bad'
  }
  return (
    <div className="card tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{f(cur)}</div>
      <div className={`tile-delta ${tone}`}>
        {change === null ? '—' : `${change > 0 ? '↑' : change < 0 ? '↓' : '→'} ${cf(Math.abs(change)).replace(/^-/, '')}`}
        <span className="muted small" style={{ fontWeight: 400 }}>vs 上周 {f(prev)}</span>
      </div>
    </div>
  )
}

function WeekReport({ ws, llm }: { ws: string; llm: boolean }) {
  const { data: w, loading, setData } = useApi(`/api/reports/weekly/${ws}`)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (loading) return <div className="loading">生成周报中…</div>
  if (!w?.available) return <div className="empty">{w?.reason ?? '没有数据'}</div>

  const genAI = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.post(`/api/reports/weekly/${ws}/ai`)
      setData({ ...w, ...r })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const daily = w.daily as Json[]
  return (
    <div className="stack">
      <div className="grid grid-5">
        <Compare label="Recovery 周均" cur={w.recovery.this_week} prev={w.recovery.last_week} change={w.recovery.change} unit="%" betterWhen="up" fmt={(v) => (v === null ? '—' : `${Math.round(v)}%`)} changeFmt={(v) => (v === null ? '—' : `${Math.round(v)} 个百分点`)} />
        <Compare label="HRV 周均" cur={w.hrv.this_week} prev={w.hrv.last_week} change={w.hrv.change} unit=" ms" betterWhen="up" />
        <Compare label="静息心率周均" cur={w.rhr.this_week} prev={w.rhr.last_week} change={w.rhr.change} unit=" bpm" betterWhen="down" />
        <Compare label="平均睡眠" cur={w.sleep.this_week} prev={w.sleep.last_week} change={w.sleep.change} betterWhen="up" fmt={(v) => fmtMinutes(v)} />
        <Compare label="平均 Strain" cur={w.strain.this_week} prev={w.strain.last_week} change={w.strain.change} betterWhen="none" />
      </div>
      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">
            本周总结
            <span className="spacer" />
            {llm && <button className="btn btn-sm" onClick={genAI} disabled={busy}>{busy ? '生成中…' : w.ai_summary ? '重新生成 AI 总结' : '生成 AI 总结'}</button>}
          </div>
          {err && <div className="banner warn">{err}</div>}
          {w.ai_summary && <p style={{ marginTop: 0 }}>{w.ai_summary}</p>}
          <Markdown text={w.narrative} />
        </div>
        <div className="stack">
          <div className="card">
            <div className="card-title">每日 Recovery</div>
            <EChart
              height={190}
              deps={[ws]}
              build={(p) => ({
                animation: false,
                grid: { left: 36, right: 10, top: 10, bottom: 26 },
                tooltip: {
                  trigger: 'axis', backgroundColor: p.surface, borderColor: p.grid, textStyle: { color: p.text, fontSize: 12 },
                  formatter: (ps: Json) => {
                    const d = daily[ps[0].dataIndex]
                    return `<b>${d.date}</b><br/>Recovery ${d.recovery ?? '—'}%<br/>HRV ${d.hrv ?? '—'} ms · RHR ${d.rhr ?? '—'}<br/>睡眠 ${fmtMinutes(d.sleep)} · Strain ${d.strain ?? '—'}`
                  },
                },
                xAxis: { type: 'category', data: daily.map((d) => WEEKDAYS[(new Date(d.date).getDay() + 6) % 7]), axisTick: { show: false }, axisLine: { lineStyle: { color: p.axis } }, axisLabel: { color: p.muted } },
                yAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: p.grid } }, axisLabel: { color: p.muted } },
                series: [{
                  type: 'bar', barMaxWidth: 28,
                  data: daily.map((d) => ({
                    value: d.recovery,
                    itemStyle: { color: d.recovery >= 67 ? p.good : d.recovery >= 34 ? p.warning : p.critical, borderRadius: [4, 4, 0, 0] },
                  })),
                }],
              })}
            />
            <div className="legend" style={{ marginTop: 4 }}>
              <span><i className="swatch box" style={{ background: 'var(--good)' }} />≥67% 绿</span>
              <span><i className="swatch box" style={{ background: 'var(--warning)' }} />34–66% 黄</span>
              <span><i className="swatch box" style={{ background: 'var(--critical)' }} />≤33% 红</span>
            </div>
          </div>
          <div className="card">
            <div className="card-title">本周状态分布</div>
            <div className="row">
              {w.state_distribution.map((s: Json) => <span key={s.state} className="chip">{s.label} · {s.days} 天</span>)}
            </div>
            <div className="small muted" style={{ marginTop: 10 }}>
              HRV 相对本周之前 28 日基线：{fmtPct(w.hrv.vs_baseline_pct)} · 睡眠一致性 {w.sleep.consistency ?? '—'}% · 训练 {w.strain.workouts} 次（上周 {w.strain.workouts_last_week} 次）
            </div>
            {w.anomalies.length > 0 && (
              <div className="row" style={{ marginTop: 10 }}>
                {w.anomalies.map((a: Json) => <span key={a.label} className="chip warn">⚠ {a.label} × {a.count}</span>)}
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-title">本周新发现的个人规律</div>
            {w.new_patterns.length === 0 ? <div className="muted small">本周没有新规律。</div> : w.new_patterns.map((p: Json) => (
              <div className="pattern" key={p.key}>
                <div>{p.title}</div>
                <div className="small muted">样本 {p.sample_size} 天 · 置信度 {CONFIDENCE_LABEL[p.confidence]}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Weekly({ status }: { status: Json }) {
  const { data } = useApi<{ weeks: Json[] }>('/api/reports/weekly')
  const [ws, setWs] = useState<string | null>(null)
  useEffect(() => {
    if (!ws && data?.weeks?.length) setWs(data.weeks[0].week_start)
  }, [data, ws])
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">WHOOP 周报</div>
          <div className="page-sub">本周 vs 上周 vs 个人基线</div>
        </div>
        <select className="input" style={{ width: 260 }} value={ws ?? ''} onChange={(e) => setWs(e.target.value)}>
          {(data?.weeks ?? []).map((w) => (
            <option key={w.week_start} value={w.week_start}>{w.week_start} ~ {w.week_end}{w.in_progress ? '（进行中）' : ''}</option>
          ))}
        </select>
      </div>
      {ws && <WeekReport key={ws} ws={ws} llm={!!status?.llm?.enabled} />}
    </div>
  )
}
