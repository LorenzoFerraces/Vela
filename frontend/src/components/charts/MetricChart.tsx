import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

type MetricChartProps = {
  data: Record<string, unknown>[]
  dataKey: string
  label: string
  color: string
  yAxisLabel: string
  chartType?: 'line' | 'area'
  referenceLine?: { value: number; label: string }
  formatValue?: (value: number) => string
}

export function MetricChart({
  data,
  dataKey,
  label,
  color,
  yAxisLabel,
  chartType = 'line',
  referenceLine,
  formatValue,
}: MetricChartProps) {
  const formatXAxis = (value: string) => {
    try {
      const d = new Date(value)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return String(value)
    }
  }

  const formatTooltipValue = (value: number) =>
    formatValue ? formatValue(value) : value.toFixed(1)

  const ChartComponent = chartType === 'area' ? AreaChart : LineChart

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ChartComponent data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="timestamp"
          tickFormatter={formatXAxis}
          tick={{ fontSize: 12 }}
        />
        <YAxis
          label={{ value: yAxisLabel, angle: -90, position: 'insideLeft', fontSize: 12 }}
          tick={{ fontSize: 12 }}
          tickFormatter={formatValue}
        />
        <Tooltip
          labelFormatter={(label) => new Date(String(label)).toLocaleString()}
          formatter={(value) => [formatTooltipValue(Number(value)), label]}
        />
        {chartType === 'line' ? (
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            dot={false}
            name={label}
          />
        ) : (
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            fill={color}
            fillOpacity={0.15}
            name={label}
          />
        )}
        {referenceLine && (
          <ReferenceLine
            y={referenceLine.value}
            stroke="#ef4444"
            strokeDasharray="4 4"
            label={{ position: 'right', value: referenceLine.label, fontSize: 11 }}
          />
        )}
      </ChartComponent>
    </ResponsiveContainer>
  )
}
