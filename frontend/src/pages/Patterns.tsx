import { useState } from 'react'
import { CONFIDENCE_LABEL, fmtP, type Json } from '../api'
import { EChart } from '../components/EChart'
import { useApi } from '../components/useApi'

const CATEGORY: Record<string, string> = { sleep: '睡眠', strain: '训练负荷', lifestyle: '生活事件', weekday: '星期规律' }

function effectText(p: Json): string {
  if (p.effect_unit === 'pct') return `${p.effect > 0 ? '+' : ''}${(p.effect * 100).toFixed(1)}%`
  if (p.effect_unit === 'probability') return `${p.effect > 0 ? '+' : ''}${(p.effect * 100).toFixed(0)} 个百分点（概率）`
  return `${p.effect > 0 ? '+' : ''}${p.effect.toFixed(1)} 个百分点`
}

export default function Patterns() {
  const pats = useApi<Json[]>('/api/patterns')
  const [days, setDays] = useState(120)
  const drivers = useApi(`/api/drivers?days=${days}`)
  const anomalies = useApi<Json[]>('/api/anomalies?days=30')

  const factors = (drivers.data?.factors ?? []) as Json[]
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">个人规律</div>
          <div className="page-sub">从你自己的长期数据中学到的规律 —— 全部是相关趋势，不代表因果</div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">已学到的规律 <span className="hint">条件组 vs 其他日子，Welch t 检验 / Fisher 精确检验</span></div>
        {pats.loading && <div className="loading">加载中…</div>}
        {pats.data?.length === 0 && <div className="muted">数据还不够（通常需要 30 天以上），暂时没有发现稳定的个人规律。</div>}
        {(pats.data ?? []).map((p) => (
          <div className="pattern" key={p.key}>
            <div className="row">
              <span className="chip">{CATEGORY[p.category] ?? p.category}</span>
              <span className={`chip ${p.confidence === 'high' ? 'good' : p.confidence === 'medium' ? 'info' : ''}`}>置信度 {CONFIDENCE_LABEL[p.confidence]}</span>
              <span className="pattern-title">{p.title}</span>
            </div>
            <div className="small muted" style={{ marginTop: 4 }}>
              条件：{p.condition} · 效应 {effectText(p)} · 样本 {p.sample_size} 天（对照 {p.comparison_size} 天）· {fmtP(p.p_value)} · 首次发现 {p.first_detected}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="row" style={{ marginBottom: 8 }}>
            <div className="card-title" style={{ margin: 0 }}>什么情况下 Recovery 通常最好</div>
            <span className="spacer" />
            <div className="seg">
              {[60, 120, 180].map((d) => <button key={d} className={days === d ? 'on' : ''} onClick={() => setDays(d)}>{d}天</button>)}
            </div>
          </div>
          {drivers.data?.summary && <p className="text-2" style={{ marginTop: 0 }}>{drivers.data.summary}</p>}
          {factors.length > 0 && (
            <EChart
              height={40 + factors.length * 34}
              deps={[days, factors.length]}
              build={(p) => ({
                animation: false,
                grid: { left: 130, right: 50, top: 8, bottom: 24 },
                tooltip: {
                  trigger: 'item', backgroundColor: p.surface, borderColor: p.grid, textStyle: { color: p.text, fontSize: 12 },
                  formatter: (x: Json) => {
                    const f = factors[factors.length - 1 - x.dataIndex]
                    return `<b>${f.label}</b><br/>Spearman ρ = ${f.spearman_rho}（${fmtP(f.p_value)}）<br/>恢复最好的 25%：${f.top_text}<br/>恢复最差的 25%：${f.bottom_text}`
                  },
                },
                xAxis: { type: 'value', min: -1, max: 1, splitLine: { lineStyle: { color: p.grid } }, axisLabel: { color: p.muted } },
                yAxis: { type: 'category', data: [...factors].reverse().map((f) => f.label), axisTick: { show: false }, axisLine: { lineStyle: { color: p.axis } }, axisLabel: { color: p.text2 } },
                series: [{
                  type: 'bar', barMaxWidth: 16,
                  label: { show: true, position: 'right', color: p.text2, formatter: (x: Json) => (x.value as number).toFixed(2) },
                  data: [...factors].reverse().map((f) => ({
                    value: f.spearman_rho,
                    itemStyle: { color: f.significant ? (f.spearman_rho > 0 ? p.s1 : p.s2) : p.axis, borderRadius: f.spearman_rho > 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] },
                  })),
                }],
              })}
            />
          )}
          <div className="legend" style={{ marginTop: 6 }}>
            <span><i className="swatch box" style={{ background: 'var(--series-1)' }} />正相关（显著）</span>
            <span><i className="swatch box" style={{ background: 'var(--series-2)' }} />负相关（显著）</span>
            <span><i className="swatch box" style={{ background: 'var(--axis)' }} />不显著</span>
          </div>
        </div>
        <div className="card">
          <div className="card-title">最近 30 天的异常 <span className="hint">阈值可在设置中调整</span></div>
          <table className="tbl">
            <thead><tr><th>日期</th><th>类型</th><th>严重度</th><th>说明</th></tr></thead>
            <tbody>
              {(anomalies.data ?? []).slice(0, 25).map((a, i) => (
                <tr key={i}>
                  <td style={{ whiteSpace: 'nowrap' }}>{a.date.slice(5)}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{a.label}</td>
                  <td><span className={`chip ${a.severity === 'high' ? 'bad' : 'warn'}`}>{a.severity}</span></td>
                  <td className="small">{a.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
