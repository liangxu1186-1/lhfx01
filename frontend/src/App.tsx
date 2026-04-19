import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import dayjs from 'dayjs';
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  ConfigProvider,
  DatePicker,
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
import { deleteDataset, deleteRun, loadDatasets, loadParameterExperimentDetail, loadParameterExperiments, loadParameters, loadRunDetail, loadRuns, postIngest, postParameterExperiment, postRunEma } from './lib/api';
import { formatDateRange, formatDateTime, formatNumber, formatPct, shortRunId } from './lib/format';
import type {
  DatasetSnapshotView,
  ParameterExperimentDetail,
  ParameterExperimentSummary,
  ParameterLabRow,
  RunAnalysisView,
  RunSummaryView,
  SensitivityRow,
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

const ALL_EXPERIMENTS = '__all__';

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
  cash_allocation_pct: '资金使用比例 (%)',
  fee_rate: '手续费率',
  slippage_bps: '滑点基点',
  min_notional: '最小名义价值',
  qty_by_policy: '按策略下单数量',
  cash_allocation_pct_by_policy: '按策略资金使用比例 (%)',
};

const ANALYSIS_VALUE_LABELS: Record<string, Record<string, string>> = {
  execution_policy_id: {
    signal_on_bar_close_fill_on_next_bar_open: '信号在当前 K 线收盘确认，下一根 K 线开盘成交',
  },
  metric_policy_id: {
    metrics_daily_365_v1: '日频指标口径（按 365 天年化）',
  },
  benchmark_type: {
    buy_and_hold: '买入并持有',
    none: '无基准',
  },
  name: {
    ema_crossover: 'EMA 均线交叉',
  },
  qty_policy_ref: {
    fixed_1: '固定数量 fixed_1',
    percent_of_cash: '按可用资金比例动态开仓 percent_of_cash',
  },
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

function formatAnalysisFieldValue(key: string, value: unknown): string {
  if (typeof value === 'string') {
    return ANALYSIS_VALUE_LABELS[key]?.[value] ?? value;
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : formatNumber(value);
  }
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
}

function experimentStatusColor(status: string | undefined): string {
  if (status === 'success') {
    return 'green';
  }
  if (status === 'failed') {
    return 'red';
  }
  return 'blue';
}

function experimentSearchTypeLabel(searchType: string | undefined): string {
  return searchType === 'grid' ? '网格搜索' : '随机搜索';
}

function pickChartSamples<T>(rows: T[], maxPoints = 1200): T[] {
  if (rows.length <= maxPoints) {
    return rows;
  }
  const step = Math.ceil(rows.length / maxPoints);
  const sampled: T[] = [];
  for (let index = 0; index < rows.length; index += step) {
    sampled.push(rows[index]);
  }
  const lastRow = rows[rows.length - 1];
  if (sampled[sampled.length - 1] !== lastRow) {
    sampled.push(lastRow);
  }
  return sampled;
}

function normalizeDateValue(value: unknown): string | undefined {
  if (value === null || value === undefined || value === '') {
    return undefined;
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'object' && value !== null && 'toISOString' in value && typeof value.toISOString === 'function') {
    return value.toISOString();
  }
  return String(value);
}

function normalizeTimeframeValue(value: unknown): string | undefined {
  if (value === null || value === undefined) {
    return undefined;
  }
  const normalized = String(value).trim().toLowerCase();
  return normalized || undefined;
}

function buildDatasetGroupKey(snapshot: DatasetSnapshotView): string {
  return `${snapshot.exchange}::${snapshot.market_type}::${snapshot.symbol}`;
}

function buildDatasetGroupLabel(snapshot: DatasetSnapshotView): string {
  return `${snapshot.exchange} · ${snapshot.symbol}`;
}

function parseIntegerList(value: unknown): number[] {
  return String(value ?? '')
    .split(',')
    .map((entry) => Number.parseInt(entry.trim(), 10))
    .filter((entry) => Number.isFinite(entry) && entry > 0);
}

function validateIntegerListInput(value: unknown, fieldLabel: string): string | null {
  const raw = String(value ?? '').trim();
  if (!raw) {
    return `请输入${fieldLabel}`;
  }
  const parts = raw.split(',').map((entry) => entry.trim()).filter(Boolean);
  if (!parts.length) {
    return `请输入${fieldLabel}`;
  }
  const parsed = parts.map((entry) => Number.parseInt(entry, 10));
  if (parsed.some((entry) => !Number.isFinite(entry) || entry <= 0)) {
    return `${fieldLabel}必须是逗号分隔的正整数`;
  }
  if (new Set(parsed).size !== parsed.length) {
    return `${fieldLabel}不能包含重复值`;
  }
  return null;
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
  const [parameterLab, setParameterLab] = useState<WorkspaceParameterLab | null>(null);
  const [parameterExperiments, setParameterExperiments] = useState<ParameterExperimentSummary[]>([]);
  const [selectedExperimentId, setSelectedExperimentId] = useState(ALL_EXPERIMENTS);
  const [selectedExperimentDetail, setSelectedExperimentDetail] = useState<ParameterExperimentDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunAnalysisView | null>(null);
  const [runDetailCache, setRunDetailCache] = useState<Record<string, RunAnalysisView>>({});
  const [error, setError] = useState<string | null>(null);
  const [shellLoading, setShellLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [experimentDetailLoading, setExperimentDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>(initialState.tab);
  const [selectedRunId, setSelectedRunId] = useState<string>(initialState.run);
  const [compareRunIds, setCompareRunIds] = useState<string[]>(initialState.compare);
  const [overviewQuery, setOverviewQuery] = useState(initialState.overviewQuery);
  const [parameterQuery, setParameterQuery] = useState(initialState.parameterQuery);
  const [lastActionResult, setLastActionResult] = useState('');
  const [submitting, setSubmitting] = useState<'ingest' | 'run' | 'experiment' | null>(null);
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [ingestForm] = Form.useForm();
  const [runForm] = Form.useForm();
  const [experimentForm] = Form.useForm();
  const deferredOverviewQuery = useDeferredValue(overviewQuery);
  const deferredParameterQuery = useDeferredValue(parameterQuery);

  function applyPayloadMeta(payload: { generated_at: string; source: WorkspaceSource }) {
    setGeneratedAt(payload.generated_at);
    setSource(payload.source);
  }

  function invalidateDerivedData() {
    setParameterLab(null);
    setParameterExperiments([]);
    setSelectedExperimentId(ALL_EXPERIMENTS);
    setSelectedExperimentDetail(null);
    setSelectedRun(null);
    setRunDetailCache({});
  }

  async function refreshShell() {
    setShellLoading(true);
    try {
      const [datasetsPayload, runsPayload] = await Promise.all([loadDatasets(), loadRuns()]);
      setDatasets(datasetsPayload.datasets);
      setRuns(runsPayload.runs);
      applyPayloadMeta(runsPayload);
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
    if (!runs.length) {
      return;
    }
    const availableRunIds = new Set(runs.map((entry) => entry.run_id));
    const validRunIds = compareRunIds.filter((runId) => availableRunIds.has(runId));
    if (!validRunIds.length && runs.length) {
      setCompareRunIds(runs.slice(0, 3).map((entry) => entry.run_id));
      return;
    }
    if (validRunIds.length !== compareRunIds.length) {
      setCompareRunIds(validRunIds);
    }
  }, [compareRunIds, runs]);

  useEffect(() => {
    if (activeTab !== 'parameters') {
      return;
    }
    if (!parameterExperiments.length) {
      if (selectedExperimentId !== ALL_EXPERIMENTS) {
        setSelectedExperimentId(ALL_EXPERIMENTS);
      }
      setSelectedExperimentDetail(null);
      return;
    }
    if (selectedExperimentId !== ALL_EXPERIMENTS && !parameterExperiments.some((experiment) => experiment.experiment_id === selectedExperimentId)) {
      setSelectedExperimentId(ALL_EXPERIMENTS);
    }
  }, [activeTab, parameterExperiments, selectedExperimentId]);

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
          const cachedRun = runDetailCache[selectedRunId];
          if (cachedRun) {
            setSelectedRun(cachedRun);
            setError(null);
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
          setRunDetailCache((current) => ({ ...current, [payload.run.run_id]: payload.run }));
          setError(null);
          return;
        }

        if (activeTab === 'parameters' && parameterLab === null) {
          setSectionLoading(true);
          const [parameterPayload, experimentPayload] = await Promise.all([
            loadParameters(),
            loadParameterExperiments(),
          ]);
          if (cancelled) {
            return;
          }
          applyPayloadMeta(parameterPayload);
          setParameterLab(parameterPayload.parameter_lab);
          setParameterExperiments(experimentPayload.parameter_experiments);
          setError(null);
          return;
        }

        if (activeTab === 'parameters' && parameterLab !== null && !parameterExperiments.length) {
          setSectionLoading(true);
          const payload = await loadParameterExperiments();
          if (cancelled) {
            return;
          }
          applyPayloadMeta(payload);
          setParameterExperiments(payload.parameter_experiments);
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
  }, [activeTab, overview, parameterLab, runDetailCache, selectedRun, selectedRunId]);

  useEffect(() => {
    if (activeTab !== 'parameters' || selectedExperimentId === ALL_EXPERIMENTS) {
      setSelectedExperimentDetail(null);
      return;
    }
    let cancelled = false;

    async function loadSelectedExperimentDetail() {
      try {
        setSelectedExperimentDetail(null);
        setExperimentDetailLoading(true);
        const detailPayload = await loadParameterExperimentDetail(selectedExperimentId);
        if (cancelled) {
          return;
        }
        applyPayloadMeta(detailPayload);
        setSelectedExperimentDetail(detailPayload.parameter_experiment);
        setError(null);
      } catch (loadError: unknown) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '参数实验详情加载失败');
        }
      } finally {
        if (!cancelled) {
          setExperimentDetailLoading(false);
        }
      }
    }

    void loadSelectedExperimentDetail();
    return () => {
      cancelled = true;
    };
  }, [activeTab, selectedExperimentId]);

  useEffect(() => {
    if (activeTab !== 'parameters') {
      return;
    }
    if (!parameterExperiments.some((experiment) => experiment.status === 'pending' || experiment.status === 'running')) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadParameterExperiments()
        .then((experimentPayload) => {
          applyPayloadMeta(experimentPayload);
          setParameterExperiments(experimentPayload.parameter_experiments);
          setError(null);
        })
        .catch((loadError: unknown) => {
          setError(loadError instanceof Error ? loadError.message : '参数实验状态刷新失败');
        });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeTab, parameterExperiments]);

  const selectedExperimentSummary = useMemo(
    () => parameterExperiments.find((experiment) => experiment.experiment_id === selectedExperimentId) ?? null,
    [parameterExperiments, selectedExperimentId],
  );

  useEffect(() => {
    if (activeTab !== 'parameters' || selectedExperimentId === ALL_EXPERIMENTS) {
      return;
    }
    if (selectedExperimentSummary?.status !== 'pending' && selectedExperimentSummary?.status !== 'running') {
      return;
    }
    const timer = window.setInterval(() => {
      void loadParameterExperimentDetail(selectedExperimentId)
        .then((detailPayload) => {
          applyPayloadMeta(detailPayload);
          setSelectedExperimentDetail(detailPayload.parameter_experiment);
          setError(null);
        })
        .catch((loadError: unknown) => {
          setError(loadError instanceof Error ? loadError.message : '参数实验详情刷新失败');
        });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeTab, selectedExperimentId, selectedExperimentSummary?.status]);

  useEffect(() => {
    if (activeTab !== 'parameters' || parameterLab === null || selectedExperimentDetail === null) {
      return;
    }
    const runIds = selectedExperimentDetail.execution.run_ids ?? [];
    if (!runIds.length) {
      return;
    }
    const knownRunIds = new Set(parameterLab.rows.map((row) => row.run_id));
    const hasMissingRows = runIds.some((runId) => !knownRunIds.has(runId));
    const isTerminal = selectedExperimentDetail.execution.status === 'success' || selectedExperimentDetail.execution.status === 'failed';
    if (!hasMissingRows || !isTerminal) {
      return;
    }
    let cancelled = false;
    setSectionLoading(true);
    void loadParameters()
      .then((payload) => {
        if (cancelled) {
          return;
        }
        applyPayloadMeta(payload);
        setParameterLab(payload.parameter_lab);
        setError(null);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '参数实验结果刷新失败');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSectionLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, parameterLab, selectedExperimentDetail]);

  async function handleRefresh() {
    invalidateDerivedData();
    await refreshShell();
  }

  async function handleIngest(values: Record<string, unknown>) {
    setSubmitting('ingest');
    try {
      const result = await postIngest({
        ...values,
        timeframe: normalizeTimeframeValue(values.timeframe),
        since: normalizeDateValue(values.since),
        until: normalizeDateValue(values.until),
      });
      const snapshotId = String(result.dataset_snapshot_id ?? '');
      setLastActionResult(`导入完成：${snapshotId}`);
      message.success(`导入完成：${snapshotId}`);
      invalidateDerivedData();
      await refreshShell();
      runForm.setFieldValue('dataset_key', undefined);
      runForm.setFieldValue('timeframes', undefined);
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
      const snapshotIds = Array.isArray(values.snapshot_ids)
        ? values.snapshot_ids.map((value) => String(value)).filter(Boolean)
        : [];
      if (!snapshotIds.length) {
        throw new Error('请先选择至少一个周期');
      }

      const baseRunId = String(values.run_id ?? '').trim();
      const createdRunIds: string[] = [];
      for (const [index, snapshotId] of snapshotIds.entries()) {
        const snapshot = datasets.find((entry) => entry.dataset_snapshot_id === snapshotId);
        if (!snapshot) {
          throw new Error(`未找到数据快照：${snapshotId}`);
        }
        const runId = snapshotIds.length === 1
          ? baseRunId
          : `${baseRunId}-${snapshot.timeframe.toLowerCase()}`;
        const result = await postRunEma({
          run_id: runId,
          snapshot_id: snapshotId,
          fast_period: values.fast_period,
          slow_period: values.slow_period,
          cash_allocation_pct: values.cash_allocation_pct,
          initial_cash: values.initial_cash,
          leverage: values.leverage,
          fee_rate: values.fee_rate,
          slippage_bps: values.slippage_bps,
          min_notional: values.min_notional,
          benchmark: 'buy_and_hold',
        });
        createdRunIds.push(String(result.run_id ?? runId));
        if (index < snapshotIds.length - 1) {
          setLastActionResult(`已完成 ${index + 1} / ${snapshotIds.length} 个周期回测`);
        }
      }

      const finalRunId = createdRunIds[createdRunIds.length - 1] ?? '';
      const summaryText = createdRunIds.length === 1
        ? `回测完成：${finalRunId}`
        : `已串行完成 ${createdRunIds.length} 个周期回测`;
      setLastActionResult(summaryText);
      message.success(summaryText);
      invalidateDerivedData();
      await refreshShell();
      if (finalRunId) {
        setSelectedRunId(finalRunId);
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

  async function handleSubmitParameterExperiment(values: Record<string, unknown>) {
    setSubmitting('experiment');
    try {
      const result = await postParameterExperiment({
        experiment_id: values.experiment_id,
        snapshot_id: values.snapshot_id,
        search_type: values.search_type,
        fast_periods: parseIntegerList(values.fast_periods),
        slow_periods: parseIntegerList(values.slow_periods),
        max_samples: values.max_samples,
        qty_policy_ref: 'percent_of_cash',
        cash_allocation_pct: 100,
        initial_cash: 10000,
        leverage: 1,
        fee_rate: 0,
        slippage_bps: 0,
        min_notional: 0,
        benchmark: 'buy_and_hold',
      });
      const experimentId = String(result.experiment_id ?? '');
      setLastActionResult(`参数实验已提交：${experimentId}`);
      message.success(`参数实验已提交：${experimentId}`);
      const experimentsPayload = await loadParameterExperiments();
      applyPayloadMeta(experimentsPayload);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setSelectedExperimentId(ALL_EXPERIMENTS);
      setError(null);
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '参数实验提交失败';
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
      [row.run_id, row.dataset_snapshot_id, row.symbol, row.strategy_name, row.timeframe].join(' ').toLowerCase().includes(query)
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
              datasets={datasets}
              rows={filteredParameterRows}
              allRows={parameterLab.rows}
              fastRows={parameterLab.fast_period_total_return}
              slowRows={parameterLab.slow_period_total_return}
              experiments={parameterExperiments}
              selectedExperimentId={selectedExperimentId}
              setSelectedExperimentId={setSelectedExperimentId}
              selectedExperimentDetail={selectedExperimentDetail}
              experimentDetailLoading={experimentDetailLoading}
              parameterQuery={parameterQuery}
              setParameterQuery={setParameterQuery}
              experimentForm={experimentForm}
              submitting={submitting}
              onSubmitExperiment={handleSubmitParameterExperiment}
              onOpenRun={(runId) => {
                setSelectedRunId(runId);
                setActiveTab('analysis');
              }}
              onRefreshExperiments={async () => {
                const [experimentPayload, parameterPayload] = await Promise.all([
                  loadParameterExperiments(),
                  loadParameters(),
                ]);
                applyPayloadMeta(experimentPayload);
                setParameterExperiments(experimentPayload.parameter_experiments);
                setParameterLab(parameterPayload.parameter_lab);
                if (selectedExperimentId !== ALL_EXPERIMENTS) {
                  const detailPayload = await loadParameterExperimentDetail(selectedExperimentId);
                  applyPayloadMeta(detailPayload);
                  setSelectedExperimentDetail(detailPayload.parameter_experiment);
                }
              }}
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
  submitting: 'ingest' | 'run' | 'experiment' | null;
  deletingDatasetId: string | null;
  deletingRunId: string | null;
  onIngest: (values: Record<string, unknown>) => Promise<void>;
  onRun: (values: Record<string, unknown>) => Promise<void>;
  onDeleteDataset: (snapshotId: string) => Promise<void>;
}) {
  const selectedDatasetKey = Form.useWatch('dataset_key', runForm) as string | undefined;
  const selectedRunTimeframes = (Form.useWatch('timeframes', runForm) as string[] | undefined) ?? [];
  const [isDatasetModalOpen, setIsDatasetModalOpen] = useState(false);
  const [datasetTimeframeFilter, setDatasetTimeframeFilter] = useState<string>('all');
  const [datasetExchangeFilter, setDatasetExchangeFilter] = useState<string>('all');
  const [datasetQuery, setDatasetQuery] = useState('');
  const datasetGroupOptions = useMemo(
    () => datasets
      .map((snapshot) => ({
        label: buildDatasetGroupLabel(snapshot),
        value: buildDatasetGroupKey(snapshot),
      }))
      .filter((entry, index, entries) => entries.findIndex((candidate) => candidate.value === entry.value) === index)
      .sort((left, right) => left.label.localeCompare(right.label, 'zh-Hans-CN')),
    [datasets],
  );
  const snapshotsForSelectedDataset = useMemo(
    () => selectedDatasetKey
      ? datasets.filter((snapshot) => buildDatasetGroupKey(snapshot) === selectedDatasetKey)
      : [],
    [datasets, selectedDatasetKey],
  );
  const timeframeOptions = useMemo(
    () => [...new Set(snapshotsForSelectedDataset.map((snapshot) => snapshot.timeframe))]
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right, 'en', { numeric: true }))
      .map((timeframe) => ({
        label: timeframe.toUpperCase(),
        value: timeframe,
      })),
    [snapshotsForSelectedDataset],
  );
  const selectedSnapshots = useMemo(
    () => snapshotsForSelectedDataset.filter((snapshot) => selectedRunTimeframes.includes(snapshot.timeframe)),
    [selectedRunTimeframes, snapshotsForSelectedDataset],
  );
  const datasetTableTimeframeOptions = useMemo(
    () => [...new Set(datasets.map((snapshot) => snapshot.timeframe))]
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right, 'en', { numeric: true }))
      .map((timeframe) => ({ label: timeframe.toUpperCase(), value: timeframe })),
    [datasets],
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
    if (!selectedDatasetKey && datasetGroupOptions[0]?.value) {
      runForm.setFieldValue('dataset_key', datasetGroupOptions[0].value);
    }
  }, [datasetGroupOptions, runForm, selectedDatasetKey]);

  useEffect(() => {
    if (!timeframeOptions.length) {
      if (selectedRunTimeframes.length) {
        runForm.setFieldValue('timeframes', []);
      }
      return;
    }
    const validTimeframes = selectedRunTimeframes.filter((timeframe) => timeframeOptions.some((option) => option.value === timeframe));
    if (!validTimeframes.length) {
      runForm.setFieldValue('timeframes', [timeframeOptions[0].value]);
      return;
    }
    if (validTimeframes.length !== selectedRunTimeframes.length) {
      runForm.setFieldValue('timeframes', validTimeframes);
    }
  }, [runForm, selectedRunTimeframes, timeframeOptions]);

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
              since: dayjs('2024-01-01T00:00:00+08:00'),
              until: dayjs('2024-01-03T00:00:00+08:00'),
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
                <Form.Item name="since" label="开始时间（北京时间）" rules={[{ required: true }]}>
                  <DatePicker
                    showTime
                    format="YYYY-MM-DD HH:mm:ss"
                    style={{ width: '100%' }}
                    placeholder="选择开始时间"
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="until" label="结束时间（北京时间）">
                  <DatePicker
                    showTime
                    format="YYYY-MM-DD HH:mm:ss"
                    style={{ width: '100%' }}
                    placeholder="选择结束时间"
                  />
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
              dataset_key: datasetGroupOptions[0]?.value,
              timeframes: timeframeOptions[0] ? [timeframeOptions[0].value] : [],
              fast_period: 2,
              slow_period: 3,
              cash_allocation_pct: 100,
              initial_cash: 10000,
              leverage: 1,
              fee_rate: 0,
              slippage_bps: 0,
              min_notional: 0,
            }}
            onFinish={(values) => void onRun({
              ...(values as Record<string, unknown>),
              snapshot_ids: selectedSnapshots.map((snapshot) => snapshot.dataset_snapshot_id),
            } as Record<string, unknown>)}
          >
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="dataset_key" label="数据集" rules={[{ required: true }]}>
                  <Select
                    options={datasetGroupOptions}
                    placeholder="先选择标的数据集"
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              </Col>
              <Col span={16}>
                <Form.Item name="timeframes" label="周期（可多选）" rules={[{ required: true }]}>
                  <Select
                    mode="multiple"
                    options={timeframeOptions}
                    placeholder={timeframeOptions.length ? '选择一个或多个周期' : '当前数据集暂无周期'}
                    notFoundContent="当前数据集暂无周期"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Paragraph type="secondary">
              当前会根据所选周期串行发起回测，并自动匹配对应数据快照：
              {selectedSnapshots.length
                ? ` ${selectedSnapshots.map((snapshot) => `${snapshot.timeframe.toUpperCase()} -> ${snapshot.dataset_snapshot_id}`).join('；')}`
                : ' 暂无匹配快照'}
            </Paragraph>
            <Form.Item name="run_id" label="运行 ID 前缀" rules={[{ required: true }]}>
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
                <Form.Item name="cash_allocation_pct" label="资金使用比例 (%)" rules={[{ required: true }]}>
                  <InputNumber min={0.01} max={100} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="initial_cash" label="初始资金">
                  <InputNumber min={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="leverage" label="杠杆倍数">
                  <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
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
              串行运行回测
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
    {
      id: 'timeframe',
      header: '周期',
      accessorFn: (row) => row.timeframe,
      cell: ({ row }) => row.original.timeframe.toUpperCase(),
    },
    { header: '策略', accessorKey: 'strategy_name' },
    { header: '快 / 慢', cell: ({ row }) => `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}` },
    { header: '杠杆', cell: ({ row }) => row.original.leverage ?? '--' },
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
    name: `${shortRunId(runId)} · ${summaryByRunId.get(runId)?.symbol ?? '未知标的'} · ${(summaryByRunId.get(runId)?.timeframe ?? '').toUpperCase()}`,
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
                placeholder="搜索 run / 数据集 / 标的 / 周期"
                value={overviewQuery}
                onChange={(event) => setOverviewQuery(event.target.value)}
              />
              <Select
                mode="multiple"
                value={compareRunIds}
                style={{ minWidth: 320 }}
                onChange={setCompareRunIds}
                options={chartOptions.slice(0, 12).map((summary) => ({
                  label: `${shortRunId(summary.run_id)} · ${summary.symbol} · ${summary.timeframe.toUpperCase()}`,
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
              xaxis: { title: '时间（北京时间）' },
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
  const equityChartRows = useMemo(
    () => pickChartSamples(selectedRun?.equity_rows ?? [], 1500),
    [selectedRun],
  );
  const tradeSideOptions = Array.from(new Set(tradeRows.map((row) => row.side))).sort();
  const tradeSummaryStats = useMemo(() => {
    const closedTrades = tradeRows.filter((row) => row.exit_time !== null);
    const openTrades = tradeRows.filter((row) => row.exit_time === null);
    const winningTrades = closedTrades.filter((row) => row.net_pnl > 0);
    const losingTrades = closedTrades.filter((row) => row.net_pnl < 0);
    const avgNetPnl = closedTrades.length
      ? closedTrades.reduce((sum, row) => sum + row.net_pnl, 0) / closedTrades.length
      : null;
    const avgWin = winningTrades.length
      ? winningTrades.reduce((sum, row) => sum + row.net_pnl, 0) / winningTrades.length
      : null;
    const avgLoss = losingTrades.length
      ? losingTrades.reduce((sum, row) => sum + row.net_pnl, 0) / losingTrades.length
      : null;
    const payoffRatio = avgWin !== null && avgLoss !== null && avgLoss !== 0
      ? avgWin / Math.abs(avgLoss)
      : null;
    const maxWin = winningTrades.length
      ? Math.max(...winningTrades.map((row) => row.net_pnl))
      : null;
    const maxLoss = losingTrades.length
      ? Math.min(...losingTrades.map((row) => row.net_pnl))
      : null;

    return [
      { title: '总交易数', value: String(tradeRows.length), tone: 'neutral' },
      { title: '盈利笔数', value: String(winningTrades.length), tone: 'positive' },
      { title: '亏损笔数', value: String(losingTrades.length), tone: 'negative' },
      { title: '未平仓笔数', value: String(openTrades.length), tone: 'neutral' },
      { title: '胜率', value: formatPct(closedTrades.length ? winningTrades.length / closedTrades.length : null), tone: 'positive' },
      { title: '平均单笔收益', value: formatNumber(avgNetPnl), tone: avgNetPnl !== null && avgNetPnl < 0 ? 'negative' : avgNetPnl !== null && avgNetPnl > 0 ? 'positive' : 'neutral' },
      { title: '平均盈利', value: formatNumber(avgWin), tone: 'positive' },
      { title: '平均亏损', value: formatNumber(avgLoss), tone: 'negative' },
      { title: '盈亏比', value: formatNumber(payoffRatio), tone: payoffRatio !== null && payoffRatio < 1 ? 'negative' : payoffRatio !== null && payoffRatio > 1 ? 'positive' : 'neutral' },
      { title: '最大单笔盈利', value: formatNumber(maxWin), tone: 'positive' },
      { title: '最大单笔亏损', value: formatNumber(maxLoss), tone: 'negative' },
    ];
  }, [tradeRows]);
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
                  label: `${shortRunId(run.run_id)} · ${run.symbol} · ${run.timeframe.toUpperCase()}`,
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
            仅展示当前策略账户权益随时间的变化，便于单次 run 的资金演进查看。大样本会自动抽样显示，减轻切换卡顿。
          </Paragraph>
          <LazyPlot
            data={[
              {
                x: equityChartRows.map((row) => row.timestamp),
                y: equityChartRows.map((row) => row.strategy_equity),
                type: equityChartRows.length > 1000 ? 'scattergl' : 'scatter',
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
              xaxis: { title: '时间（北京时间）' },
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
            <Descriptions.Item label="标的 / 周期">{`${selectedRun.symbol} · ${selectedRun.timeframe.toUpperCase()}`}</Descriptions.Item>
            <Descriptions.Item label="数据快照">{selectedRun.dataset_snapshot_id}</Descriptions.Item>
            <Descriptions.Item label="策略版本">{selectedRun.manifest.strategy_version}</Descriptions.Item>
            <Descriptions.Item label="执行策略">
              {formatAnalysisFieldValue('execution_policy_id', selectedRun.manifest.execution_policy_id)}
            </Descriptions.Item>
            <Descriptions.Item label="指标策略">
              {formatAnalysisFieldValue('metric_policy_id', selectedRun.manifest.metric_policy_id)}
            </Descriptions.Item>
            <Descriptions.Item label="特征产物">{selectedRun.manifest.feature_artifact_id}</Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="策略参数与执行约束">
          <Descriptions column={1} size="small">
            {Object.entries(strategyParams ?? {}).map(([key, value]) => (
              <Descriptions.Item key={key} label={labelAnalysisField(key)}>
                {formatAnalysisFieldValue(key, value)}
              </Descriptions.Item>
            ))}
            {Object.entries(executionConstraints ?? {}).map(([key, value]) => (
              <Descriptions.Item key={key} label={labelAnalysisField(key)}>
                {formatAnalysisFieldValue(key, value)}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
      </Col>

      <Col span={24}>
        <Card title="交易统计汇总">
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            基于当前 run 的全部交易记录计算。
          </Paragraph>
          <Row gutter={[10, 10]}>
            {tradeSummaryStats.map((item) => (
              <Col xs={12} sm={8} lg={6} xl={4} xxl={3} key={item.title}>
                <Card size="small" className="cbw-summary-card">
                  <Statistic
                    className="cbw-summary-stat"
                    title={item.title}
                    value={item.value}
                    valueStyle={{
                      color: item.tone === 'positive'
                        ? '#16a34a'
                        : item.tone === 'negative'
                          ? '#dc2626'
                          : '#101828',
                    }}
                  />
                </Card>
              </Col>
            ))}
          </Row>
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
  datasets,
  rows,
  allRows,
  fastRows,
  slowRows,
  experiments,
  selectedExperimentId,
  setSelectedExperimentId,
  selectedExperimentDetail,
  experimentDetailLoading,
  parameterQuery,
  setParameterQuery,
  experimentForm,
  submitting,
  onSubmitExperiment,
  onOpenRun,
  onRefreshExperiments,
}: {
  datasets: DatasetSnapshotView[];
  rows: ParameterLabRow[];
  allRows: ParameterLabRow[];
  fastRows: SensitivityRow[];
  slowRows: SensitivityRow[];
  experiments: ParameterExperimentSummary[];
  selectedExperimentId: string;
  setSelectedExperimentId: (value: string) => void;
  selectedExperimentDetail: ParameterExperimentDetail | null;
  experimentDetailLoading: boolean;
  parameterQuery: string;
  setParameterQuery: (value: string) => void;
  experimentForm: ReturnType<typeof Form.useForm>[0];
  submitting: 'ingest' | 'run' | 'experiment' | null;
  onSubmitExperiment: (values: Record<string, unknown>) => Promise<void>;
  onOpenRun: (runId: string) => void;
  onRefreshExperiments: () => Promise<void>;
}) {
  const experimentSearchType = Form.useWatch('search_type', experimentForm) as string | undefined;
  const [experimentRunQuery, setExperimentRunQuery] = useState('');
  const datasetOptions = useMemo(
    () => datasets.map((snapshot) => ({
      label: `${snapshot.dataset_snapshot_id} · ${snapshot.symbol} · ${snapshot.timeframe.toUpperCase()}`,
      value: snapshot.dataset_snapshot_id,
    })),
    [datasets],
  );

  useEffect(() => {
    if (!experimentForm.getFieldValue('snapshot_id') && datasets[0]?.dataset_snapshot_id) {
      experimentForm.setFieldValue('snapshot_id', datasets[0].dataset_snapshot_id);
    }
    if (!experimentForm.getFieldValue('experiment_id')) {
      experimentForm.setFieldValue('experiment_id', `experiment-${dayjs().format('YYYYMMDDHHmmss')}`);
    }
    if (!experimentForm.getFieldValue('search_type')) {
      experimentForm.setFieldValue('search_type', 'grid');
    }
    if (!experimentForm.getFieldValue('fast_periods')) {
      experimentForm.setFieldValue('fast_periods', '2,3,5,8');
    }
    if (!experimentForm.getFieldValue('slow_periods')) {
      experimentForm.setFieldValue('slow_periods', '13,21,34');
    }
  }, [datasets, experimentForm]);

  useEffect(() => {
    if (experimentSearchType === 'grid') {
      experimentForm.setFieldValue('max_samples', undefined);
    }
  }, [experimentForm, experimentSearchType]);

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

  const selectedExperimentSummary = useMemo(
    () => (selectedExperimentId === ALL_EXPERIMENTS
      ? null
      : experiments.find((experiment) => experiment.experiment_id === selectedExperimentId) ?? null),
    [experiments, selectedExperimentId],
  );
  const selectedExperimentRows = useMemo(() => {
    if (selectedExperimentId === ALL_EXPERIMENTS) {
      return allRows;
    }
    const runIds = selectedExperimentDetail?.execution.run_ids ?? [];
    if (!runIds.length) {
      return [];
    }
    const rowsByRunId = new Map(allRows.map((row) => [row.run_id, row] as const));
    return runIds
      .map((runId) => rowsByRunId.get(runId))
      .filter((row): row is ParameterLabRow => row !== undefined);
  }, [allRows, selectedExperimentDetail, selectedExperimentId]);
  const filteredExperimentRows = useMemo(() => {
    const query = experimentRunQuery.trim().toLowerCase();
    if (!query) {
      return selectedExperimentRows;
    }
    return selectedExperimentRows.filter((row) => (
      [
        row.run_id,
        row.symbol,
        row.timeframe,
        row.dataset_snapshot_id,
        row.fast_period,
        row.slow_period,
      ].join(' ').toLowerCase().includes(query)
    ));
  }, [experimentRunQuery, selectedExperimentRows]);
  const failedChildTaskIds = selectedExperimentDetail?.execution.failed_child_task_ids ?? [];
  const experimentResultColumns = useMemo<ColumnDef<ParameterLabRow>[]>(() => [
    {
      header: 'Run',
      accessorKey: 'run_id',
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{row.original.symbol}</Text>
        </Space>
      ),
    },
    {
      id: 'timeframe',
      header: '周期',
      accessorFn: (row) => row.timeframe,
      cell: ({ row }) => row.original.timeframe.toUpperCase(),
    },
    {
      id: 'fast_slow',
      header: '快 / 慢',
      accessorFn: (row) => `${row.fast_period ?? ''}/${row.slow_period ?? ''}`,
      cell: ({ row }) => `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}`,
    },
    { id: 'leverage', header: '杠杆', accessorFn: (row) => row.leverage ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.leverage ?? '--' },
    { id: 'total_return', header: '收益率', accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    { id: 'excess_return', header: '超额收益', accessorFn: (row) => row.excess_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.excess_return) },
    { id: 'final_equity', header: '最终权益', accessorFn: (row) => row.final_equity, cell: ({ row }) => formatNumber(row.original.final_equity) },
    { id: 'trade_count', header: '交易数', accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    { id: 'win_rate', header: '胜率', accessorFn: (row) => row.win_rate, cell: ({ row }) => formatPct(row.original.win_rate) },
    {
      id: 'actions',
      header: '操作',
      enableSorting: false,
      cell: ({ row }) => <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开分析</Button>,
    },
  ], [onOpenRun]);
  const experimentColumns = useMemo<ColumnDef<ParameterExperimentSummary>[]>(() => [
    {
      header: '实验 ID',
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.original.experiment_id}</Text>
          <Text type="secondary">{row.original.task_id ?? '--'}</Text>
        </Space>
      ),
    },
    { header: '模式', cell: ({ row }) => experimentSearchTypeLabel(row.original.search_type) },
    { header: '计划 / 已完成', cell: ({ row }) => `${row.original.planned_run_count} / ${row.original.run_count}` },
    { header: '失败数', accessorKey: 'failed_run_count' },
    {
      header: '状态',
      cell: ({ row }) => {
        const status = row.original.status;
        return <Tag color={experimentStatusColor(status)}>{status}</Tag>;
      },
    },
    { id: 'created_at', header: '提交时间', accessorFn: (row) => row.created_at, cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: 'actions',
      header: '操作',
      enableSorting: false,
      cell: ({ row }) => (
        <Button size="small" type={row.original.experiment_id === selectedExperimentId ? 'primary' : 'default'} onClick={() => setSelectedExperimentId(row.original.experiment_id)}>
          查看结果
        </Button>
      ),
    },
  ], [selectedExperimentId, setSelectedExperimentId]);

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

      <Col span={24}>
        <Card
          title="实验结果查看"
          extra={(
            <Space wrap>
              <Select
                value={selectedExperimentId}
                style={{ minWidth: 360 }}
                placeholder="选择参数实验范围"
                onChange={setSelectedExperimentId}
                options={[
                  { label: '全部实验', value: ALL_EXPERIMENTS },
                  ...experiments.map((experiment) => ({
                    label: `${experiment.experiment_id} · ${experimentSearchTypeLabel(experiment.search_type)} · ${experiment.status}`,
                    value: experiment.experiment_id,
                  })),
                ]}
              />
              {selectedExperimentSummary ? (
                <Tag color={experimentStatusColor(selectedExperimentSummary.status)}>{selectedExperimentSummary.status}</Tag>
              ) : null}
            </Space>
          )}
        >
          {!experiments.length ? (
            <Alert type="info" showIcon message="当前还没有可查看的参数实验" />
          ) : (
            <Spin spinning={experimentDetailLoading}>
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {selectedExperimentId === ALL_EXPERIMENTS
                    ? '当前展示全部实验的汇总结果，适合先整体排序筛选，再进入单次分析。'
                    : '这里直接消费实验详情与子 run 结果，方便按指标排序后快速跳转到单次分析。'}
                </Paragraph>
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="实验数" value={selectedExperimentId === ALL_EXPERIMENTS ? experiments.length : 1} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="计划组合" value={selectedExperimentId === ALL_EXPERIMENTS ? experiments.reduce((sum, experiment) => sum + experiment.planned_run_count, 0) : (selectedExperimentDetail?.execution.planned_run_count ?? selectedExperimentSummary?.planned_run_count ?? 0)} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="已生成 Run" value={selectedExperimentId === ALL_EXPERIMENTS ? selectedExperimentRows.length : (selectedExperimentDetail?.execution.run_ids?.length ?? selectedExperimentSummary?.run_count ?? 0)} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="失败子任务" value={selectedExperimentId === ALL_EXPERIMENTS ? experiments.reduce((sum, experiment) => sum + experiment.failed_run_count, 0) : (failedChildTaskIds.length || selectedExperimentSummary?.failed_run_count || 0)} /></Card></Col>
                </Row>
                {selectedExperimentId !== ALL_EXPERIMENTS ? (
                  <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                    <Descriptions.Item label="实验 ID">{selectedExperimentDetail?.experiment.experiment_id ?? selectedExperimentId}</Descriptions.Item>
                    <Descriptions.Item label="搜索方式">{experimentSearchTypeLabel(selectedExperimentDetail?.experiment.search_type ?? selectedExperimentSummary?.search_type)}</Descriptions.Item>
                    <Descriptions.Item label="数据集">{selectedExperimentDetail?.experiment.dataset_bundle_id ?? selectedExperimentSummary?.dataset_bundle_id ?? '--'}</Descriptions.Item>
                    <Descriptions.Item label="父任务">{selectedExperimentDetail?.execution.task_id ?? selectedExperimentSummary?.task_id ?? '--'}</Descriptions.Item>
                    <Descriptions.Item label="提交时间">{selectedExperimentDetail?.experiment.created_at ? formatDateTime(selectedExperimentDetail.experiment.created_at) : (selectedExperimentSummary ? formatDateTime(selectedExperimentSummary.created_at) : '--')}</Descriptions.Item>
                    <Descriptions.Item label="随机种子策略">{selectedExperimentDetail?.experiment.seed_policy ?? '--'}</Descriptions.Item>
                  </Descriptions>
                ) : null}
                {selectedExperimentId !== ALL_EXPERIMENTS && failedChildTaskIds.length ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={`有 ${failedChildTaskIds.length} 个子任务失败`}
                    description={`失败任务：${failedChildTaskIds.join('，')}`}
                  />
                ) : null}
                <Card
                  size="small"
                  title="子 Run 结果"
                  extra={(
                    <Input
                      placeholder="搜索 run / 标的 / 周期 / 参数"
                      value={experimentRunQuery}
                      onChange={(event) => setExperimentRunQuery(event.target.value)}
                      style={{ width: 260 }}
                    />
                  )}
                >
                  <Paragraph type="secondary">
                    当前显示 {filteredExperimentRows.length} / {selectedExperimentRows.length} 条已落盘 run。可按收益率、超额收益、最终权益、胜率直接排序。
                  </Paragraph>
                  <DataTable
                    columns={experimentResultColumns}
                    data={filteredExperimentRows}
                    initialPageSize={8}
                    pageSizeOptions={[8, 16, 32]}
                    initialSorting={[{ id: 'total_return', desc: true }]}
                  />
                </Card>
              </Space>
            </Spin>
          )}
        </Card>
      </Col>

      <Col span={24}>
        <Card title="发起参数实验" extra={<Button onClick={() => void onRefreshExperiments()}>刷新实验状态</Button>}>
          <Paragraph type="secondary">
            当前版本严格收敛在设计文档边界内：仅支持 EMA、单数据快照、`grid/random` 两种搜索方式。
          </Paragraph>
          <Form form={experimentForm} layout="vertical" onFinish={(values) => void onSubmitExperiment(values as Record<string, unknown>)}>
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item name="experiment_id" label="实验 ID" rules={[{ required: true, whitespace: true, message: '请输入实验 ID' }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="snapshot_id" label="数据快照" rules={[{ required: true }]}>
                  <Select options={datasetOptions} showSearch optionFilterProp="label" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="search_type" label="搜索方式" rules={[{ required: true }]}>
                  <Select
                    options={[
                      { label: '网格搜索', value: 'grid' },
                      { label: '随机搜索', value: 'random' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="fast_periods"
                  label="快线候选"
                  rules={[
                    {
                      validator: async (_, value) => {
                        const message = validateIntegerListInput(value, '快线候选');
                        if (message) {
                          throw new Error(message);
                        }
                        const slowValue = experimentForm.getFieldValue('slow_periods');
                        const slowMessage = validateIntegerListInput(slowValue, '慢线候选');
                        if (!slowMessage) {
                          const fastPeriods = parseIntegerList(value);
                          const slowPeriods = parseIntegerList(slowValue);
                          const invalidPair = fastPeriods.flatMap((fastPeriod) => (
                            slowPeriods.filter((slowPeriod) => fastPeriod >= slowPeriod).map((slowPeriod) => `${fastPeriod}/${slowPeriod}`)
                          ))[0];
                          if (invalidPair) {
                            throw new Error(`所有组合都必须满足快线周期 < 慢线周期，当前存在 ${invalidPair}`);
                          }
                        }
                      },
                    },
                  ]}
                >
                  <Input placeholder="例如 2,3,5,8" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="slow_periods"
                  label="慢线候选"
                  rules={[
                    {
                      validator: async (_, value) => {
                        const message = validateIntegerListInput(value, '慢线候选');
                        if (message) {
                          throw new Error(message);
                        }
                        const fastValue = experimentForm.getFieldValue('fast_periods');
                        const fastMessage = validateIntegerListInput(fastValue, '快线候选');
                        if (!fastMessage) {
                          const fastPeriods = parseIntegerList(fastValue);
                          const slowPeriods = parseIntegerList(value);
                          const invalidPair = fastPeriods.flatMap((fastPeriod) => (
                            slowPeriods.filter((slowPeriod) => fastPeriod >= slowPeriod).map((slowPeriod) => `${fastPeriod}/${slowPeriod}`)
                          ))[0];
                          if (invalidPair) {
                            throw new Error(`所有组合都必须满足快线周期 < 慢线周期，当前存在 ${invalidPair}`);
                          }
                        }
                      },
                    },
                  ]}
                >
                  <Input placeholder="例如 13,21,34" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="max_samples"
                  label="随机搜索样本数"
                  rules={[
                    {
                      validator: async (_, value) => {
                        if (experimentSearchType !== 'random') {
                          return;
                        }
                        if (value === null || value === undefined || value === '') {
                          throw new Error('随机搜索时必须填写样本数');
                        }
                        if (Number(value) <= 0) {
                          throw new Error('随机搜索样本数必须大于 0');
                        }
                      },
                    },
                  ]}
                >
                  <InputNumber min={1} disabled={experimentSearchType !== 'random'} style={{ width: '100%' }} placeholder="仅随机搜索时生效" />
                </Form.Item>
              </Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={submitting === 'experiment'}>
              提交参数实验
            </Button>
          </Form>
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

      <Col span={24}>
        <Card title="最近实验任务">
          <DataTable
            columns={experimentColumns}
            data={experiments}
            initialPageSize={8}
            pageSizeOptions={[8, 16, 24]}
            initialSorting={[{ id: 'created_at', desc: true }]}
          />
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
