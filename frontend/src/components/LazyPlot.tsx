import { Suspense, lazy } from 'react';
import { Spin } from 'antd';
import type { PlotParams } from 'react-plotly.js';

const Plot = lazy(() => import('./PlotlyChart'));

export function LazyPlot(props: PlotParams) {
  return (
    <div className="cbw-plot-shell">
      <Suspense fallback={<div className="cbw-plot-loading"><Spin size="large" /></div>}>
        <Plot {...props} />
      </Suspense>
    </div>
  );
}
