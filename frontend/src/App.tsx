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
  Modal,
  Popconfirm,
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
import { deleteDataset, deleteRun, loadDatasets, loadOverview, loadParameters, loadRunDetail, loadRuns, postIngest, postRunEma } from './lib/api';
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

const ANALYSIS_FIELD_LABELS: Record<string, string> = {
  strategy_version: '策略版本',
  execution_policy_id: '执行策略',
  metric_policy_id: '指标策略',
  feature_artifact_id: '特征产物',
  fast_period: '快线周期',
  slow_period: '慢线周期',
  input_price_field: '输入价格字段',
  qty_policy_ref: '仓位策略标识',
  feature_version: '特征版本',
  name: '策略名称',
  version: '策略版本号',
  initial_cash: '初始资金',
  leverage: '杠杆倍数',
  fee_rate: '手续费率',
  slippage_bps: '滑点基点',
  min_notional: '最小名义价值',
  qty_by_policy: '按策略下单数量',
};

function isTabId(value: string | null): value is TabId {
  return value === 'execution' || value === 'overview' || value === 'analysis' || value === 'parameters';
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function labelAnalysisField(key: string): string {
  return ANALYSIS_FIELD_LABELS[key] ?? key;
}

function formatAnalysisFieldValue(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : formatNumber(value);
  }
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
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
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
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

  async function handleDeleteRun(runId: string) {
    setDeletingRunId(runId);
    try {
      await deleteRun(runId);
      setLastActionResult(`已删除回测：${runId}`);
      message.success(`已删除回测：${runId}`);
      if (selectedRunId === runId) {
        setSelectedRunId('');
      }
      invalidateDerivedData();
      await refreshShell();
      setActiveTab('overview');
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '删除回测失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDeletingRunId(null);
    }
  }

  async function handleDeleteDataset(snapshotId: string) {
    setDeletingDatasetId(snapshotId);
    try {
      await deleteDataset(snapshotId);
      setLastActionResult(`已删除数据集：${snapshotId}`);
      message.success(`已删除数据集：${snapshotId}`);
      await refreshShell();
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '删除数据集失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDeletingDatasetId(null);
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
              deletingDatasetId={deletingDatasetId}
              deletingRunId={deletingRunId}
              onIngest={handleIngest}
              onRun={handleRun}
              onDeleteDataset={handleDeleteDataset}
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
              deletingRunId={deletingRunId}
              onDeleteRun={handleDeleteRun}
            />
          )}
          {activeTab === 'analysis' && (
            <AnalysisView
              runs={runs}
              selectedRun={selectedRun}
              selectedRunId={selectedRunId}
              setSelectedRunId={setSelectedRunId}
              deletingRunId={deletingRunId}
              onDeleteRun={handleDeleteRun}
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
  deletingDatasetId,
  deletingRunId,
  onIngest,
  onRun,
  onDeleteDataset,
}: {
  datasets: DatasetSnapshotView[];
  ingestForm: ReturnType<typeof Form.useForm>[0];
  runForm: ReturnType<typeof Form.useForm>[0];
  submitting: 'ingest' | 'run' | null;
  deletingDatasetId: string | null;
  deletingRunId: string | null;
  onIngest: (values: Record<string, unknown>) => Promise<void>;
  onRun: (values: Record<string, unknown>) => Promise<void>;
  onDeleteDataset: (snapshotId: string) => Promise<void>;
}) {
  const selectedSnapshotId = Form.useWatch('snapshot_id', runForm) as string | undefined;
  const selectedRunTimeframe = Form.useWatch('timeframe', runForm) as string | undefined;
  const [isDatasetModalOpen, setIsDatasetModalOpen] = useState(false);
  const [datasetTimeframeFilter, setDatasetTimeframeFilter] = useState<string>('all');
  const [datasetExchangeFilter, setDatasetExchangeFilter] = useState<string>('all');
  const [datasetQuery, setDatasetQuery] = useState('');
  const timeframeOptions = useMemo(
    () => [...new Set(datasets.map((snapshot) => snapshot.timeframe))]
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right, 'en', { numeric: true }))
      .map((timeframe) => ({
        label: timeframe.toUpperCase(),
        value: timeframe,
      })),
    [datasets],
  );
  const filteredDatasets = useMemo(
    () => selectedRunTimeframe
      ? datasets.filter((snapshot) => snapshot.timeframe === selectedRunTimeframe)
      : datasets,
    [datasets, selectedRunTimeframe],
  );
  const datasetById = useMemo(
    () => new Map(datasets.map((snapshot) => [snapshot.dataset_snapshot_id, snapshot] as const)),
    [datasets],
  );
  const datasetTableTimeframeOptions = useMemo(
    () => timeframeOptions.map((option) => ({ label: option.label, value: option.value })),
    [timeframeOptions],
  );
  const datasetExchangeOptions = useMemo(
    () => [...new Set(datasets.map((snapshot) => snapshot.exchange))]
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right, 'en'))
      .map((exchange) => ({
        label: exchange,
        value: exchange,
      })),
    [datasets],
  );
  const filteredDatasetRows = useMemo(() => {
    const query = datasetQuery.trim().toLowerCase();
    return datasets.filter((snapshot) => {
      if (datasetTimeframeFilter !== 'all' && snapshot.timeframe !== datasetTimeframeFilter) {
        return false;
      }
      if (datasetExchangeFilter !== 'all' && snapshot.exchange !== datasetExchangeFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      return [
        snapshot.dataset_snapshot_id,
        snapshot.symbol,
        snapshot.exchange,
        snapshot.timeframe,
      ].join(' ').toLowerCase().includes(query);
    });
  }, [datasetExchangeFilter, datasetQuery, datasetTimeframeFilter, datasets]);
  const datasetColumns = useMemo<ColumnDef<DatasetSnapshotView>[]>(() => [
    {
      header: '数据集',
      accessorKey: 'dataset_snapshot_id',
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.original.dataset_snapshot_id}</Text>
          <Text type="secondary">{row.original.symbol}</Text>
        </Space>
      ),
    },
    { header: '交易所', accessorKey: 'exchange' },
    {
      id: 'timeframe',
      header: '周期',
      accessorFn: (row) => row.timeframe,
      cell: ({ row }) => row.original.timeframe.toUpperCase(),
    },
    {
      id: 'time_range_start',
      header: '时间范围',
      accessorFn: (row) => row.time_range_start,
      cell: ({ row }) => formatDateRange(row.original.time_range_start, row.original.time_range_end),
    },
    {
      id: 'row_count',
      header: 'K线数',
      accessorFn: (row) => row.row_count,
      cell: ({ row }) => formatNumber(row.original.row_count, 0),
    },
    {
      id: 'created_at',
      header: '导入时间',
      accessorFn: (row) => row.created_at,
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: 'actions',
      header: '操作',
      enableSorting: false,
      cell: ({ row }) => (
        <Popconfirm
          title="删除这个数据集？"
          description={(
            <>
              <div>{row.original.dataset_snapshot_id}</div>
              <div>已有回测结果不会被删除。</div>
            </>
          )}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true, loading: deletingDatasetId === row.original.dataset_snapshot_id }}
          onConfirm={() => onDeleteDataset(row.original.dataset_snapshot_id)}
        >
          <Button type="link" danger size="small">删除</Button>
        </Popconfirm>
      ),
    },
  ], [deletingDatasetId, onDeleteDataset]);

  useEffect(() => {
    if (!selectedRunTimeframe && datasets[0]?.timeframe) {
      runForm.setFieldValue('timeframe', datasets[0].timeframe);
    }
  }, [datasets, runForm, selectedRunTimeframe]);

  useEffect(() => {
    if (!filteredDatasets.length) {
      if (selectedSnapshotId) {
        runForm.setFieldValue('snapshot_id', undefined);
      }
      return;
    }
    if (!selectedSnapshotId || !filteredDatasets.some((snapshot) => snapshot.dataset_snapshot_id === selectedSnapshotId)) {
      runForm.setFieldValue('snapshot_id', filteredDatasets[0].dataset_snapshot_id);
    }
  }, [filteredDatasets, runForm, selectedSnapshotId]);

  function handleRunTimeframeChange(value: string) {
    runForm.setFieldValue('timeframe', value);
    const nextSnapshot = datasets.find((snapshot) => snapshot.timeframe === value);
    runForm.setFieldValue('snapshot_id', nextSnapshot?.dataset_snapshot_id);
  }

  function handleRunSnapshotChange(value: string) {
    runForm.setFieldValue('snapshot_id', value);
    const selectedSnapshot = datasetById.get(value);
    if (selectedSnapshot && selectedSnapshot.timeframe !== selectedRunTimeframe) {
      runForm.setFieldValue('timeframe', selectedSnapshot.timeframe);
    }
  }

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
              timeframe: datasets[0]?.timeframe,
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
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="timeframe" label="周期" rules={[{ required: true }]}>
                  <Select
                    options={timeframeOptions}
                    placeholder="选择周期"
                    onChange={handleRunTimeframeChange}
                  />
                </Form.Item>
              </Col>
              <Col span={16}>
                <Form.Item name="snapshot_id" label="数据快照" rules={[{ required: true }]}>
                  <Select
                    showSearch
                    placeholder={filteredDatasets.length ? '选择数据快照' : '该周期下暂无数据快照'}
                    notFoundContent="该周期下暂无数据快照"
                    options={filteredDatasets.map((snapshot) => ({
                      label: `${snapshot.dataset_snapshot_id} · ${snapshot.symbol} · ${snapshot.timeframe.toUpperCase()}`,
                      value: snapshot.dataset_snapshot_id,
                    }))}
                    optionFilterProp="label"
                    onChange={handleRunSnapshotChange}
                  />
                </Form.Item>
              </Col>
            </Row>
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
        <Card
          title="当前已入库数据集"
          extra={(
            <Space>
              {deletingRunId ? <Text type="secondary">正在删除回测…</Text> : null}
              {deletingDatasetId ? <Text type="secondary">正在删除数据集…</Text> : null}
              <Button onClick={() => setIsDatasetModalOpen(true)}>管理数据集</Button>
            </Space>
          )}
        >
          <Paragraph type="secondary">
            默认展示最近导入的数据集摘要。完整数据集清单、分页筛选和删除入口放在“管理数据集”弹框里。
          </Paragraph>
          <Row gutter={[16, 16]}>
            {datasets.slice(0, 6).map((snapshot) => (
              <Col xs={24} md={12} xxl={8} key={snapshot.dataset_snapshot_id}>
                <Card size="small">
                  <Space direction="vertical" size={4}>
                    <Text strong>{snapshot.symbol}</Text>
                    <Text type="secondary">{`${snapshot.dataset_snapshot_id} · ${snapshot.timeframe.toUpperCase()}`}</Text>
                    <Text type="secondary">{formatDateRange(snapshot.time_range_start, snapshot.time_range_end)}</Text>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      </Col>

      <Modal
        title="数据集管理"
        open={isDatasetModalOpen}
        onCancel={() => setIsDatasetModalOpen(false)}
        footer={null}
        width={1120}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            共 {datasets.length} 个已导入数据集。这里适合集中做分页浏览、筛选和删除，避免把执行台主布局撑乱。
          </Paragraph>
          <Space wrap size={12}>
            <Select
              value={datasetTimeframeFilter}
              style={{ width: 140 }}
              onChange={setDatasetTimeframeFilter}
              options={[
                { label: '全部周期', value: 'all' },
                ...datasetTableTimeframeOptions,
              ]}
            />
            <Select
              value={datasetExchangeFilter}
              style={{ width: 160 }}
              onChange={setDatasetExchangeFilter}
              options={[
                { label: '全部交易所', value: 'all' },
                ...datasetExchangeOptions,
              ]}
            />
            <Input
              value={datasetQuery}
              onChange={(event) => setDatasetQuery(event.target.value)}
              placeholder="搜索快照ID / 标的 / 交易所 / 周期"
              style={{ width: 260 }}
            />
          </Space>
          <DataTable
            columns={datasetColumns}
            data={filteredDatasetRows}
            initialPageSize={8}
            pageSizeOptions={[8, 16, 32, 50]}
            initialSorting={[{ id: 'created_at', desc: true }]}
          />
        </Space>
      </Modal>
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
  deletingRunId,
  onDeleteRun,
}: {
  overview: WorkspaceOverview;
  filteredSummaries: RunSummaryView[];
  compareRunIds: string[];
  setCompareRunIds: (value: string[]) => void;
  overviewQuery: string;
  setOverviewQuery: (value: string) => void;
  overviewStats: Array<{ title: string; value: string }>;
  deletingRunId: string | null;
  onDeleteRun: (runId: string) => Promise<void>;
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
    {
      id: 'actions',
      header: '操作',
      enableSorting: false,
      cell: ({ row }) => (
        <Popconfirm
          title="删除这个回测？"
          description={`run_id: ${row.original.run_id}`}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true, loading: deletingRunId === row.original.run_id }}
          onConfirm={() => onDeleteRun(row.original.run_id)}
        >
          <Button type="link" danger size="small">删除</Button>
        </Popconfirm>
      ),
    },
  ], []);

  const plotRows = overview.multi_run_equity;
  const chartOptions = filteredSummaries.length ? filteredSummaries : overview.summaries;
  const summaryByRunId = new Map(overview.summaries.map((summary) => [summary.run_id, summary] as const));
  const plotSeries = compareRunIds.map((runId) => ({
    x: plotRows.map((row) => row.timestamp),
    y: plotRows.map((row) => {
      const value = row[`${runId}_equity`];
      return typeof value === 'number' ? value : null;
    }),
    type: 'scatter',
    mode: 'lines',
    name: `${shortRunId(runId)} · ${summaryByRunId.get(runId)?.symbol ?? '未知标的'}`,
    line: {
      width: 2.5,
    },
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
              hovermode: 'x unified',
              xaxis: { title: '时间（UTC）' },
              yaxis: { title: '权益' },
              legend: { orientation: 'h', title: { text: '每条线代表一个 run 的策略权益' } },
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
  deletingRunId,
  onDeleteRun,
}: {
  runs: RunSummaryView[];
  selectedRun: RunAnalysisView | null;
  selectedRunId: string;
  setSelectedRunId: (value: string) => void;
  deletingRunId: string | null;
  onDeleteRun: (runId: string) => Promise<void>;
}) {
  const [tradeSideFilter, setTradeSideFilter] = useState<string>('all');
  const [tradeOutcomeFilter, setTradeOutcomeFilter] = useState<'all' | 'win' | 'loss' | 'open'>('all');
  const [tradeReasonQuery, setTradeReasonQuery] = useState('');

  const tradeColumns = useMemo<ColumnDef<RunAnalysisView['trade_rows'][number]>[]>(() => [
    {
      id: 'trade_id',
      header: '交易',
      enableSorting: false,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.trade_id)}</Text>
          <Text type="secondary">{row.original.symbol}</Text>
        </Space>
      ),
    },
    { header: '方向', accessorKey: 'side' },
    { id: 'entry_time', header: '开仓', accessorFn: (row) => row.entry_time, cell: ({ row }) => formatDateTime(row.original.entry_time) },
    { id: 'exit_time', header: '平仓', accessorFn: (row) => row.exit_time ?? '', cell: ({ row }) => row.original.exit_time ? formatDateTime(row.original.exit_time) : '--' },
    { id: 'entry_price', header: '开仓价', accessorFn: (row) => row.entry_price, cell: ({ row }) => formatNumber(row.original.entry_price) },
    { id: 'exit_price', header: '平仓价', accessorFn: (row) => row.exit_price ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.exit_price === null ? '--' : formatNumber(row.original.exit_price) },
    { id: 'qty', header: '数量', accessorFn: (row) => row.qty, cell: ({ row }) => formatNumber(row.original.qty) },
    { id: 'net_pnl', header: '净收益', accessorFn: (row) => row.net_pnl, cell: ({ row }) => formatNumber(row.original.net_pnl) },
    { id: 'return_pct', header: '收益率', accessorFn: (row) => row.return_pct, cell: ({ row }) => formatPct(row.original.return_pct) },
    { id: 'holding_bars', header: '持仓K线', accessorFn: (row) => row.holding_bars, cell: ({ row }) => row.original.holding_bars },
    { id: 'entry_reason', header: '开仓原因', accessorFn: (row) => row.entry_reason || '', cell: ({ row }) => row.original.entry_reason || '--' },
    { id: 'exit_reason', header: '平仓原因', accessorFn: (row) => row.exit_reason || '', cell: ({ row }) => row.original.exit_reason || '--' },
  ], []);

  const warningColumns = useMemo<ColumnDef<RunAnalysisView['warning_rows'][number]>[]>(() => [
    { header: '级别', accessorKey: 'severity' },
    { header: '类型', accessorKey: 'warning_type' },
    { header: '代码', accessorKey: 'warning_code' },
    { header: '消息', accessorKey: 'message' },
  ], []);

  const tradeRows = selectedRun?.trade_rows ?? [];
  const tradeSideOptions = Array.from(new Set(tradeRows.map((row) => row.side))).sort();
  const filteredTradeRows = useMemo(
    () => tradeRows
      .filter((row) => {
        if (tradeSideFilter !== 'all' && row.side !== tradeSideFilter) {
          return false;
        }
        if (tradeOutcomeFilter === 'win' && row.net_pnl <= 0) {
          return false;
        }
        if (tradeOutcomeFilter === 'loss' && row.net_pnl >= 0) {
          return false;
        }
        if (tradeOutcomeFilter === 'open' && row.exit_time !== null) {
          return false;
        }
        const query = tradeReasonQuery.trim().toLowerCase();
        if (!query) {
          return true;
        }
        return [row.trade_id, row.entry_reason, row.exit_reason, row.symbol].join(' ').toLowerCase().includes(query);
      }),
    [tradeRows, tradeOutcomeFilter, tradeReasonQuery, tradeSideFilter],
  );

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
            <Space wrap>
              <Select
                value={selectedRunId}
                style={{ minWidth: 360 }}
                onChange={setSelectedRunId}
                options={runs.map((run) => ({
                  label: `${shortRunId(run.run_id)} · ${run.symbol}`,
                  value: run.run_id,
                }))}
              />
              <Popconfirm
                title="删除当前回测？"
                description={`run_id: ${selectedRun.run_id}`}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true, loading: deletingRunId === selectedRun.run_id }}
                onConfirm={() => onDeleteRun(selectedRun.run_id)}
              >
                <Button danger>删除当前回测</Button>
              </Popconfirm>
            </Space>
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
        <Card title="资金曲线">
          <Paragraph type="secondary">
            仅展示当前策略账户权益随时间的变化，便于单次 run 的资金演进查看。
          </Paragraph>
          <LazyPlot
            data={[
              {
                x: selectedRun.equity_rows.map((row) => row.timestamp),
                y: selectedRun.equity_rows.map((row) => row.strategy_equity),
                type: 'scatter',
                mode: 'lines',
                name: '资金曲线',
                line: { color: '#1677ff', width: 3.5 },
              },
            ] as never}
            layout={{
              autosize: true,
              height: 360,
              margin: { l: 40, r: 20, t: 20, b: 40 },
              paper_bgcolor: '#ffffff',
              plot_bgcolor: '#ffffff',
              hovermode: 'x unified',
              xaxis: { title: '时间（UTC）' },
              yaxis: { title: '资金' },
              legend: {
                orientation: 'h',
                y: 1.12,
                title: { text: '图例' },
              },
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
            <Descriptions.Item label="策略版本">{selectedRun.manifest.strategy_version}</Descriptions.Item>
            <Descriptions.Item label="执行策略">{selectedRun.manifest.execution_policy_id}</Descriptions.Item>
            <Descriptions.Item label="指标策略">{selectedRun.manifest.metric_policy_id}</Descriptions.Item>
            <Descriptions.Item label="特征产物">{selectedRun.manifest.feature_artifact_id}</Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="策略参数与执行约束">
          <Descriptions column={1} size="small">
            {Object.entries(strategyParams ?? {}).map(([key, value]) => (
              <Descriptions.Item key={key} label={labelAnalysisField(key)}>
                {formatAnalysisFieldValue(value)}
              </Descriptions.Item>
            ))}
            {Object.entries(executionConstraints ?? {}).map(([key, value]) => (
              <Descriptions.Item key={key} label={labelAnalysisField(key)}>
                {formatAnalysisFieldValue(value)}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
      </Col>

      <Col span={24}>
        <Card
          title="交易记录"
          extra={(
            <Space wrap size={12}>
              <Select
                value={tradeSideFilter}
                style={{ width: 120 }}
                onChange={setTradeSideFilter}
                options={[
                  { label: '全部方向', value: 'all' },
                  ...tradeSideOptions.map((side) => ({ label: side, value: side })),
                ]}
              />
              <Select
                value={tradeOutcomeFilter}
                style={{ width: 140 }}
                onChange={setTradeOutcomeFilter}
                options={[
                  { label: '全部结果', value: 'all' },
                  { label: '仅盈利', value: 'win' },
                  { label: '仅亏损', value: 'loss' },
                  { label: '未平仓', value: 'open' },
                ]}
              />
              <Input
                value={tradeReasonQuery}
                onChange={(event) => setTradeReasonQuery(event.target.value)}
                placeholder="搜索交易ID / 原因 / 标的"
                style={{ width: 220 }}
              />
            </Space>
          )}
        >
          <Paragraph type="secondary">
            当前显示 {filteredTradeRows.length} / {selectedRun.trade_rows.length} 笔交易。可直接点击表头右侧上下按钮排序。
          </Paragraph>
          <DataTable
            columns={tradeColumns}
            data={filteredTradeRows}
            initialPageSize={12}
            pageSizeOptions={[12, 24, 50]}
            initialSorting={[{ id: 'entry_time', desc: true }]}
          />
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
