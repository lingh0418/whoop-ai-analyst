import { useState } from 'react'
import { fmtMetric, fmtNum, fmtPct, type Json } from '../api'
import { EChart } from '../components/EChart'
import { useApi } from '../components/useApi'

const TABS: { key: string; label: string }[] = [
  { key: 'hrv', label: 'HRV' },
  { key: 'rhr', label: '静息心率' },
  { key: 'recovery', label: 'Recovery' },
  { key: 'sleep_duration', label: '睡眠时长' },
  { key: 'strain', label: 'Strain' },
  { key: 'workout', label: '训练' },
  { key: 'weight', label: '体重' },
]
const MORE = [
  { key: 'sleep_performance', label: '睡眠表现' },
  { key: 'sleep_consistency', label: '睡眠一致性' },
  { key: 'deep_sleep', label: '深睡' },
  { key: 'rem_sleep', label: 'REM' },
  { key: 'sleep_debt', label: '睡眠负债' },
  { key: 'resp_rate', label: '呼吸频率' },
  { key: 'skin_temp', label: '皮肤温度' },
]
const RANGES = [7, 28, 90, 180]
const MINUTE_METRICS = ['sleep_duration', 'deep_sleep', 'rem_sleep', 'sleep_debt', 'workout_minutes']

function axisFmt(metric: string) {
  return (v: number) => (MINUTE_METRICS.includes(metric) ? `${(v / 60).toFixed(1)}h` : `${Math.round(v * 10) / 10}`)
}

function MetricChart({ data, metric }: { data: Json; metric: string }) {
  const pts = data.points as Json[]
  const anomalies = new Map<string, Json>((data.anomalies as Json[]).map((a) => [a.date, a]))
  const unit = data.unit
  return (
    <EChart
      height={340}
      deps={[metric, pts.length, pts[pts.length - 1]?.date]}
      build={(p) => ({
        animation: false,
        grid: { left: 48, right: 16, top: 16, bottom: 30 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line', lineStyle: { color: p.axis } },
          backgroundColor: p.surface,
          borderColor: p.grid,
          textStyle: { color: p.text, fontSize: 12 },
          formatter: (params: Json) => {
            const i = params[0].dataIndex
            const pt = pts[i]
            const an = anomalies.get(pt.date)
            const rows = [
              `<b>${pt.date}</b>`,
              `数值：<b>${fmtMetric(metric, pt.value, unit)}</b>`,
              `7 日均线：${fmtMetric(metric, pt.ma7, unit)}`,
              `28 日基线：${fmtMetric(metric, pt.baseline, unit)}`,
              `偏差：${fmtPct(pt.deviation_pct)}${pt.z !== null ? `（z=${pt.z}）` : ''}`,
            ]
            if (an) rows.push(`<span style="color:${p.critical}">⚠ ${an.message}</span>`)
            return rows.join('<br/>')
          },
        },
        xAxis: {
          type: 'category',
          data: pts.map((x) => x.date.slice(5)),
          axisLine: { lineStyle: { color: p.axis } },
          axisTick: { show: false },
          axisLabel: { color: p.muted, fontSize: 11 },
        },
        yAxis: {
          type: 'value',
          scale: true,
          splitLine: { lineStyle: { color: p.grid } },
          axisLabel: { color: p.muted, fontSize: 11, formatter: axisFmt(metric) },
        },
        series: [
          { name: 'band-low', type: 'line', stack: 'band', data: pts.map((x) => x.band_low), symbol: 'none', lineStyle: { opacity: 0 }, tooltip: { show: false }, silent: true },
          {
            name: 'band', type: 'line', stack: 'band', symbol: 'none', silent: true, lineStyle: { opacity: 0 },
            areaStyle: { color: p.band }, tooltip: { show: false },
            data: pts.map((x) => (x.band_high !== null && x.band_low !== null ? x.band_high - x.band_low : null)),
          },
          { name: '28 日基线', type: 'line', data: pts.map((x) => x.baseline), symbol: 'none', lineStyle: { color: p.baseline, width: 1.5, type: 'dashed' } },
          { name: '7 日均线', type: 'line', data: pts.map((x) => x.ma7), symbol: 'none', lineStyle: { color: p.s2, width: 2 } },
          {
            name: '每日数值', type: 'line', data: pts.map((x) => x.value), symbol: 'circle', symbolSize: pts.length > 60 ? 0 : 5,
            showSymbol: pts.length <= 60, lineStyle: { color: p.s1, width: 2 }, itemStyle: { color: p.s1 }, connectNulls: false,
          },
          {
            name: '异常', type: 'scatter', symbolSize: 11,
            itemStyle: { color: p.critical, borderColor: p.surface, borderWidth: 2 },
            data: pts.map((x) => (anomalies.has(x.date) ? x.value : null)),
          },
        ],
      })}
    />
  )
}

