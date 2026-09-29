import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import type { Latency } from '../api/types'
import { formatClock } from '../lib/format'

interface TooltipProps {
  active?: boolean
  payload?: { payload: { ts_ms: number; total_ms: number } }[]
}

function ChartTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs shadow-lg">
      <span className="font-medium text-zinc-100">{Math.round(point.total_ms)} ms</span>
      <span className="ml-2 text-zinc-500">{formatClock(point.ts_ms)}</span>
    </div>
  )
}

export default function LatencyChart({ data }: { data: Latency['recent'] }) {
  if (data.length < 2) {
    return (
      <div className="flex h-20 items-center justify-center text-xs text-zinc-600">
        Not enough samples yet
      </div>
    )
  }
  return (
    <div className="h-20" role="img" aria-label="Recent copy latency">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <YAxis hide domain={[0, 'dataMax']} />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#3f3f46' }} />
          <Line
            type="monotone"
            dataKey="total_ms"
            stroke="#818cf8"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
