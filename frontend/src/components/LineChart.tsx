import type { CSSProperties } from 'react';

type ChartValue = number | string | null | undefined;

interface LineSeries {
  key: string;
  label: string;
  color: string;
  dashed?: boolean;
}

interface LineChartProps<T extends object> {
  rows: T[];
  xKey: keyof T;
  series: LineSeries[];
  height?: number;
  valueSuffix?: string;
}

export function LineChart<T extends object>({
  rows,
  xKey,
  series,
  height = 260,
  valueSuffix = '',
}: LineChartProps<T>) {
  if (!rows.length || !series.length) {
    return <div className="empty-state compact">当前没有可绘制的数据。</div>;
  }

  const width = 960;
  const padding = 24;
  const innerHeight = height - padding * 2;
  const innerWidth = width - padding * 2;
  const numericValues = rows.flatMap((row) =>
    series
      .map((entry) => (row as Record<string, ChartValue>)[entry.key])
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value)),
  );

  if (!numericValues.length) {
    return <div className="empty-state compact">当前序列没有数值点。</div>;
  }

  const minValue = Math.min(...numericValues);
  const maxValue = Math.max(...numericValues);
  const domainPadding = minValue === maxValue ? Math.max(Math.abs(minValue) * 0.02, 1) : (maxValue - minValue) * 0.08;
  const domainMin = minValue - domainPadding;
  const domainMax = maxValue + domainPadding;

  const x = (index: number) => {
    if (rows.length === 1) {
      return width / 2;
    }
    return padding + (index / (rows.length - 1)) * innerWidth;
  };

  const y = (value: number) => padding + ((domainMax - value) / (domainMax - domainMin)) * innerHeight;

  return (
    <div className="chart-shell">
      <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="line chart">
        {[0, 0.5, 1].map((ratio) => {
          const lineY = padding + ratio * innerHeight;
          return (
            <line
              key={ratio}
              x1={padding}
              x2={width - padding}
              y1={lineY}
              y2={lineY}
              className="chart-grid"
            />
          );
        })}

        {series.map((entry) => {
          const points = rows
            .map((row, index) => {
              const value = (row as Record<string, ChartValue>)[entry.key];
              if (typeof value !== 'number' || !Number.isFinite(value)) {
                return null;
              }
              return `${x(index)},${y(value)}`;
            })
            .filter((point): point is string => point !== null);

          if (!points.length) {
            return null;
          }

          return (
            <polyline
              key={entry.key}
              fill="none"
              points={points.join(' ')}
              className="chart-path"
              style={
                {
                  '--chart-color': entry.color,
                  strokeDasharray: entry.dashed ? '10 8' : undefined,
                } as CSSProperties
              }
            />
          );
        })}
      </svg>

      <div className="chart-meta">
        <div className="chart-axis-label">
          <span>{String(rows[0][xKey])}</span>
          <span>{String(rows[rows.length - 1][xKey])}</span>
        </div>
        <div className="chart-axis-label">
          <span>
            {domainMax.toFixed(2)}
            {valueSuffix}
          </span>
          <span>
            {domainMin.toFixed(2)}
            {valueSuffix}
          </span>
        </div>
      </div>
    </div>
  );
}
