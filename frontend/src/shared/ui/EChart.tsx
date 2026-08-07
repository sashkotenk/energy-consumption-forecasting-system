import { useEffect, useId, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

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