function Stats({ a, metric, unit, trend }: { a: Json; metric: string; unit: string; trend: Json }) {
  if (!a?.available) return null
  const items: [string, string][] = [
    ['最新一天', a.value_text],
    ['近 7 日均值', fmtMetric(metric, a.avg_7d, unit)],
    ['28 日基线', fmtMetric(metric, a.baseline_28d, unit)],
    ['90 日基线', fmtMetric(metric, a.baseline_90d, unit)],
    ['相对 28 日基线', fmtPct(a.deviation_pct_28d)],
    ['z-score', fmtNum(a.z_score_28d, 2)],
    ['90 日个人百分位', a.percentile_90d === null ? '—' : `P${Math.round(a.percentile_90d)}`],
    ['标准差（28 日）', fmtMetric(metric, a.std_28d, unit)],
    ['7 日趋势', `${a.trend_7d.label} ${fmtPct(a.trend_7d.pct_per_week)}/周`],
    ['28 日趋势', `${a.trend_28d.label} ${fmtPct(a.trend_28d.pct_per_week)}/周`],
    ['90 日趋势', `${a.trend_90d.label} ${fmtPct(a.trend_90d.pct_per_week)}/周`],
    ['所选区间趋势', `${{ up: '上升', down: '下降', flat: '平稳' }[trend.direction as string]} ${fmtPct(trend.pct_per_week)}/周`],
    ['连续低于基线', `${a.consecutive_below_baseline} 天`],
    ['连续高于基线', `${a.consecutive_above_baseline} 天`],
    ['波动性', a.volatility ? `${a.volatility}（CV ${fmtPct(a.cv_28d, 1, false)}）` : '—'],
    ['P10 / P90（90 日）', `${fmtMetric(metric, a.p10_90d, unit)} / ${fmtMetric(metric, a.p90_90d, unit)}`],
  ]
  return (
    <div className="stat-grid">
      {items.map(([k, v]) => (
        <div className="stat" key={k}><div className="k">{k}</div><div className="v">{v}</div></div>
      ))}
    </div>
  )
}

