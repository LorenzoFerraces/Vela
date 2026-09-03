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

type ChartSeries = { dataKey: string; label: string; color: string }

type MetricChartProps = {
  data: Record<string, unknown>[]
  dataKey?: string
  label: string
  color?: string
  yAxisLabel: string
  chartType?: 'line' | 'area'
  referenceLine?: { value: number; label: string }
  formatValue?: (value: number) => string
  series?: ChartSeries[]
}

// Recharts props cannot read CSS variables; keep these hex values in sync
// with the dark theme tokens in index.css (grid: --border, ticks/tooltip
// text: --text-muted, tooltip background: --bg-deep, tooltip border:
// --border, reference line: --error).
const CHART_GRID_STROKE = '#5a4b7a'
const CHART_TEXT = '#9a8fb8'
const CHART_TOOLTIP_BG = '#120e1e'
const CHART_REFERENCE_STROKE = '#ef4444'

export function MetricChart({
  data,
  dataKey,
  label,
  color,
  yAxisLabel,
  chartType = 'line',
  referenceLine,
  formatValue,
  series,
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

  const singleSeries =
    dataKey !== undefined && color !== undefined ? (
      chartType === 'line' ? (
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
      )
    ) : null

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ChartComponent data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
        <XAxis
          dataKey="timestamp"
          tickFormatter={formatXAxis}
          tick={{ fontSize: 12, fill: CHART_TEXT }}
        />
        <YAxis
          label={{ value: yAxisLabel, angle: -90, position: 'insideLeft', fontSize: 12 }}
          tick={{ fontSize: 12, fill: CHART_TEXT }}
          tickFormatter={formatValue}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: CHART_TOOLTIP_BG,
            border: `1px solid ${CHART_GRID_STROKE}`,
            color: CHART_TEXT,
          }}
          labelFormatter={(label) => new Date(String(label)).toLocaleString()}
          formatter={(value, name) => [formatTooltipValue(Number(value)), name]}
        />
        {series ? (
          series.map((s) => (
            <Line
              key={s.dataKey}
              type="monotone"
              dataKey={s.dataKey}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              name={s.label}
            />
          ))
        ) : (
          singleSeries
        )}
        {referenceLine && (
          <ReferenceLine
            y={referenceLine.value}
            stroke={CHART_REFERENCE_STROKE}
            strokeDasharray="4 4"
            label={{ position: 'right', value: referenceLine.label, fontSize: 11 }}
          />
        )}
      </ChartComponent>
    </ResponsiveContainer>
  )
}
