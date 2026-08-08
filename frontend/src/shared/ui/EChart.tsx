import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import type { EChartsOption } from 'echarts'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useId, useRef } from 'react'

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])

export function EChart({ option, label, summary, height = 320 }: { option: EChartsOption; label: string; summary: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const summaryId = useId()

  useEffect(() => {
    if (!ref.current) return
    const instance = echarts.init(ref.current)
    instance.setOption(option)
    const resize = () => instance.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      instance.dispose()
    }
  }, [option])

  return (
    <figure className="chart-card">
      <div ref={ref} role="img" aria-label={label} aria-describedby={summaryId} tabIndex={0} style={{ height }} />
      <figcaption id={summaryId}>{summary}</figcaption>
    </figure>
  )
}
