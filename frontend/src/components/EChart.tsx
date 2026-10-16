import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { ComposeOption } from 'echarts/core'
import type { BarSeriesOption, LineSeriesOption, ScatterSeriesOption } from 'echarts/charts'
import type { GridComponentOption, MarkLineComponentOption, TooltipComponentOption } from 'echarts/components'
import { cssVar } from '../api'

echarts.use([LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, MarkLineComponent, SVGRenderer])

export type ChartOption = ComposeOption<
  LineSeriesOption | BarSeriesOption | ScatterSeriesOption | GridComponentOption | TooltipComponentOption | MarkLineComponentOption
>

/** 主题变化（系统深浅色 / 手动切换）时触发重绘 */
export function useThemeVersion(): number {
  const [v, setV] = useState(0)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const bump = () => setV((x) => x + 1)
    mq.addEventListener('change', bump)
    const obs = new MutationObserver(bump)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => {
      mq.removeEventListener('change', bump)
      obs.disconnect()
    }
  }, [])
  return v
}

export type Palette = {
  text: string
  text2: string
  muted: string
  grid: string
  axis: string
  surface: string
  s1: string
  s2: string
  s3: string
  baseline: string
  band: string
  good: string
  warning: string
  critical: string
}

export function palette(): Palette {
  return {
    text: cssVar('--text'),
    text2: cssVar('--text-2'),
    muted: cssVar('--muted'),
    grid: cssVar('--grid'),
    axis: cssVar('--axis'),
    surface: cssVar('--surface'),
    s1: cssVar('--series-1'),
    s2: cssVar('--series-2'),
    s3: cssVar('--series-3'),
    baseline: cssVar('--baseline'),
    band: cssVar('--band'),
    good: cssVar('--good'),
    warning: cssVar('--warning'),
    critical: cssVar('--critical'),
  }
}

export function EChart({ build, height = 280, deps = [] }: { build: (p: Palette) => ChartOption; height?: number; deps?: unknown[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const theme = useThemeVersion()

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current, undefined, { renderer: 'svg' })
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.current?.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(build(palette()), true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, ...deps])

  return <div ref={ref} style={{ height, width: '100%' }} />
}
