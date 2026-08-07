import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

export function EChart({ option, label, summary, height = 320 }: { option: EChartsOption; label: string; summary: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)

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
      <div ref={ref} role="img" aria-label={label} style={{ height }} />
      <figcaption>{summary}</figcaption>
    </figure>
  )
}
