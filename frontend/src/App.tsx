import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  ConfigProvider,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Layout,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
  theme,
} from 'antd';
import { DataTable } from './components/DataTable';
import { LazyPlot } from './components/LazyPlot';
import { loadDatasets, loadOverview, loadParameters, loadRunDetail, loadRuns, postIngest, postRunEma } from './lib/api';
import { formatDateRange, formatDateTime, formatNumber, formatPct, shortRunId } from './lib/format';
import type {
  DatasetSnapshotView,
  ParameterLabRow,
  RunAnalysisView,
  RunSummaryView,
  SensitivityRow,
  WorkspaceOverview,
  WorkspaceParameterLab,
  WorkspaceSource,
} from './types';

const { Header, Content } = Layout;
const { Title, Paragraph, Text } = Typography;

type TabId = 'execution' | 'overview' | 'analysis' | 'parameters';

interface UrlState {
  tab: TabId;
  run: string;
  compare: string[];
  overviewQuery: string;
  parameterQuery: string;
}

const TAB_OPTIONS = [
  { label: '执行台', value: 'execution' },
  { label: '运行总览', value: 'overview' },
  { label: '单次分析', value: 'analysis' },
  { label: '参数实验', value: 'parameters' },
] satisfies Array<{ label: string; value: TabId }>;

