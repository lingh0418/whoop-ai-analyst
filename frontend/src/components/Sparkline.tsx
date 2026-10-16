import { EChart } from './EChart'

export function Sparkline({ values, baseline, color }: { values: (number | null)[]; baseline?: number | null; color?: string }) {
  return (
    <div className="spark">
      <EChart
        height={34}
        deps={[values.join(','), baseline, color]}
        build={(p) => ({
          animation: false,
          grid: { left: 2, right: 2, top: 4, bottom: 4 },
          xAxis: { type: 'category', show: false, data: values.map((_, i) => i) },
          yAxis: { type: 'value', show: false, scale: true },
          series: [
            {
              type: 'line',
              data: values,
              symbol: 'none',
              smooth: false,
              lineStyle: { width: 2, color: color || p.s1 },
              markLine: baseline
                ? { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: p.baseline, type: 'dashed', width: 1 }, data: [{ yAxis: baseline }] }
                : undefined,
            },
          ],
        })}
      />
    </div>
  )
}