function MetricView({ metric, days }: { metric: string; days: number }) {
  const { data, loading, error } = useApi(`/api/trends?metric=${metric}&days=${days}`)
  if (loading) return <div className="loading">加载中…</div>
  if (error || !data) return <div className="empty">{error}</div>
  return (
    <div className="stack">
      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="card-title" style={{ margin: 0 }}>{data.label} · 最近 {days} 天</div>
          <span className="spacer" />
          <div className="legend">
            <span><i className="swatch" style={{ background: 'var(--series-1)' }} />每日数值</span>
            <span><i className="swatch" style={{ background: 'var(--series-2)' }} />7 日均线</span>
            <span><i className="swatch dash" />28 日个人基线</span>
            <span><i className="swatch box" style={{ background: 'var(--band)' }} />基线 ±1 标准差</span>
            <span><i className="dot" style={{ background: 'var(--critical)' }} />异常点</span>
          </div>
        </div>
        <MetricChart data={data} metric={metric} />
      </div>
      <div className="card">
        <div className="card-title">统计 <span className="hint">基线均使用当天之前的窗口（不含当天）</span></div>
        <Stats a={data.analysis} metric={metric} unit={data.unit} trend={data.period_trend} />
      </div>
      {data.anomalies.length > 0 && (
        <div className="card">
          <div className="card-title">区间内异常（{data.anomalies.length}）</div>
          <table className="tbl">
            <thead><tr><th>日期</th><th>类型</th><th>严重度</th><th>说明</th></tr></thead>
            <tbody>
              {[...data.anomalies].reverse().slice(0, 20).map((a: Json, i: number) => (
                <tr key={i}><td>{a.date}</td><td>{a.label}</td><td>{a.severity}</td><td>{a.message}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function WorkoutView({ days }: { days: number }) {
  const strain = useApi(`/api/trends?metric=strain&days=${days}`)
  const w = useApi(`/api/workouts?days=${days}`)
  if (strain.loading || w.loading) return <div className="loading">加载中…</div>
  if (!strain.data || !w.data) return <div className="empty">暂无数据</div>
  const pts = strain.data.points as Json[]
  const byDate = new Map<string, number>()
  for (const it of w.data.items as Json[]) byDate.set(it.date, (byDate.get(it.date) || 0) + it.minutes)
  const zoneTotals = [0, 0, 0, 0, 0, 0]
  for (const it of w.data.items as Json[]) it.zone_minutes.forEach((m: number, i: number) => (zoneTotals[i] += m))
  const totalZone = zoneTotals.reduce((a, b) => a + b, 0) || 1
  return (
    <div className="stack">
      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="card-title" style={{ margin: 0 }}>每日 Strain · 最近 {days} 天</div>
          <span className="spacer" />
          <div className="legend">
            <span><i className="swatch box" style={{ background: 'var(--series-1)' }} />每日 Strain</span>
            <span><i className="swatch dash" />28 日基线</span>
          </div>
        </div>
        <EChart
          height={260}
          deps={[days, pts.length]}
          build={(p) => ({
            animation: false,
            grid: { left: 40, right: 16, top: 16, bottom: 30 },
            tooltip: {
              trigger: 'axis', backgroundColor: p.surface, borderColor: p.grid, textStyle: { color: p.text, fontSize: 12 },
              formatter: (ps: Json) => {
                const pt = pts[ps[0].dataIndex]
                const mins = byDate.get(pt.date)
                return `<b>${pt.date}</b><br/>Strain：<b>${fmtNum(pt.value)}</b><br/>28 日基线：${fmtNum(pt.baseline)}${mins ? `<br/>训练 ${mins} 分钟` : ''}`
              },
            },
            xAxis: { type: 'category', data: pts.map((x) => x.date.slice(5)), axisLine: { lineStyle: { color: p.axis } }, axisTick: { show: false }, axisLabel: { color: p.muted, fontSize: 11 } },
            yAxis: { type: 'value', max: 21, splitLine: { lineStyle: { color: p.grid } }, axisLabel: { color: p.muted, fontSize: 11 } },
            series: [
              { type: 'bar', data: pts.map((x) => x.value), barMaxWidth: 14, itemStyle: { color: p.s1, borderRadius: [4, 4, 0, 0] } },
              { type: 'line', data: pts.map((x) => x.baseline), symbol: 'none', lineStyle: { color: p.baseline, type: 'dashed', width: 1.5 } },
            ],
          })}
        />
      </div>
      <div className="grid grid-3">
        <div className="card">
          <div className="card-title">训练频率</div>
          <div className="stat-grid">
            <div className="stat"><div className="k">训练次数</div><div className="v">{w.data.items.length}</div></div>
            <div className="stat"><div className="k">每周平均</div><div className="v">{((w.data.items.length / days) * 7).toFixed(1)} 次</div></div>
          </div>
        </div>
        <div className="card span-2">
          <div className="card-title">心率区间分布 <span className="hint">区间内全部训练</span></div>
          <table className="tbl">
            <thead><tr>{['Z0', 'Z1', 'Z2', 'Z3', 'Z4', 'Z5'].map((z) => <th key={z}>{z}</th>)}</tr></thead>
            <tbody><tr>{zoneTotals.map((m, i) => <td key={i}>{m} 分钟<br /><span className="muted small">{((m / totalZone) * 100).toFixed(0)}%</span></td>)}</tr></tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <div className="card-title">训练记录</div>
        <table className="tbl">
          <thead><tr><th>日期</th><th>类型</th><th>时长</th><th>Strain</th><th>平均心率</th><th>最大心率</th><th>Z2 / Z3 / Z4+（分钟）</th></tr></thead>
          <tbody>
            {(w.data.items as Json[]).slice(0, 40).map((it) => (
              <tr key={it.id}>
                <td>{it.date}</td><td>{it.sport}</td><td>{it.minutes} 分钟</td><td>{fmtNum(it.strain)}</td>
                <td>{it.avg_hr ?? '—'}</td><td>{it.max_hr ?? '—'}</td>
                <td>{it.zone_minutes[2]} / {it.zone_minutes[3]} / {it.zone_minutes[4] + it.zone_minutes[5]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function Trends() {
  const [metric, setMetric] = useState('hrv')
  const [days, setDays] = useState(28)
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">趋势</div>
          <div className="page-sub">每日数值、7 日均线、28 日个人基线与异常点</div>
        </div>
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r} className={days === r ? 'on' : ''} onClick={() => setDays(r)}>{r}D</button>
          ))}
        </div>
      </div>
      <div className="row">
        <div className="seg">
          {TABS.map((t) => (
            <button key={t.key} className={metric === t.key ? 'on' : ''} onClick={() => setMetric(t.key)}>{t.label}</button>
          ))}
        </div>
        <select className="input" style={{ width: 150 }} value={MORE.some((m) => m.key === metric) ? metric : ''} onChange={(e) => e.target.value && setMetric(e.target.value)}>
          <option value="">更多指标…</option>
          {MORE.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </div>
      {metric === 'workout' ? <WorkoutView days={days} /> : <MetricView key={`${metric}-${days}`} metric={metric} days={days} />}
    </div>
  )
}