function isTabId(value: string | null): value is TabId {
  return value === 'execution' || value === 'overview' || value === 'analysis' || value === 'parameters';
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function readUrlState(): UrlState {
  const params = new URLSearchParams(window.location.search);
  const tabParam = params.get('tab');
  return {
    tab: isTabId(tabParam) ? tabParam : 'overview',
    run: params.get('run') ?? '',
    compare: uniqueStrings((params.get('compare') ?? '').split(',')),
    overviewQuery: params.get('overviewQuery') ?? '',
    parameterQuery: params.get('parameterQuery') ?? '',
  };
}

function writeUrlState(state: UrlState): void {
  const params = new URLSearchParams();
  if (state.tab !== 'overview') {
    params.set('tab', state.tab);
  }
  if (state.run) {
    params.set('run', state.run);
  }
  if (state.compare.length) {
    params.set('compare', state.compare.join(','));
  }
  if (state.overviewQuery) {
    params.set('overviewQuery', state.overviewQuery);
  }
  if (state.parameterQuery) {
    params.set('parameterQuery', state.parameterQuery);
  }
  const nextSearch = params.toString();
  const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ''}${window.location.hash}`;
  const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextUrl !== currentUrl) {
    window.history.replaceState(null, '', nextUrl);
  }
}

function WorkspaceShell() {
  const initialState = readUrlState();
  const { message } = AntdApp.useApp();
  const [source, setSource] = useState<WorkspaceSource | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<DatasetSnapshotView[]>([]);
  const [runs, setRuns] = useState<RunSummaryView[]>([]);
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [parameterLab, setParameterLab] = useState<WorkspaceParameterLab | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunAnalysisView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shellLoading, setShellLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>(initialState.tab);
  const [selectedRunId, setSelectedRunId] = useState<string>(initialState.run);
  const [compareRunIds, setCompareRunIds] = useState<string[]>(initialState.compare);
  const [overviewQuery, setOverviewQuery] = useState(initialState.overviewQuery);
  const [parameterQuery, setParameterQuery] = useState(initialState.parameterQuery);
  const [lastActionResult, setLastActionResult] = useState('');
  const [submitting, setSubmitting] = useState<'ingest' | 'run' | null>(null);
  const [ingestForm] = Form.useForm();
  const [runForm] = Form.useForm();
  const deferredOverviewQuery = useDeferredValue(overviewQuery);
  const deferredParameterQuery = useDeferredValue(parameterQuery);

  function applyPayloadMeta(payload: { generated_at: string; source: WorkspaceSource }) {
    setGeneratedAt(payload.generated_at);
    setSource(payload.source);
  }

  function invalidateDerivedData() {
    setOverview(null);
    setParameterLab(null);
    setSelectedRun(null);
  }

  async function refreshShell() {
    setShellLoading(true);
    try {
      const [datasetsPayload, runsPayload] = await Promise.all([loadDatasets(), loadRuns()]);
      setDatasets(datasetsPayload.datasets);
      setRuns(runsPayload.runs);
      applyPayloadMeta(runsPayload);
      if (!runForm.getFieldValue('snapshot_id') && datasetsPayload.datasets[0]?.dataset_snapshot_id) {
        runForm.setFieldValue('snapshot_id', datasetsPayload.datasets[0].dataset_snapshot_id);
      }
      setError(null);
    } catch (loadError: unknown) {
      setError(loadError instanceof Error ? loadError.message : '工作台加载失败');
    } finally {
      setShellLoading(false);
    }
  }

  useEffect(() => {
    void refreshShell();
  }, []);

  useEffect(() => {
    const nextState = readUrlState();
    const handlePopState = () => {
      const state = readUrlState();
      setActiveTab(state.tab);
      setSelectedRunId(state.run);
      setCompareRunIds(state.compare);
      setOverviewQuery(state.overviewQuery);
      setParameterQuery(state.parameterQuery);
    };
    setActiveTab(nextState.tab);
    setSelectedRunId(nextState.run);
    setCompareRunIds(nextState.compare);
    setOverviewQuery(nextState.overviewQuery);
    setParameterQuery(nextState.parameterQuery);
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    writeUrlState({
      tab: activeTab,
      run: selectedRunId,
      compare: compareRunIds,
      overviewQuery,
      parameterQuery,
    });
  }, [activeTab, selectedRunId, compareRunIds, overviewQuery, parameterQuery]);

  useEffect(() => {
    if (!runs.length) {
      if (selectedRunId) {
        setSelectedRunId('');
      }
      setSelectedRun(null);
      return;
    }
    if (!runs.some((entry) => entry.run_id === selectedRunId)) {
      setSelectedRunId(runs[0].run_id);
    }
  }, [runs, selectedRunId]);

  useEffect(() => {
    if (!overview) {
      return;
    }
    const availableRunIds = new Set(overview.summaries.map((entry) => entry.run_id));
    const validRunIds = compareRunIds.filter((runId) => availableRunIds.has(runId));
    if (!validRunIds.length && overview.summaries.length) {
      setCompareRunIds(overview.summaries.slice(0, 3).map((entry) => entry.run_id));
      return;
    }
    if (validRunIds.length !== compareRunIds.length) {
      setCompareRunIds(validRunIds);
    }
  }, [overview, compareRunIds]);

  useEffect(() => {
    let cancelled = false;

    async function loadActivePane() {
      try {
        if (activeTab === 'overview' && overview === null) {
          setSectionLoading(true);
          const payload = await loadOverview();
          if (cancelled) {
            return;
          }
          applyPayloadMeta(payload);
          setOverview(payload.overview);
          setError(null);
          return;
        }

        if (activeTab === 'analysis') {
          if (!selectedRunId) {
            setSelectedRun(null);
            return;
          }
          if (selectedRun?.run_id === selectedRunId) {
            return;
          }
          setSectionLoading(true);
          const payload = await loadRunDetail(selectedRunId);
          if (cancelled) {
            return;
          }
          applyPayloadMeta(payload);
          setSelectedRun(payload.run);
          setError(null);
          return;
        }

        if (activeTab === 'parameters' && parameterLab === null) {
          setSectionLoading(true);
          const payload = await loadParameters();
          if (cancelled) {
            return;
          }
          applyPayloadMeta(payload);
          setParameterLab(payload.parameter_lab);
          setError(null);
        }
      } catch (loadError: unknown) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '工作台加载失败');
        }
      } finally {
        if (!cancelled) {
          setSectionLoading(false);
        }
      }
    }

    void loadActivePane();
    return () => {
      cancelled = true;
    };
  }, [activeTab, overview, parameterLab, selectedRun, selectedRunId]);

  async function handleRefresh() {
    invalidateDerivedData();
    await refreshShell();
  }

  async function handleIngest(values: Record<string, unknown>) {
    setSubmitting('ingest');
    try {
      const result = await postIngest(values);
      const snapshotId = String(result.dataset_snapshot_id ?? '');
      setLastActionResult(`导入完成：${snapshotId}`);
      message.success(`导入完成：${snapshotId}`);
      invalidateDerivedData();
      await refreshShell();
      if (snapshotId) {
        runForm.setFieldValue('snapshot_id', snapshotId);
      }
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '导入失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setSubmitting(null);
    }
  }

  async function handleRun(values: Record<string, unknown>) {
    setSubmitting('run');
    try {
      const result = await postRunEma({
        ...values,
        benchmark: 'buy_and_hold',
      });
      const runId = String(result.run_id ?? '');
      setLastActionResult(`回测完成：${runId}`);
      message.success(`回测完成：${runId}`);
      invalidateDerivedData();
      await refreshShell();
      if (runId) {
        setSelectedRunId(runId);
        setActiveTab('analysis');
      }
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '回测失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setSubmitting(null);
    }
  }

  const filteredSummaries = useMemo(() => {
    const rows = overview?.summaries ?? [];
    const query = deferredOverviewQuery.trim().toLowerCase();
    if (!query) {
      return rows;
    }
    return rows.filter((row) => (
      [row.run_id, row.dataset_snapshot_id, row.symbol, row.strategy_name].join(' ').toLowerCase().includes(query)
    ));
  }, [overview, deferredOverviewQuery]);

  const filteredParameterRows = useMemo(() => {
    const rows = parameterLab?.rows ?? [];
    const query = deferredParameterQuery.trim().toLowerCase();
    if (!query) {
      return rows;
    }
    return rows.filter((row) => (
      [row.run_id, row.dataset_snapshot_id, row.symbol, row.strategy_name].join(' ').toLowerCase().includes(query)
    ));
  }, [parameterLab, deferredParameterQuery]);

  const overviewStats = buildOverviewStats(filteredSummaries);
  const loading = shellLoading || sectionLoading;
  const datasetCount = source?.dataset_count ?? datasets.length;
  const runCount = source?.run_count ?? runs.length;

  return (
    <Layout className="cbw-app">
      <Header className="cbw-header">
        <div>
          <Text className="cbw-kicker">React UI replacing Streamlit page layer</Text>
          <Title level={2} className="cbw-title">加密回测研究工作台</Title>
          <Paragraph className="cbw-subtitle">
            页面层拆成可控的总览、单次分析、参数实验和执行台，保持桌面与大屏布局稳定，后端继续复用 Python engine / storage / workflow。
          </Paragraph>
        </div>
        <Space direction="vertical" align="end" size={4}>
          <Text type="secondary">{generatedAt ? `最近刷新 ${formatDateTime(generatedAt)}` : '正在加载工作台'}</Text>
          <Button onClick={() => void handleRefresh()}>刷新 Workspace</Button>
        </Space>
      </Header>

      <Content className="cbw-content">
        <Card className="cbw-toolbar-card">
          <Flex justify="space-between" align="center" gap={16} wrap="wrap">
            <Segmented<TabId>
              className="cbw-tab-switcher"
              options={TAB_OPTIONS}
              size="large"
              value={activeTab}
              onChange={(value) => setActiveTab(value)}
            />
            <Space size="large" wrap>
              <Statistic title="Datasets" value={datasetCount} />
              <Statistic title="Runs" value={runCount} />
            </Space>
          </Flex>
        </Card>

        {lastActionResult ? (
          <Alert className="cbw-alert" type="info" showIcon message={lastActionResult} />
        ) : null}
        {error ? (
          <Alert className="cbw-alert" type="error" showIcon message="工作台加载失败" description={error} />
        ) : null}

        <Spin spinning={loading}>
          {activeTab === 'execution' && (
            <ExecutionView
              datasets={datasets}
              ingestForm={ingestForm}
              runForm={runForm}
              submitting={submitting}
              onIngest={handleIngest}
              onRun={handleRun}
            />
          )}
          {activeTab === 'overview' && overview && (
            <OverviewView
              overview={overview}
              filteredSummaries={filteredSummaries}
              compareRunIds={compareRunIds}
              setCompareRunIds={setCompareRunIds}
              overviewQuery={overviewQuery}
              setOverviewQuery={setOverviewQuery}
              overviewStats={overviewStats}
            />
          )}
          {activeTab === 'analysis' && (
            <AnalysisView
              runs={runs}
              selectedRun={selectedRun}
              selectedRunId={selectedRunId}
              setSelectedRunId={setSelectedRunId}
            />
          )}
          {activeTab === 'parameters' && parameterLab && (
            <ParametersView
              rows={filteredParameterRows}
              fastRows={parameterLab.fast_period_total_return}
              slowRows={parameterLab.slow_period_total_return}
              parameterQuery={parameterQuery}
              setParameterQuery={setParameterQuery}
            />
          )}
        </Spin>
      </Content>
    </Layout>
  );
}

function ExecutionView({
  datasets,
  ingestForm,
  runForm,
  submitting,
  onIngest,
  onRun,
}: {
  datasets: DatasetSnapshotView[];
  ingestForm: ReturnType<typeof Form.useForm>[0];
  runForm: ReturnType<typeof Form.useForm>[0];
  submitting: 'ingest' | 'run' | null;
  onIngest: (values: Record<string, unknown>) => Promise<void>;
  onRun: (values: Record<string, unknown>) => Promise<void>;
}) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={12}>
        <Card title="导入数据集" extra={<Tag color="blue">导入接口</Tag>}>
          <Form
            form={ingestForm}
            layout="vertical"
            initialValues={{
              exchange: 'binanceusdm',
              symbol: 'BTC/USDT:USDT',
              timeframe: '1h',
              since: '2024-01-01T00:00:00+00:00',
              until: '2024-01-03T00:00:00+00:00',
              market_type: 'linear_usdt_perpetual',
              price_type: 'last',
              limit: 1000,
            }}
            onFinish={(values) => void onIngest(values as Record<string, unknown>)}
          >
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="exchange" label="交易所" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="timeframe" label="周期" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="symbol" label="标的" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="since" label="开始时间 ISO8601" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="until" label="结束时间 ISO8601">
                  <Input />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="market_type" label="市场类型">
                  <Select options={[{ label: 'linear_usdt_perpetual', value: 'linear_usdt_perpetual' }]} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="price_type" label="价格类型">
                  <Select options={[{ label: 'last', value: 'last' }]} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="limit" label="请求条数上限">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={submitting === 'ingest'}>
              导入数据集
            </Button>
          </Form>
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="运行 EMA 回测" extra={<Tag color="green">运行接口</Tag>}>
          <Form
            form={runForm}
            layout="vertical"
            initialValues={{
              run_id: `run-${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}`,
              fast_period: 2,
              slow_period: 3,
              qty_policy_ref: 'fixed_1',
              qty: 0.01,
              initial_cash: 10000,
              leverage: 1,
              fee_rate: 0,
              slippage_bps: 0,
              min_notional: 0,
            }}
            onFinish={(values) => void onRun(values as Record<string, unknown>)}
          >
            <Form.Item name="snapshot_id" label="数据快照" rules={[{ required: true }]}>
              <Select
                showSearch
                options={datasets.map((snapshot) => ({
                  label: `${snapshot.dataset_snapshot_id} · ${snapshot.symbol}`,
                  value: snapshot.dataset_snapshot_id,
                }))}
              />
            </Form.Item>
            <Form.Item name="run_id" label="运行 ID" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="fast_period" label="快线周期" rules={[{ required: true }]}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="slow_period" label="慢线周期" rules={[{ required: true }]}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="qty" label="下单数量" rules={[{ required: true }]}>
                  <InputNumber min={0} step={0.001} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="qty_policy_ref" label="仓位策略标识">
                  <Input />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="initial_cash" label="初始资金">
                  <InputNumber min={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="leverage" label="杠杆倍数">
                  <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="fee_rate" label="手续费率">
                  <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="slippage_bps" label="滑点基点">
                  <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="min_notional" label="最小名义价值">
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting === 'run'}>
              运行回测
            </Button>
          </Form>
        </Card>
      </Col>

      <Col span={24}>
        <Card title="当前已入库数据集">
          <Row gutter={[16, 16]}>
            {datasets.map((snapshot) => (
              <Col xs={24} md={12} xxl={8} key={snapshot.dataset_snapshot_id}>
                <Card size="small">
                  <Space direction="vertical" size={4}>
                    <Text strong>{snapshot.symbol}</Text>
                    <Text type="secondary">{snapshot.dataset_snapshot_id}</Text>
                    <Text type="secondary">{formatDateRange(snapshot.time_range_start, snapshot.time_range_end)}</Text>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      </Col>
    </Row>
  );
}

function OverviewView({
  overview,
  filteredSummaries,
  compareRunIds,
  setCompareRunIds,
  overviewQuery,
  setOverviewQuery,
  overviewStats,
}: {
  overview: WorkspaceOverview;
  filteredSummaries: RunSummaryView[];
  compareRunIds: string[];
  setCompareRunIds: (value: string[]) => void;
  overviewQuery: string;
  setOverviewQuery: (value: string) => void;
  overviewStats: Array<{ title: string; value: string }>;
}) {
  const columns = useMemo<ColumnDef<RunSummaryView>[]>(() => [
    {
      header: 'Run',
      accessorKey: 'run_id',
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{formatDateTime(row.original.created_at)}</Text>
        </Space>
      ),
    },
    { header: '标的', accessorKey: 'symbol' },
    { header: '策略', accessorKey: 'strategy_name' },
    { header: '收益率', cell: ({ row }) => formatPct(row.original.total_return) },
    { header: '基准', cell: ({ row }) => formatPct(row.original.benchmark_return) },
    { header: '交易', accessorKey: 'trade_count' },
    { header: '告警', accessorKey: 'warning_count' },
  ], []);

  const plotRows = overview.multi_run_equity;
  const chartOptions = filteredSummaries.length ? filteredSummaries : overview.summaries;
  const plotSeries = compareRunIds.map((runId) => ({
    x: plotRows.map((row) => row.timestamp),
    y: plotRows.map((row) => {
      const value = row[`${runId}_equity`];
      return typeof value === 'number' ? value : null;
    }),
    type: 'scatter',
    mode: 'lines',
    name: shortRunId(runId),
  }));

  return (
    <Row gutter={[16, 16]}>
      {overviewStats.map((entry) => (
        <Col xs={24} md={12} xl={6} key={entry.title}>
          <Card><Statistic title={entry.title} value={entry.value} /></Card>
        </Col>
      ))}

      <Col span={24}>
        <Card
          title="资金曲线对比"
          extra={(
            <Space wrap>
              <Input
                placeholder="搜索 run / 数据集 / 标的"
                value={overviewQuery}
                onChange={(event) => setOverviewQuery(event.target.value)}
              />
              <Select
                mode="multiple"
                value={compareRunIds}
                style={{ minWidth: 320 }}
                onChange={setCompareRunIds}
                options={chartOptions.slice(0, 12).map((summary) => ({
                  label: `${shortRunId(summary.run_id)} · ${summary.symbol}`,
                  value: summary.run_id,
                }))}
              />
            </Space>
          )}
        >
          <LazyPlot
            data={plotSeries as never}
            layout={{
              autosize: true,
              height: 360,
              margin: { l: 40, r: 20, t: 20, b: 40 },
              paper_bgcolor: '#ffffff',
              plot_bgcolor: '#ffffff',
              legend: { orientation: 'h' },
            } as never}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
            useResizeHandler
          />
        </Card>
      </Col>

      <Col span={24}>
        <Card title="运行总览表">
          <DataTable columns={columns} data={filteredSummaries} initialPageSize={10} />
        </Card>
      </Col>
    </Row>
  );
}

function AnalysisView({
  runs,
  selectedRun,
  selectedRunId,
  setSelectedRunId,
}: {
  runs: RunSummaryView[];
  selectedRun: RunAnalysisView | null;
  selectedRunId: string;
  setSelectedRunId: (value: string) => void;
}) {
  const tradeColumns = useMemo<ColumnDef<RunAnalysisView['trade_rows'][number]>[]>(() => [
    {
      header: '交易',
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.trade_id)}</Text>
          <Text type="secondary">{row.original.symbol}</Text>
        </Space>
      ),
    },
    { header: '方向', accessorKey: 'side' },
    { header: '开仓', cell: ({ row }) => formatDateTime(row.original.entry_time) },
    { header: '平仓', cell: ({ row }) => row.original.exit_time ? formatDateTime(row.original.exit_time) : '--' },
    { header: '开仓价', cell: ({ row }) => formatNumber(row.original.entry_price) },
    { header: '平仓价', cell: ({ row }) => row.original.exit_price === null ? '--' : formatNumber(row.original.exit_price) },
    { header: '数量', cell: ({ row }) => formatNumber(row.original.qty) },
    { header: '净收益', cell: ({ row }) => formatNumber(row.original.net_pnl) },
    { header: '收益率', cell: ({ row }) => formatPct(row.original.return_pct) },
    { header: '持仓K线', cell: ({ row }) => row.original.holding_bars },
    { header: '开仓原因', cell: ({ row }) => row.original.entry_reason || '--' },
    { header: '平仓原因', cell: ({ row }) => row.original.exit_reason || '--' },
  ], []);

  const warningColumns = useMemo<ColumnDef<RunAnalysisView['warning_rows'][number]>[]>(() => [
    { header: '级别', accessorKey: 'severity' },
    { header: '类型', accessorKey: 'warning_type' },
    { header: '代码', accessorKey: 'warning_code' },
    { header: '消息', accessorKey: 'message' },
  ], []);

  if (!runs.length) {
    return <Alert type="info" showIcon message="当前没有可分析的 run" />;
  }

  if (!selectedRun) {
    return <Alert type="info" showIcon message="正在加载所选 run 的详细数据" />;
  }

  const strategyParams = selectedRun.manifest.resolved_config_json.strategy_params as Record<string, unknown> | undefined;
  const executionConstraints = selectedRun.manifest.resolved_config_json.execution_constraints as Record<string, unknown> | undefined;

  return (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <Card
          title="单次分析"
          extra={(
            <Select
              value={selectedRunId}
              style={{ minWidth: 360 }}
              onChange={setSelectedRunId}
              options={runs.map((run) => ({
                label: `${shortRunId(run.run_id)} · ${run.symbol}`,
                value: run.run_id,
              }))}
            />
          )}
        >
          <Row gutter={[16, 16]}>
            <Col xs={24} md={12} xl={6}><Statistic title="总收益率" value={formatPct(selectedRun.metrics.total_return)} /></Col>
            <Col xs={24} md={12} xl={6}><Statistic title="最终权益" value={formatNumber(selectedRun.metrics.final_equity)} /></Col>
            <Col xs={24} md={12} xl={6}><Statistic title="成交笔数" value={selectedRun.execution_counts.trade_count} /></Col>
            <Col xs={24} md={12} xl={6}><Statistic title="基准收益" value={formatPct(selectedRun.benchmark?.return_pct)} /></Col>
          </Row>
        </Card>
      </Col>

      <Col span={24}>
        <Card title="权益曲线">
          <LazyPlot
            data={[
              {
                x: selectedRun.equity_rows.map((row) => row.timestamp),
                y: selectedRun.equity_rows.map((row) => row.strategy_equity),
                type: 'scatter',
                mode: 'lines',
                name: 'Strategy',
              },
              ...(selectedRun.benchmark ? [{
                x: selectedRun.equity_rows.map((row) => row.timestamp),
                y: selectedRun.equity_rows.map((row) => row.benchmark_equity),
                type: 'scatter',
                mode: 'lines',
                name: 'Benchmark',
                line: { dash: 'dash' },
              }] : []),
            ] as never}
            layout={{
              autosize: true,
              height: 360,
              margin: { l: 40, r: 20, t: 20, b: 40 },
              paper_bgcolor: '#ffffff',
              plot_bgcolor: '#ffffff',
            } as never}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
            useResizeHandler
          />
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="运行上下文">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Strategy Version">{selectedRun.manifest.strategy_version}</Descriptions.Item>
            <Descriptions.Item label="Execution Policy">{selectedRun.manifest.execution_policy_id}</Descriptions.Item>
            <Descriptions.Item label="Metric Policy">{selectedRun.manifest.metric_policy_id}</Descriptions.Item>
            <Descriptions.Item label="Feature Artifact">{selectedRun.manifest.feature_artifact_id}</Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="策略参数与执行约束">
          <Descriptions column={1} size="small">
            {Object.entries(strategyParams ?? {}).map(([key, value]) => (
              <Descriptions.Item key={key} label={key}>{String(value)}</Descriptions.Item>
            ))}
            {Object.entries(executionConstraints ?? {}).map(([key, value]) => (
              <Descriptions.Item key={key} label={key}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
      </Col>

      <Col span={24}>
        <Card title="交易记录">
          <DataTable columns={tradeColumns} data={selectedRun.trade_rows} initialPageSize={12} pageSizeOptions={[12, 24, 50]} />
        </Card>
      </Col>

      <Col span={24}>
        <Card title="结构化告警">
          <DataTable columns={warningColumns} data={selectedRun.warning_rows} initialPageSize={10} />
        </Card>
      </Col>
    </Row>
  );
}

function ParametersView({
  rows,
  fastRows,
  slowRows,
  parameterQuery,
  setParameterQuery,
}: {
  rows: ParameterLabRow[];
  fastRows: SensitivityRow[];
  slowRows: SensitivityRow[];
  parameterQuery: string;
  setParameterQuery: (value: string) => void;
}) {
  const columns = useMemo<ColumnDef<ParameterLabRow>[]>(() => [
    {
      header: 'Run',
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{row.original.symbol}</Text>
        </Space>
      ),
    },
    { header: 'Fast / Slow', cell: ({ row }) => `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}` },
    { header: 'Leverage', cell: ({ row }) => row.original.leverage ?? '--' },
    { header: '收益率', cell: ({ row }) => formatPct(row.original.total_return) },
    { header: '超额收益', cell: ({ row }) => formatPct(row.original.excess_return) },
    { header: '交易', accessorKey: 'trade_count' },
  ], []);

  return (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <Card
          title="参数实验"
          extra={(
            <Input
              placeholder="搜索 run / 数据集 / 标的"
              value={parameterQuery}
              onChange={(event) => setParameterQuery(event.target.value)}
            />
          )}
        >
          <Paragraph type="secondary">
            这个视图只负责参数敏感度、实验筛选和实验表，不再混入单次 run 详情，方便桌面和大屏长时间查看。
          </Paragraph>
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="Fast period 敏感度">
          <LazyPlot
            data={[
              {
                x: fastRows.map((row) => row.parameter_value),
                y: fastRows.map((row) => row.avg_metric),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Avg Return',
              },
              {
                x: fastRows.map((row) => row.parameter_value),
                y: fastRows.map((row) => row.best_metric),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Best Return',
              },
            ] as never}
            layout={{ autosize: true, height: 320, margin: { l: 40, r: 20, t: 20, b: 40 } } as never}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
            useResizeHandler
          />
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="Slow period 敏感度">
          <LazyPlot
            data={[
              {
                x: slowRows.map((row) => row.parameter_value),
                y: slowRows.map((row) => row.avg_metric),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Avg Return',
              },
              {
                x: slowRows.map((row) => row.parameter_value),
                y: slowRows.map((row) => row.best_metric),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Best Return',
              },
            ] as never}
            layout={{ autosize: true, height: 320, margin: { l: 40, r: 20, t: 20, b: 40 } } as never}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
            useResizeHandler
          />
        </Card>
      </Col>

      <Col span={24}>
        <Card title="实验表">
          <DataTable columns={columns} data={rows} initialPageSize={12} pageSizeOptions={[12, 24, 50]} />
        </Card>
      </Col>
    </Row>
  );
}

function buildOverviewStats(rows: RunSummaryView[]) {
  if (!rows.length) {
    return [
      { title: '筛选后 Run 数', value: '0' },
      { title: '最佳收益率', value: '--' },
      { title: '平均收益率', value: '--' },
      { title: '平均交易 / 告警', value: '--' },
    ];
  }

  const avgReturn = rows.reduce((sum, row) => sum + row.total_return, 0) / rows.length;
  const avgTradeCount = rows.reduce((sum, row) => sum + row.trade_count, 0) / rows.length;
  const bestReturn = Math.max(...rows.map((row) => row.total_return));
  const avgWarningCount = rows.reduce((sum, row) => sum + row.warning_count, 0) / rows.length;

  return [
    { title: '筛选后 Run 数', value: String(rows.length) },
    { title: '最佳收益率', value: formatPct(bestReturn) },
    { title: '平均收益率', value: formatPct(avgReturn) },
    { title: '平均交易 / 告警', value: `${avgTradeCount.toFixed(1)} / ${avgWarningCount.toFixed(1)}` },
  ];
}

export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          borderRadius: 14,
          colorPrimary: '#1677ff',
          colorBgLayout: '#f5f7fa',
        },
      }}
    >
      <AntdApp>
        <WorkspaceShell />
      </AntdApp>
    </ConfigProvider>
  );
}
