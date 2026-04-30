import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
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
  Tooltip,
  Typography,
  theme,
} from 'antd';
import { DataTable } from './components/DataTable';
import { LazyPlot } from './components/LazyPlot';
import {
  deleteDataset,
  deleteParameterExperiment,
  deleteParameterExperimentBatch,
  deleteRun,
  loadDatasets,
  loadParameterExperimentBatchDetail,
  loadParameterExperimentBatches,
  loadParameterExperimentDetail,
  loadParameterExperiments,
  loadOverview,
  loadOverviewEquity,
  loadParameters,
  loadResearchNotes,
  loadRunDetail,
  loadRuns,
  postIngest,
  postParameterExperimentBatch,
  postResearchNote,
  postRunEma,
} from './lib/api';
import { formatDateRange, formatDateTime, formatNumber, formatPct, shortRunId } from './lib/format';
import type {
  DatasetSnapshotView,
  ParameterExperimentBatchDetail,
  ParameterExperimentBatchSummary,
  ParameterExperimentDetail,
  ParameterExperimentSummary,
  ParameterLabRow,
  ResearchNote,
  RunAnalysisView,
  RunSummaryView,
  SensitivityRow,
  MultiRunEquityRow,
  WorkspaceParameterLab,
  WorkspaceOverview,
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

interface AutoLabelInfo {
  label: string;
  reason: string;
}

const TAB_OPTIONS = [
  { label: '执行台', value: 'execution' },
  { label: '运行总览', value: 'overview' },
  { label: '单次分析', value: 'analysis' },
  { label: '参数实验', value: 'parameters' },
] satisfies Array<{ label: string; value: TabId }>;

const ALL_EXPERIMENTS = '__all__';
const ALL_BATCHES = '__all_batches__';
const RESEARCH_LABEL_OPTIONS = [
  { label: '基准', value: 'baseline' },
  { label: '候选', value: 'candidate' },
  { label: '稳健候选', value: 'robust_candidate' },
  { label: '高收益候选', value: 'high_return_candidate' },
  { label: '待复核', value: 'review' },
  { label: '排除', value: 'excluded' },
];
const RESEARCH_LABEL_TEXT: Record<string, string> = {
  baseline: '基准',
  candidate: '候选',
  robust_candidate: '稳健候选',
  high_return_candidate: '高收益候选',
  review: '待复核',
  excluded: '排除',
};
const DECISION_STATUS_OPTIONS = [
  { label: '候选', value: 'candidate' },
  { label: '观察', value: 'observing' },
  { label: '通过', value: 'approved' },
  { label: '拒绝', value: 'rejected' },
  { label: '归档', value: 'archived' },
];
const DECISION_STATUS_TEXT: Record<string, string> = {
  candidate: '候选',
  observing: '观察',
  approved: '通过',
  rejected: '拒绝',
  archived: '归档',
};
const DECISION_STATUS_COLOR: Record<string, string> = {
  candidate: 'blue',
  observing: 'purple',
  approved: 'green',
  rejected: 'red',
  archived: 'default',
};
const AUTO_GROUP_MEMBERSHIP_LABEL_TEXT: Record<string, string> = {
  auto_robust_candidate: '所属稳健参数组',
  auto_high_return_candidate: '所属高收益参数组',
  auto_exploratory_candidate: '所属探索参数组',
  auto_excluded: '所属排除参数组',
};

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

function researchLabelText(value: string): string {
  return RESEARCH_LABEL_TEXT[value] ?? value;
}

function decisionStatusText(value: string | null | undefined): string {
  return value ? (DECISION_STATUS_TEXT[value] ?? value) : '候选';
}

function decisionStatusColor(value: string | null | undefined): string {
  return value ? (DECISION_STATUS_COLOR[value] ?? 'blue') : 'blue';
}

function targetTypeText(value: string): string {
  if (value === 'run') {
    return 'Run';
  }
  if (value === 'parameter_experiment') {
    return '单实验';
  }
  if (value === 'parameter_experiment_batch') {
    return '实验批次';
  }
  if (value === 'parameter_group') {
    return '参数组';
  }
  return value;
}

function isInactiveDecisionStatus(value: string | null | undefined): boolean {
  return value === 'rejected' || value === 'archived';
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

function normalizeRatioValue(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') {
    return undefined;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
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

function buildParameterGroupTargetId(batchId: string, group: { fast_period: number | null; slow_period: number | null; leverage: number | null }): string {
  return `${batchId}:f${group.fast_period ?? 'na'}:s${group.slow_period ?? 'na'}:l${group.leverage ?? 'na'}`;
}

function buildParameterGroupKey(group: { fast_period: number | null | undefined; slow_period: number | null | undefined; leverage: number | null | undefined }): string {
  return `${group.fast_period ?? 'na'}:${group.slow_period ?? 'na'}:${group.leverage ?? 'na'}`;
}

function parseIntegerList(value: unknown): number[] {
  return String(value ?? '')
    .split(',')
    .map((entry) => Number.parseInt(entry.trim(), 10))
    .filter((entry) => Number.isFinite(entry) && entry > 0);
}

function parsePositiveNumberList(value: unknown): number[] {
  return String(value ?? '')
    .split(',')
    .map((entry) => Number.parseFloat(entry.trim()))
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

function validatePositiveNumberListInput(value: unknown, fieldLabel: string): string | null {
  const raw = String(value ?? '').trim();
  if (!raw) {
    return `请输入${fieldLabel}`;
  }
  const parts = raw.split(',').map((entry) => entry.trim()).filter(Boolean);
  if (!parts.length) {
    return `请输入${fieldLabel}`;
  }
  const parsed = parts.map((entry) => Number.parseFloat(entry));
  if (parsed.some((entry) => !Number.isFinite(entry) || entry <= 0)) {
    return `${fieldLabel}必须是逗号分隔的正数`;
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
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [overviewEquityRows, setOverviewEquityRows] = useState<MultiRunEquityRow[]>([]);
  const [parameterLab, setParameterLab] = useState<WorkspaceParameterLab | null>(null);
  const [parameterExperiments, setParameterExperiments] = useState<ParameterExperimentSummary[]>([]);
  const [parameterExperimentBatches, setParameterExperimentBatches] = useState<ParameterExperimentBatchSummary[]>([]);
  const [researchNotes, setResearchNotes] = useState<ResearchNote[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState(ALL_BATCHES);
  const [selectedBatchDetail, setSelectedBatchDetail] = useState<ParameterExperimentBatchDetail | null>(null);
  const [selectedExperimentId, setSelectedExperimentId] = useState(ALL_EXPERIMENTS);
  const [selectedExperimentDetail, setSelectedExperimentDetail] = useState<ParameterExperimentDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunAnalysisView | null>(null);
  const [runDetailCache, setRunDetailCache] = useState<Record<string, RunAnalysisView>>({});
  const [error, setError] = useState<string | null>(null);
  const [shellLoading, setShellLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [experimentDetailLoading, setExperimentDetailLoading] = useState(false);
  const [overviewEquityLoading, setOverviewEquityLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>(initialState.tab);
  const [selectedRunId, setSelectedRunId] = useState<string>(initialState.run);
  const [compareRunIds, setCompareRunIds] = useState<string[]>(initialState.compare);
  const [selectedOverviewRunIds, setSelectedOverviewRunIds] = useState<string[]>([]);
  const [overviewLabelFilter, setOverviewLabelFilter] = useState<string[]>([]);
  const [overviewQuery, setOverviewQuery] = useState(initialState.overviewQuery);
  const [parameterQuery, setParameterQuery] = useState(initialState.parameterQuery);
  const [lastActionResult, setLastActionResult] = useState('');
  const [submitting, setSubmitting] = useState<'ingest' | 'run' | 'experiment' | null>(null);
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [bulkDeletingRuns, setBulkDeletingRuns] = useState(false);
  const [deletingExperimentId, setDeletingExperimentId] = useState<string | null>(null);
  const [deletingBatchId, setDeletingBatchId] = useState<string | null>(null);
  const [savingResearchNote, setSavingResearchNote] = useState(false);
  const attemptedParameterResultRefreshKeysRef = useRef<Set<string>>(new Set());
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
    setOverview(null);
    setOverviewEquityRows([]);
    setSelectedOverviewRunIds([]);
    attemptedParameterResultRefreshKeysRef.current.clear();
    setResearchNotes([]);
    setParameterLab(null);
    setParameterExperimentBatches([]);
    setSelectedBatchId(ALL_BATCHES);
    setSelectedBatchDetail(null);
    setParameterExperiments([]);
    setSelectedExperimentId(ALL_EXPERIMENTS);
    setSelectedExperimentDetail(null);
    setSelectedRun(null);
    setRunDetailCache({});
  }

  async function refreshShell() {
    setShellLoading(true);
    try {
      const [datasetsPayload, runsPayload, researchNotesPayload] = await Promise.all([loadDatasets(), loadRuns(), loadResearchNotes()]);
      setDatasets(datasetsPayload.datasets);
      setRuns(runsPayload.runs);
      setResearchNotes(researchNotesPayload.research_notes);
      applyPayloadMeta(runsPayload);
      setError(null);
    } catch (loadError: unknown) {
      setError(loadError instanceof Error ? loadError.message : '工作台加载失败');
    } finally {
      setShellLoading(false);
    }
  }

  async function refreshParameterWorkspaceMeta() {
    if (
      parameterLab === null
      && !parameterExperiments.length
      && !parameterExperimentBatches.length
      && selectedExperimentDetail === null
      && selectedBatchDetail === null
    ) {
      return;
    }

    const [experimentPayload, batchPayload] = await Promise.all([
      loadParameterExperiments(),
      loadParameterExperimentBatches(),
    ]);
    setParameterExperiments(experimentPayload.parameter_experiments);
    setParameterExperimentBatches(batchPayload.parameter_experiment_batches);

    if (selectedBatchId !== ALL_BATCHES) {
      const batchDetailPayload = await loadParameterExperimentBatchDetail(selectedBatchId);
      setSelectedBatchDetail(batchDetailPayload.parameter_experiment_batch);
    }

    if (selectedExperimentId !== ALL_EXPERIMENTS) {
      const detailPayload = await loadParameterExperimentDetail(selectedExperimentId);
      setSelectedExperimentDetail(detailPayload.parameter_experiment);
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
    if (!parameterExperimentBatches.length) {
      if (selectedBatchId !== ALL_BATCHES) {
        setSelectedBatchId(ALL_BATCHES);
      }
      setSelectedBatchDetail(null);
      return;
    }
    if (selectedBatchId !== ALL_BATCHES && !parameterExperimentBatches.some((batch) => batch.batch_id === selectedBatchId)) {
      setSelectedBatchId(ALL_BATCHES);
    }
  }, [activeTab, parameterExperimentBatches, selectedBatchId]);

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
          setOverviewEquityRows([]);
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
          const [parameterPayload, experimentPayload, batchPayload] = await Promise.all([
            loadParameters(),
            loadParameterExperiments(),
            loadParameterExperimentBatches(),
          ]);
          if (cancelled) {
            return;
          }
          applyPayloadMeta(parameterPayload);
          setParameterLab(parameterPayload.parameter_lab);
          setParameterExperiments(experimentPayload.parameter_experiments);
          setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
          setError(null);
          return;
        }

        if (activeTab === 'parameters' && parameterLab !== null && (!parameterExperiments.length || !parameterExperimentBatches.length)) {
          setSectionLoading(true);
          const [experimentPayload, batchPayload] = await Promise.all([
            loadParameterExperiments(),
            loadParameterExperimentBatches(),
          ]);
          if (cancelled) {
            return;
          }
          applyPayloadMeta(experimentPayload);
          setParameterExperiments(experimentPayload.parameter_experiments);
          setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
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
  }, [activeTab, overview, parameterExperimentBatches.length, parameterLab, parameterExperiments.length, runDetailCache, selectedRun, selectedRunId]);

  useEffect(() => {
    if (activeTab !== 'overview' || overview === null) {
      return;
    }
    const availableRunIds = new Set(overview.summaries.map((summary) => summary.run_id));
    const requestedRunIds = compareRunIds.filter((runId) => availableRunIds.has(runId));
    if (!requestedRunIds.length) {
      setOverviewEquityRows([]);
      return;
    }

    let cancelled = false;
    setOverviewEquityLoading(true);
    void loadOverviewEquity(requestedRunIds)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        applyPayloadMeta(payload);
        setOverviewEquityRows(payload.multi_run_equity);
        setError(null);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '资金曲线加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setOverviewEquityLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, compareRunIds, overview]);

  useEffect(() => {
    if (activeTab !== 'parameters' || selectedBatchId === ALL_BATCHES) {
      setSelectedBatchDetail(null);
      return;
    }
    let cancelled = false;

    async function loadSelectedBatchDetail() {
      try {
        setSelectedBatchDetail(null);
        setExperimentDetailLoading(true);
        const detailPayload = await loadParameterExperimentBatchDetail(selectedBatchId);
        if (cancelled) {
          return;
        }
        applyPayloadMeta(detailPayload);
        setSelectedBatchDetail(detailPayload.parameter_experiment_batch);
        setError(null);
      } catch (loadError: unknown) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '参数实验批次详情加载失败');
        }
      } finally {
        if (!cancelled) {
          setExperimentDetailLoading(false);
        }
      }
    }

    void loadSelectedBatchDetail();
    return () => {
      cancelled = true;
    };
  }, [activeTab, selectedBatchId]);

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
    const hasRunningExperiments = parameterExperiments.some((experiment) => experiment.status === 'pending' || experiment.status === 'running');
    const hasRunningBatches = parameterExperimentBatches.some((batch) => batch.status === 'pending' || batch.status === 'running');
    if (!hasRunningExperiments && !hasRunningBatches) {
      return;
    }
    const timer = window.setInterval(() => {
      void Promise.all([loadParameterExperiments(), loadParameterExperimentBatches()])
        .then(([experimentPayload, batchPayload]) => {
          applyPayloadMeta(experimentPayload);
          setParameterExperiments(experimentPayload.parameter_experiments);
          setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
          setError(null);
        })
        .catch((loadError: unknown) => {
          setError(loadError instanceof Error ? loadError.message : '参数实验状态刷新失败');
        });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeTab, parameterExperimentBatches, parameterExperiments]);

  const selectedExperimentSummary = useMemo(
    () => parameterExperiments.find((experiment) => experiment.experiment_id === selectedExperimentId) ?? null,
    [parameterExperiments, selectedExperimentId],
  );

  const selectedBatchSummary = useMemo(
    () => parameterExperimentBatches.find((batch) => batch.batch_id === selectedBatchId) ?? null,
    [parameterExperimentBatches, selectedBatchId],
  );

  useEffect(() => {
    if (activeTab !== 'parameters' || selectedBatchId === ALL_BATCHES) {
      return;
    }
    if (selectedBatchSummary?.status !== 'pending' && selectedBatchSummary?.status !== 'running') {
      return;
    }
    const timer = window.setInterval(() => {
      void loadParameterExperimentBatchDetail(selectedBatchId)
        .then((detailPayload) => {
          applyPayloadMeta(detailPayload);
          setSelectedBatchDetail(detailPayload.parameter_experiment_batch);
          setError(null);
        })
        .catch((loadError: unknown) => {
          setError(loadError instanceof Error ? loadError.message : '参数实验批次详情刷新失败');
        });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeTab, selectedBatchId, selectedBatchSummary?.status]);

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
    const refreshKey = [
      selectedExperimentDetail.experiment.experiment_id,
      selectedExperimentDetail.execution.status,
      selectedExperimentDetail.execution.updated_at ?? '',
      ...runIds,
    ].join('|');
    if (attemptedParameterResultRefreshKeysRef.current.has(refreshKey)) {
      return;
    }
    attemptedParameterResultRefreshKeysRef.current.add(refreshKey);
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
      const snapshotIds = Array.isArray(values.snapshot_ids)
        ? values.snapshot_ids.map((value) => String(value)).filter(Boolean)
        : [];
      if (!snapshotIds.length) {
        throw new Error('请至少选择一个数据快照');
      }
      const result = await postParameterExperimentBatch({
        batch_id: values.batch_id,
        snapshot_ids: snapshotIds,
        search_type: values.search_type,
        fast_periods: parseIntegerList(values.fast_periods),
        slow_periods: parseIntegerList(values.slow_periods),
        leverage_candidates: parsePositiveNumberList(values.leverage_candidates),
        max_samples: values.max_samples,
        qty_policy_ref: 'percent_of_cash',
        cash_allocation_pct: values.cash_allocation_pct,
        initial_cash: values.initial_cash,
        fee_rate: values.fee_rate,
        slippage_bps: values.slippage_bps,
        min_notional: values.min_notional,
        benchmark: 'buy_and_hold',
        validation_split_mode: values.validation_split_mode,
        oos_ratio: normalizeRatioValue(values.oos_ratio_pct) === undefined ? undefined : Number(values.oos_ratio_pct) / 100,
        warmup_bars: values.warmup_bars,
        is_start: normalizeDateValue(values.is_start),
        is_end: normalizeDateValue(values.is_end),
        oos_start: normalizeDateValue(values.oos_start),
        oos_end: normalizeDateValue(values.oos_end),
      });
      const batchId = String(result.batch_id ?? '');
      setLastActionResult(`参数实验批次已提交：${batchId}`);
      message.success(`参数实验批次已提交：${batchId}`);
      const [batchPayload, experimentsPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setSelectedBatchId(batchId || ALL_BATCHES);
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
      setParameterLab((current) => (
        current === null
          ? current
          : {
            ...current,
            rows: current.rows.filter((row) => row.run_id !== runId),
          }
      ));
      setSelectedExperimentDetail((current) => {
        if (current === null) {
          return current;
        }
        const nextRunIds = (current.execution.run_ids ?? []).filter((value) => value !== runId);
        if (nextRunIds.length === (current.execution.run_ids ?? []).length) {
          return current;
        }
        return {
          ...current,
          execution: {
            ...current.execution,
            run_ids: nextRunIds,
          },
        };
      });
      setSelectedBatchDetail((current) => {
        if (current === null) {
          return current;
        }
        const nextRunIds = (current.execution.run_ids ?? []).filter((value) => value !== runId);
        if (nextRunIds.length === (current.execution.run_ids ?? []).length) {
          return current;
        }
        return {
          ...current,
          execution: {
            ...current.execution,
            run_ids: nextRunIds,
          },
          run_rows: current.run_rows.filter((row) => row.run_id !== runId),
          parameter_groups: current.parameter_groups.map((group) => ({
            ...group,
            run_ids: group.run_ids.filter((value) => value !== runId),
            run_count: Math.max(0, group.run_count - (group.run_ids.includes(runId) ? 1 : 0)),
          })),
          recommendations: {
            robust_candidates: current.recommendations.robust_candidates.map((group) => ({
              ...group,
              run_ids: group.run_ids.filter((value) => value !== runId),
              run_count: Math.max(0, group.run_count - (group.run_ids.includes(runId) ? 1 : 0)),
            })),
            high_return_candidates: current.recommendations.high_return_candidates.map((group) => ({
              ...group,
              run_ids: group.run_ids.filter((value) => value !== runId),
              run_count: Math.max(0, group.run_count - (group.run_ids.includes(runId) ? 1 : 0)),
            })),
            exploratory_candidates: current.recommendations.exploratory_candidates?.map((group) => ({
              ...group,
              run_ids: group.run_ids.filter((value) => value !== runId),
              run_count: Math.max(0, group.run_count - (group.run_ids.includes(runId) ? 1 : 0)),
            })),
            excluded_combinations: current.recommendations.excluded_combinations.map((group) => ({
              ...group,
              run_ids: group.run_ids.filter((value) => value !== runId),
              run_count: Math.max(0, group.run_count - (group.run_ids.includes(runId) ? 1 : 0)),
            })),
          },
        };
      });
      setLastActionResult(`已删除回测：${runId}`);
      message.success(`已删除回测：${runId}`);
      if (selectedRunId === runId) {
        setSelectedRunId('');
      }
      await refreshShell();
      await refreshParameterWorkspaceMeta();
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '删除回测失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDeletingRunId(null);
    }
  }

  async function handleDeleteRuns(runIds: string[]) {
    if (!runIds.length) {
      return;
    }
    setBulkDeletingRuns(true);
    try {
      const runIdSet = new Set(runIds);
      for (const runId of runIds) {
        await deleteRun(runId);
        if (selectedRunId === runId) {
          setSelectedRunId('');
        }
      }
      setParameterLab((current) => (
        current === null
          ? current
          : {
            ...current,
            rows: current.rows.filter((row) => !runIdSet.has(row.run_id)),
          }
      ));
      setSelectedExperimentDetail((current) => {
        if (current === null) {
          return current;
        }
        return {
          ...current,
          execution: {
            ...current.execution,
            run_ids: (current.execution.run_ids ?? []).filter((value) => !runIdSet.has(value)),
          },
        };
      });
      setSelectedBatchDetail((current) => {
        if (current === null) {
          return current;
        }
        const shrinkGroup = <T extends { run_ids: string[]; run_count: number }>(group: T): T => {
          const removedCount = group.run_ids.filter((value) => runIdSet.has(value)).length;
          return {
            ...group,
            run_ids: group.run_ids.filter((value) => !runIdSet.has(value)),
            run_count: Math.max(0, group.run_count - removedCount),
          };
        };
        return {
          ...current,
          execution: {
            ...current.execution,
            run_ids: (current.execution.run_ids ?? []).filter((value) => !runIdSet.has(value)),
          },
          run_rows: current.run_rows.filter((row) => !runIdSet.has(row.run_id)),
          parameter_groups: current.parameter_groups.map((group) => shrinkGroup(group)),
          recommendations: {
            robust_candidates: current.recommendations.robust_candidates.map((group) => shrinkGroup(group)),
            high_return_candidates: current.recommendations.high_return_candidates.map((group) => shrinkGroup(group)),
            exploratory_candidates: current.recommendations.exploratory_candidates?.map((group) => shrinkGroup(group)),
            excluded_combinations: current.recommendations.excluded_combinations.map((group) => shrinkGroup(group)),
          },
        };
      });
      setSelectedOverviewRunIds([]);
      setLastActionResult(`已批量删除 ${runIds.length} 个回测`);
      message.success(`已批量删除 ${runIds.length} 个回测`);
      await refreshShell();
      await refreshParameterWorkspaceMeta();
      setActiveTab('overview');
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '批量删除回测失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setBulkDeletingRuns(false);
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

  async function handleDeleteParameterExperiment(experimentId: string) {
    setDeletingExperimentId(experimentId);
    try {
      await deleteParameterExperiment(experimentId);
      setLastActionResult(`已删除参数实验：${experimentId}`);
      message.success(`已删除参数实验：${experimentId}`);
      invalidateDerivedData();
      await refreshShell();
      setActiveTab('parameters');
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '删除参数实验失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDeletingExperimentId(null);
    }
  }

  async function handleDeleteParameterExperimentBatch(batchId: string) {
    setDeletingBatchId(batchId);
    try {
      await deleteParameterExperimentBatch(batchId);
      setLastActionResult(`已删除实验批次：${batchId}`);
      message.success(`已删除实验批次：${batchId}`);
      invalidateDerivedData();
      await refreshShell();
      setActiveTab('parameters');
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '删除实验批次失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDeletingBatchId(null);
    }
  }

  async function handleSaveTargetResearchNote(targetType: string, targetId: string, values: Record<string, unknown>) {
    setSavingResearchNote(true);
    try {
      await postResearchNote({
        target_type: targetType,
        target_id: targetId,
        author: String(values.author ?? 'local').trim() || 'local',
        content: String(values.content ?? '').trim(),
        labels: Array.isArray(values.labels) ? values.labels : [],
      });
      const notesPayload = await loadResearchNotes(targetType, targetId);
      setResearchNotes((current) => {
        const retained = current.filter((note) => !(note.target_type === targetType && note.target_id === targetId));
        return [...notesPayload.research_notes, ...retained];
      });
      setLastActionResult(`研究备注已保存：${targetId}`);
      setError(null);
      message.success('研究备注已保存');
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '研究备注保存失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setSavingResearchNote(false);
    }
  }

  async function handleSaveResearchNote(runId: string, values: Record<string, unknown>) {
    await handleSaveTargetResearchNote('run', runId, values);
    const payload = await loadRunDetail(runId);
    applyPayloadMeta(payload);
    setSelectedRun(payload.run);
    setRunDetailCache((current) => ({ ...current, [payload.run.run_id]: payload.run }));
  }

  const manualLabelsByRunId = useMemo(() => {
    const labelMap = new Map<string, string[]>();
    for (const note of researchNotes) {
      if (note.target_type !== 'run') {
        continue;
      }
      const current = labelMap.get(note.target_id) ?? [];
      labelMap.set(note.target_id, Array.from(new Set([...current, ...(note.labels ?? [])])));
    }
    return labelMap;
  }, [researchNotes]);

  const filteredSummaries = useMemo(() => {
    const rows = overview?.summaries ?? [];
    const query = deferredOverviewQuery.trim().toLowerCase();
    return rows.filter((row) => {
      if (query && ![row.run_id, row.dataset_snapshot_id, row.symbol, row.strategy_name, row.timeframe].join(' ').toLowerCase().includes(query)) {
        return false;
      }
      if (overviewLabelFilter.length) {
        const labels = manualLabelsByRunId.get(row.run_id) ?? [];
        if (!overviewLabelFilter.some((label) => labels.includes(label))) {
          return false;
        }
      }
      return true;
    });
  }, [overview, deferredOverviewQuery, manualLabelsByRunId, overviewLabelFilter]);

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

  useEffect(() => {
    const availableRunIds = new Set(filteredSummaries.map((summary) => summary.run_id));
    setSelectedOverviewRunIds((current) => current.filter((runId) => availableRunIds.has(runId)));
  }, [filteredSummaries]);
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
              overviewEquityRows={overviewEquityRows}
              overviewEquityLoading={overviewEquityLoading}
              filteredSummaries={filteredSummaries}
              manualLabelsByRunId={manualLabelsByRunId}
              overviewLabelFilter={overviewLabelFilter}
              setOverviewLabelFilter={setOverviewLabelFilter}
              selectedOverviewRunIds={selectedOverviewRunIds}
              setSelectedOverviewRunIds={setSelectedOverviewRunIds}
              compareRunIds={compareRunIds}
              setCompareRunIds={setCompareRunIds}
              overviewQuery={overviewQuery}
              setOverviewQuery={setOverviewQuery}
              overviewStats={overviewStats}
              deletingRunId={deletingRunId}
              bulkDeletingRuns={bulkDeletingRuns}
              onDeleteRun={handleDeleteRun}
              onDeleteRuns={handleDeleteRuns}
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
              onSaveResearchNote={handleSaveResearchNote}
              savingResearchNote={savingResearchNote}
            />
          )}
          {activeTab === 'parameters' && parameterLab && (
            <ParametersView
              datasets={datasets}
              rows={filteredParameterRows}
              allRows={parameterLab.rows}
              researchNotes={researchNotes}
              manualLabelsByRunId={manualLabelsByRunId}
              fastRows={parameterLab.fast_period_total_return}
              slowRows={parameterLab.slow_period_total_return}
              batches={parameterExperimentBatches}
              selectedBatchId={selectedBatchId}
              setSelectedBatchId={setSelectedBatchId}
              selectedBatchDetail={selectedBatchDetail}
              experiments={parameterExperiments}
              selectedExperimentId={selectedExperimentId}
              setSelectedExperimentId={setSelectedExperimentId}
              selectedExperimentDetail={selectedExperimentDetail}
              experimentDetailLoading={experimentDetailLoading}
              deletingExperimentId={deletingExperimentId}
              deletingBatchId={deletingBatchId}
              parameterQuery={parameterQuery}
              setParameterQuery={setParameterQuery}
              experimentForm={experimentForm}
              submitting={submitting}
              onSubmitExperiment={handleSubmitParameterExperiment}
              onOpenRun={(runId) => {
                setSelectedRunId(runId);
                setActiveTab('analysis');
              }}
              onDeleteRun={handleDeleteRun}
              onDeleteExperiment={handleDeleteParameterExperiment}
              onDeleteBatch={handleDeleteParameterExperimentBatch}
              onSaveResearchNote={handleSaveTargetResearchNote}
              savingResearchNote={savingResearchNote}
              onRefreshExperiments={async () => {
                const [experimentPayload, batchPayload, parameterPayload] = await Promise.all([
                  loadParameterExperiments(),
                  loadParameterExperimentBatches(),
                  loadParameters(),
                ]);
                applyPayloadMeta(experimentPayload);
                setParameterExperiments(experimentPayload.parameter_experiments);
                setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
                setParameterLab(parameterPayload.parameter_lab);
                if (selectedBatchId !== ALL_BATCHES) {
                  const batchDetailPayload = await loadParameterExperimentBatchDetail(selectedBatchId);
                  applyPayloadMeta(batchDetailPayload);
                  setSelectedBatchDetail(batchDetailPayload.parameter_experiment_batch);
                }
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
  overviewEquityRows,
  overviewEquityLoading,
  filteredSummaries,
  manualLabelsByRunId,
  overviewLabelFilter,
  setOverviewLabelFilter,
  selectedOverviewRunIds,
  setSelectedOverviewRunIds,
  compareRunIds,
  setCompareRunIds,
  overviewQuery,
  setOverviewQuery,
  overviewStats,
  deletingRunId,
  bulkDeletingRuns,
  onDeleteRun,
  onDeleteRuns,
}: {
  overview: WorkspaceOverview;
  overviewEquityRows: MultiRunEquityRow[];
  overviewEquityLoading: boolean;
  filteredSummaries: RunSummaryView[];
  manualLabelsByRunId: Map<string, string[]>;
  overviewLabelFilter: string[];
  setOverviewLabelFilter: (value: string[]) => void;
  selectedOverviewRunIds: string[];
  setSelectedOverviewRunIds: (value: string[]) => void;
  compareRunIds: string[];
  setCompareRunIds: (value: string[]) => void;
  overviewQuery: string;
  setOverviewQuery: (value: string) => void;
  overviewStats: Array<{ title: string; value: string }>;
  deletingRunId: string | null;
  bulkDeletingRuns: boolean;
  onDeleteRun: (runId: string) => Promise<void>;
  onDeleteRuns: (runIds: string[]) => Promise<void>;
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
    {
      id: 'labels',
      header: '人工标签',
      enableSorting: false,
      cell: ({ row }) => {
        const labels = manualLabelsByRunId.get(row.original.run_id) ?? [];
        if (!labels.length) {
          return <Text type="secondary">--</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {labels.map((label) => (
              <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'default'} key={`${row.original.run_id}-${label}`}>
                {RESEARCH_LABEL_TEXT[label] ?? label}
              </Tag>
            ))}
          </Space>
        );
      },
    },
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
  ], [manualLabelsByRunId]);

  const plotRows = overviewEquityRows;
  const chartOptions = filteredSummaries.length ? filteredSummaries : overview.summaries;
  const summaryByRunId = new Map(overview.summaries.map((summary) => [summary.run_id, summary] as const));
  const availableOverviewLabels = useMemo(
    () => Array.from(new Set(overview.summaries.flatMap((summary) => manualLabelsByRunId.get(summary.run_id) ?? []))),
    [manualLabelsByRunId, overview.summaries],
  );
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
                allowClear
                value={overviewLabelFilter}
                style={{ minWidth: 220 }}
                placeholder="按人工标签筛选"
                onChange={setOverviewLabelFilter}
                options={availableOverviewLabels.map((label) => ({
                  label: RESEARCH_LABEL_TEXT[label] ?? label,
                  value: label,
                }))}
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
          <Spin spinning={overviewEquityLoading}>
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
          </Spin>
        </Card>
      </Col>

      <Col span={24}>
        <Card title="运行总览表">
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Flex justify="space-between" align="center" wrap="wrap" gap={12}>
              <Text type="secondary">
                {selectedOverviewRunIds.length
                  ? `已选中 ${selectedOverviewRunIds.length} 条回测`
                  : '可勾选多条回测后批量删除'}
              </Text>
              <Popconfirm
                title="批量删除选中的回测？"
                description={`将删除 ${selectedOverviewRunIds.length} 条回测记录`}
                okText="批量删除"
                cancelText="取消"
                okButtonProps={{ danger: true, loading: bulkDeletingRuns }}
                onConfirm={() => onDeleteRuns(selectedOverviewRunIds)}
                disabled={!selectedOverviewRunIds.length}
              >
                <Button danger disabled={!selectedOverviewRunIds.length} loading={bulkDeletingRuns}>
                  批量删除
                </Button>
              </Popconfirm>
            </Flex>
            <DataTable
              columns={columns}
              data={filteredSummaries}
              initialPageSize={10}
              getRowId={(row) => row.run_id}
              selectedRowIds={selectedOverviewRunIds}
              onSelectedRowIdsChange={setSelectedOverviewRunIds}
            />
          </Space>
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
  onSaveResearchNote,
  savingResearchNote,
}: {
  runs: RunSummaryView[];
  selectedRun: RunAnalysisView | null;
  selectedRunId: string;
  setSelectedRunId: (value: string) => void;
  deletingRunId: string | null;
  onDeleteRun: (runId: string) => Promise<void>;
  onSaveResearchNote: (runId: string, values: Record<string, unknown>) => Promise<void>;
  savingResearchNote: boolean;
}) {
  const [tradeSideFilter, setTradeSideFilter] = useState<string>('all');
  const [tradeOutcomeFilter, setTradeOutcomeFilter] = useState<'all' | 'win' | 'loss' | 'open'>('all');
  const [tradeReasonQuery, setTradeReasonQuery] = useState('');
  const [researchNoteForm] = Form.useForm();

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
  const researchNotes = selectedRun?.research_notes ?? [];
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
  const validationSummary = selectedRun.validation;
  const latestResearchNote = researchNotes[0] ?? null;
  const aggregatedLabels = Array.from(new Set(researchNotes.flatMap((note) => note.labels ?? [])));
  const validationSegments = validationSummary
    ? [
      {
        key: 'is',
        title: '样本内 IS',
        segment: validationSummary.is_segment,
      },
      {
        key: 'oos',
        title: '样本外 OOS',
        segment: validationSummary.oos_segment,
      },
    ]
    : [];

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
        <Card title="样本内 / 样本外研究">
          {validationSummary ? (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                当前主 run 结果仍保持样本内口径；这里额外展示同一份 validation split 下的样本内 / 样本外摘要，用来判断参数是否过拟合。
              </Paragraph>
              <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                <Descriptions.Item label="切分 ID">{validationSummary.validation_split_id}</Descriptions.Item>
                <Descriptions.Item label="主结果口径">样本内 IS</Descriptions.Item>
              </Descriptions>
              <Row gutter={[16, 16]}>
                {validationSegments.map(({ key, title, segment }) => (
                  <Col xs={24} xl={12} key={key}>
                    <Card size="small" title={title}>
                      <Row gutter={[12, 12]}>
                        <Col xs={12} md={8}><Statistic title="收益率" value={formatPct(segment.metrics.total_return)} /></Col>
                        <Col xs={12} md={8}><Statistic title="超额收益" value={formatPct(segment.excess_return)} /></Col>
                        <Col xs={12} md={8}><Statistic title="成交笔数" value={segment.metrics.trade_count} /></Col>
                        <Col xs={12} md={8}><Statistic title="胜率" value={formatPct(segment.metrics.win_rate)} /></Col>
                        <Col xs={12} md={8}><Statistic title="基准收益" value={formatPct(segment.benchmark_return)} /></Col>
                        <Col xs={12} md={8}><Statistic title="最终权益" value={formatNumber(segment.metrics.final_equity)} /></Col>
                      </Row>
                      <Descriptions size="small" column={1} style={{ marginTop: 16 }}>
                        <Descriptions.Item label="分析区间">
                          {segment.analysis_start && segment.analysis_end
                            ? `${formatDateTime(segment.analysis_start)} ~ ${formatDateTime(segment.analysis_end)}`
                            : '--'}
                        </Descriptions.Item>
                        <Descriptions.Item label="K 线 / 预热">
                          {`${segment.analysis_bar_count} / ${segment.warmup_bars}`}
                        </Descriptions.Item>
                        <Descriptions.Item label="预热完整">
                          {segment.warmup_complete ? '是' : '否'}
                        </Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Space>
          ) : (
            <Alert type="info" showIcon message="当前 run 没有配置 validation split，暂时没有样本内 / 样本外研究摘要。" />
          )}
        </Card>
      </Col>

      <Col span={24}>
        <Card title="研究备注与标记">
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={10}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  给当前 run 留下结论、候选状态和复盘备注。标签用于快速筛出基准、候选和排除项，备注保留具体判断依据。
                </Paragraph>
                <Space wrap size={[8, 8]}>
                  {aggregatedLabels.length ? aggregatedLabels.map((label) => (
                    <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'blue'} key={label}>
                      {researchLabelText(label)}
                    </Tag>
                  )) : <Text type="secondary">当前还没有标签</Text>}
                  {latestResearchNote ? (
                    <Tag color={decisionStatusColor(latestResearchNote.decision_status)}>
                      {decisionStatusText(latestResearchNote.decision_status)}
                    </Tag>
                  ) : null}
                </Space>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="备注数">{researchNotes.length}</Descriptions.Item>
                  <Descriptions.Item label="最近更新">
                    {latestResearchNote ? formatDateTime(latestResearchNote.created_at) : '--'}
                  </Descriptions.Item>
                  <Descriptions.Item label="最近作者">
                    {latestResearchNote?.author ?? '--'}
                  </Descriptions.Item>
                </Descriptions>
              </Space>
            </Col>
            <Col xs={24} xl={14}>
              <Form
                form={researchNoteForm}
                layout="vertical"
                initialValues={{ author: 'local', decision_status: 'candidate', labels: [] }}
                onFinish={async (values) => {
                  await onSaveResearchNote(selectedRun.run_id, values);
                  researchNoteForm.setFieldsValue({
                    author: values.author,
                    decision_status: values.decision_status ?? 'candidate',
                    labels: values.labels ?? [],
                    decision_reason: '',
                    confidence_score: null,
                    content: '',
                  });
                }}
              >
                <Row gutter={[12, 12]}>
                  <Col xs={24} md={8}>
                    <Form.Item name="author" label="作者" rules={[{ required: true, whitespace: true, message: '请输入作者' }]}>
                      <Input placeholder="local" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={16}>
                    <Form.Item name="labels" label="标签">
                      <Select
                        mode="multiple"
                        options={RESEARCH_LABEL_OPTIONS}
                        placeholder="选择标签"
                        optionFilterProp="label"
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Row gutter={[12, 12]}>
                  <Col xs={24} md={8}>
                    <Form.Item name="decision_status" label="决策状态" rules={[{ required: true, message: '请选择决策状态' }]}>
                      <Select options={DECISION_STATUS_OPTIONS} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item name="confidence_score" label="置信度">
                      <InputNumber min={0} max={100} precision={1} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item name="decision_reason" label="状态原因">
                      <Input />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item
                  name="content"
                  label="研究备注"
                  rules={[{ required: true, whitespace: true, message: '请输入备注内容' }]}
                >
                  <Input.TextArea rows={3} placeholder="例如：样本外收益仍为正，可作为下一轮重点复核候选。" />
                </Form.Item>
                <Flex justify="flex-end">
                  <Button type="primary" htmlType="submit" loading={savingResearchNote}>
                    保存备注
                  </Button>
                </Flex>
              </Form>
            </Col>
            <Col span={24}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                {researchNotes.length ? researchNotes.map((note) => (
                  <Card size="small" className="cbw-note-card" key={note.note_id}>
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
                        <Space wrap size={[8, 8]}>
                          <Text strong>{note.author}</Text>
                          <Text type="secondary">{formatDateTime(note.created_at)}</Text>
                        </Space>
                        <Space wrap size={[8, 8]}>
                          <Tag color={decisionStatusColor(note.decision_status)}>
                            {decisionStatusText(note.decision_status)}
                          </Tag>
                          {note.labels.map((label) => (
                            <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'blue'} key={`${note.note_id}-${label}`}>
                              {researchLabelText(label)}
                            </Tag>
                          ))}
                        </Space>
                      </Flex>
                      {note.decision_reason ? <Text type="secondary">{note.decision_reason}</Text> : null}
                      <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{note.content}</Paragraph>
                    </Space>
                  </Card>
                )) : (
                  <Alert type="info" showIcon message="当前 run 还没有研究备注。" />
                )}
              </Space>
            </Col>
          </Row>
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
  researchNotes,
  manualLabelsByRunId,
  fastRows,
  slowRows,
  batches,
  selectedBatchId,
  setSelectedBatchId,
  selectedBatchDetail,
  experiments,
  selectedExperimentId,
  setSelectedExperimentId,
  selectedExperimentDetail,
  experimentDetailLoading,
  deletingExperimentId,
  deletingBatchId,
  parameterQuery,
  setParameterQuery,
  experimentForm,
  submitting,
  onSubmitExperiment,
  onOpenRun,
  onDeleteRun,
  onDeleteExperiment,
  onDeleteBatch,
  onSaveResearchNote,
  savingResearchNote,
  onRefreshExperiments,
}: {
  datasets: DatasetSnapshotView[];
  rows: ParameterLabRow[];
  allRows: ParameterLabRow[];
  researchNotes: ResearchNote[];
  manualLabelsByRunId: Map<string, string[]>;
  fastRows: SensitivityRow[];
  slowRows: SensitivityRow[];
  batches: ParameterExperimentBatchSummary[];
  selectedBatchId: string;
  setSelectedBatchId: (value: string) => void;
  selectedBatchDetail: ParameterExperimentBatchDetail | null;
  experiments: ParameterExperimentSummary[];
  selectedExperimentId: string;
  setSelectedExperimentId: (value: string) => void;
  selectedExperimentDetail: ParameterExperimentDetail | null;
  experimentDetailLoading: boolean;
  deletingExperimentId: string | null;
  deletingBatchId: string | null;
  parameterQuery: string;
  setParameterQuery: (value: string) => void;
  experimentForm: ReturnType<typeof Form.useForm>[0];
  submitting: 'ingest' | 'run' | 'experiment' | null;
  onSubmitExperiment: (values: Record<string, unknown>) => Promise<void>;
  onOpenRun: (runId: string) => void;
  onDeleteRun: (runId: string) => Promise<void>;
  onDeleteExperiment: (experimentId: string) => Promise<void>;
  onDeleteBatch: (batchId: string) => Promise<void>;
  onSaveResearchNote: (targetType: string, targetId: string, values: Record<string, unknown>) => Promise<void>;
  savingResearchNote: boolean;
  onRefreshExperiments: () => Promise<void>;
  }) {
  const experimentSearchType = Form.useWatch('search_type', experimentForm) as string | undefined;
  const validationSplitMode = Form.useWatch('validation_split_mode', experimentForm) as string | undefined;
  const [workspaceMode, setWorkspaceMode] = useState<'batch' | 'experiment' | 'decisions' | 'sensitivity'>('batch');
  const [runManualLabelFilter, setRunManualLabelFilter] = useState<string[]>([]);
  const [groupDecisionLabelFilter, setGroupDecisionLabelFilter] = useState<string[]>([]);
  const [batchDecisionLabelFilter, setBatchDecisionLabelFilter] = useState<string[]>([]);
  const [groupDecisionStatusFilter, setGroupDecisionStatusFilter] = useState<string[]>([]);
  const [batchDecisionStatusFilter, setBatchDecisionStatusFilter] = useState<string[]>([]);
  const [decisionLedgerStatusFilter, setDecisionLedgerStatusFilter] = useState<string[]>([]);
  const [decisionLedgerLabelFilter, setDecisionLedgerLabelFilter] = useState<string[]>([]);
  const [decisionLedgerTargetTypeFilter, setDecisionLedgerTargetTypeFilter] = useState<string[]>([]);
  const [decisionLedgerBatchFilter, setDecisionLedgerBatchFilter] = useState<string | null>(null);
  const [decisionLedgerParameterGroupFilter, setDecisionLedgerParameterGroupFilter] = useState<string | null>(null);
  const [showExperimentForm, setShowExperimentForm] = useState(false);
  const [autoLabelFilter, setAutoLabelFilter] = useState<string[]>([]);
  const [minScoreFilter, setMinScoreFilter] = useState<number | null>(null);
  const [minConfidenceFilter, setMinConfidenceFilter] = useState<number | null>(null);
  const [maxDrawdownFilter, setMaxDrawdownFilter] = useState<number | null>(null);
  const [minReturnDrawdownFilter, setMinReturnDrawdownFilter] = useState<number | null>(null);
  const [topNFilter, setTopNFilter] = useState<number | null>(null);
  const [decisionTarget, setDecisionTarget] = useState<{ targetType: string; targetId: string; title: string } | null>(null);
  const [decisionForm] = Form.useForm();
  const datasetOptions = useMemo(
    () => datasets.map((snapshot) => ({
      label: `${snapshot.dataset_snapshot_id} · ${snapshot.symbol} · ${snapshot.timeframe.toUpperCase()}`,
      value: snapshot.dataset_snapshot_id,
    })),
    [datasets],
  );

  useEffect(() => {
    if (!experimentForm.getFieldValue('snapshot_ids') && datasets[0]?.dataset_snapshot_id) {
      experimentForm.setFieldValue('snapshot_ids', [datasets[0].dataset_snapshot_id]);
    }
    if (!experimentForm.getFieldValue('batch_id')) {
      experimentForm.setFieldValue('batch_id', `batch-${dayjs().format('YYYYMMDDHHmmss')}`);
    }
    if (!experimentForm.getFieldValue('search_type')) {
      experimentForm.setFieldValue('search_type', 'grid');
    }
    if (!experimentForm.getFieldValue('validation_split_mode')) {
      experimentForm.setFieldValue('validation_split_mode', 'auto_ratio');
    }
    if (experimentForm.getFieldValue('oos_ratio_pct') === undefined) {
      experimentForm.setFieldValue('oos_ratio_pct', 30);
    }
    if (experimentForm.getFieldValue('warmup_bars') === undefined) {
      experimentForm.setFieldValue('warmup_bars', 0);
    }
    if (!experimentForm.getFieldValue('fast_periods')) {
      experimentForm.setFieldValue('fast_periods', '2,3,5,8');
    }
    if (!experimentForm.getFieldValue('slow_periods')) {
      experimentForm.setFieldValue('slow_periods', '13,21,34');
    }
    if (experimentForm.getFieldValue('cash_allocation_pct') === undefined) {
      experimentForm.setFieldValue('cash_allocation_pct', 100);
    }
    if (experimentForm.getFieldValue('initial_cash') === undefined) {
      experimentForm.setFieldValue('initial_cash', 10000);
    }
    if (!experimentForm.getFieldValue('leverage_candidates')) {
      experimentForm.setFieldValue('leverage_candidates', '1');
    }
    if (experimentForm.getFieldValue('fee_rate') === undefined) {
      experimentForm.setFieldValue('fee_rate', 0);
    }
    if (experimentForm.getFieldValue('slippage_bps') === undefined) {
      experimentForm.setFieldValue('slippage_bps', 0);
    }
    if (experimentForm.getFieldValue('min_notional') === undefined) {
      experimentForm.setFieldValue('min_notional', 0);
    }
  }, [datasets, experimentForm]);

  useEffect(() => {
    if (experimentSearchType === 'grid') {
      experimentForm.setFieldValue('max_samples', undefined);
    }
  }, [experimentForm, experimentSearchType]);

  const selectedExperimentSummary = useMemo(
    () => (selectedExperimentId === ALL_EXPERIMENTS
      ? null
      : experiments.find((experiment) => experiment.experiment_id === selectedExperimentId) ?? null),
    [experiments, selectedExperimentId],
  );
  const visibleExperiments = useMemo(
    () => experiments.filter((experiment) => experiment.run_count > 0 || experiment.failed_run_count > 0),
    [experiments],
  );
  const selectedBatchSummary = useMemo(
    () => (selectedBatchId === ALL_BATCHES
      ? null
      : batches.find((batch) => batch.batch_id === selectedBatchId) ?? null),
    [batches, selectedBatchId],
  );

  useEffect(() => {
    if (selectedExperimentId === ALL_EXPERIMENTS) {
      return;
    }
    if (!visibleExperiments.some((experiment) => experiment.experiment_id === selectedExperimentId)) {
      setSelectedExperimentId(ALL_EXPERIMENTS);
    }
  }, [selectedExperimentId, setSelectedExperimentId, visibleExperiments]);
  useEffect(() => {
    if (selectedBatchId !== ALL_BATCHES) {
      return;
    }
    if (autoLabelFilter.length) {
      setAutoLabelFilter([]);
    }
    if (groupDecisionLabelFilter.length) {
      setGroupDecisionLabelFilter([]);
    }
    if (groupDecisionStatusFilter.length) {
      setGroupDecisionStatusFilter([]);
    }
    if (minScoreFilter !== null) {
      setMinScoreFilter(null);
    }
    if (minConfidenceFilter !== null) {
      setMinConfidenceFilter(null);
    }
    if (maxDrawdownFilter !== null) {
      setMaxDrawdownFilter(null);
    }
    if (minReturnDrawdownFilter !== null) {
      setMinReturnDrawdownFilter(null);
    }
    if (topNFilter !== null) {
      setTopNFilter(null);
    }
  }, [autoLabelFilter.length, groupDecisionLabelFilter.length, groupDecisionStatusFilter.length, maxDrawdownFilter, minConfidenceFilter, minReturnDrawdownFilter, minScoreFilter, selectedBatchId, topNFilter]);
  const selectedBatchRows = useMemo(() => {
    if (selectedBatchId === ALL_BATCHES) {
      return rows;
    }
    if (selectedBatchDetail?.run_rows) {
      return selectedBatchDetail.run_rows;
    }
    const runIds = new Set(selectedBatchDetail?.execution.run_ids ?? []);
    if (!runIds.size) {
      return [];
    }
    return rows.filter((row) => runIds.has(row.run_id));
  }, [rows, selectedBatchDetail, selectedBatchId]);
  const selectedExperimentRows = useMemo(() => {
    if (selectedExperimentId === ALL_EXPERIMENTS) {
      return rows;
    }
    const runIds = selectedExperimentDetail?.execution.run_ids ?? [];
    if (!runIds.length) {
      return [];
    }
    const rowsByRunId = new Map(rows.map((row) => [row.run_id, row] as const));
    return runIds
      .map((runId) => rowsByRunId.get(runId))
      .filter((row): row is ParameterLabRow => row !== undefined);
  }, [rows, selectedExperimentDetail, selectedExperimentId]);
  const failedChildTaskIds = selectedExperimentDetail?.execution.failed_child_task_ids ?? [];
  const autoLabelsByRunId = useMemo(() => {
    const labelMap = new Map<string, AutoLabelInfo[]>();
    if (!selectedBatchDetail) {
      return labelMap;
    }
    const applyLabels = (runIds: string[], label: string, reason: string) => {
      for (const runId of runIds) {
        const current = labelMap.get(runId) ?? [];
        if (!current.some((item) => item.label === label)) {
          labelMap.set(runId, [...current, { label, reason }]);
        }
      }
    };
    for (const item of selectedBatchDetail.recommendations.robust_candidates) {
      applyLabels(item.run_ids, 'auto_robust_candidate', item.reason);
    }
    for (const item of selectedBatchDetail.recommendations.high_return_candidates) {
      applyLabels(item.run_ids, 'auto_high_return_candidate', item.reason);
    }
    for (const item of selectedBatchDetail.recommendations.exploratory_candidates ?? []) {
      applyLabels(item.run_ids, 'auto_exploratory_candidate', item.reason);
    }
    for (const item of selectedBatchDetail.recommendations.excluded_combinations) {
      applyLabels(item.run_ids, 'auto_excluded', item.reason);
    }
    return labelMap;
  }, [selectedBatchDetail]);

  const availableRunManualLabels = useMemo(
    () => Array.from(new Set(researchNotes.filter((note) => note.target_type === 'run').flatMap((note) => note.labels ?? []))),
    [researchNotes],
  );
  const availableAutoLabels = useMemo(
    () => Array.from(new Set(rows.flatMap((row) => (autoLabelsByRunId.get(row.run_id) ?? []).map((item) => item.label)))),
    [autoLabelsByRunId, rows],
  );
  const notesByTarget = useMemo(() => {
    const noteMap = new Map<string, ResearchNote[]>();
    for (const note of researchNotes) {
      const key = `${note.target_type}:${note.target_id}`;
      noteMap.set(key, [...(noteMap.get(key) ?? []), note]);
    }
    return noteMap;
  }, [researchNotes]);
  const availableDecisionLedgerStatuses = useMemo(
    () => Array.from(new Set(researchNotes.map((note) => note.decision_status ?? 'candidate'))),
    [researchNotes],
  );
  const availableDecisionLedgerLabels = useMemo(
    () => Array.from(new Set(researchNotes.flatMap((note) => note.labels ?? []))),
    [researchNotes],
  );
  const availableDecisionLedgerTargetTypes = useMemo(
    () => Array.from(new Set(researchNotes.map((note) => note.target_type))),
    [researchNotes],
  );
  const availableDecisionLedgerBatchIds = useMemo(
    () => Array.from(new Set(researchNotes.map((note) => note.linked_batch_id).filter((value): value is string => Boolean(value)))),
    [researchNotes],
  );
  const availableDecisionLedgerParameterGroups = useMemo(
    () => Array.from(new Set(researchNotes.map((note) => note.linked_parameter_group).filter((value): value is string => Boolean(value)))),
    [researchNotes],
  );
  const filteredDecisionLedgerNotes = useMemo(
    () => researchNotes.filter((note) => (
      (!decisionLedgerStatusFilter.length || decisionLedgerStatusFilter.includes(note.decision_status ?? 'candidate'))
      && (!decisionLedgerLabelFilter.length || decisionLedgerLabelFilter.some((label) => (note.labels ?? []).includes(label)))
      && (!decisionLedgerTargetTypeFilter.length || decisionLedgerTargetTypeFilter.includes(note.target_type))
      && (!decisionLedgerBatchFilter || note.linked_batch_id === decisionLedgerBatchFilter)
      && (!decisionLedgerParameterGroupFilter || note.linked_parameter_group === decisionLedgerParameterGroupFilter)
    )),
    [
      decisionLedgerBatchFilter,
      decisionLedgerLabelFilter,
      decisionLedgerParameterGroupFilter,
      decisionLedgerStatusFilter,
      decisionLedgerTargetTypeFilter,
      researchNotes,
    ],
  );
  const batchDecisionNotes = useMemo(
    () => (selectedBatchDetail ? (notesByTarget.get(`parameter_experiment_batch:${selectedBatchDetail.batch.batch_id}`) ?? []) : []),
    [notesByTarget, selectedBatchDetail],
  );
  const batchDecisionNotesByBatchId = useMemo(() => {
    const noteMap = new Map<string, ResearchNote[]>();
    for (const note of researchNotes) {
      if (note.target_type !== 'parameter_experiment_batch') {
        continue;
      }
      noteMap.set(note.target_id, [...(noteMap.get(note.target_id) ?? []), note]);
    }
    return noteMap;
  }, [researchNotes]);
  const availableBatchDecisionLabels = useMemo(
    () => Array.from(new Set(Array.from(batchDecisionNotesByBatchId.values()).flatMap((notes) => notes.flatMap((note) => note.labels ?? [])))),
    [batchDecisionNotesByBatchId],
  );
  const availableBatchDecisionStatuses = useMemo(
    () => Array.from(new Set(Array.from(batchDecisionNotesByBatchId.values()).flatMap((notes) => notes.map((note) => note.decision_status ?? 'candidate')))),
    [batchDecisionNotesByBatchId],
  );
  const filteredBatches = useMemo(() => {
    if (!batchDecisionLabelFilter.length && !batchDecisionStatusFilter.length) {
      return batches;
    }
    return batches.filter((batch) => {
      const notes = batchDecisionNotesByBatchId.get(batch.batch_id) ?? [];
      const labels = Array.from(new Set(notes.flatMap((note) => note.labels ?? [])));
      const statuses = Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate')));
      return (
        (!batchDecisionLabelFilter.length || batchDecisionLabelFilter.some((label) => labels.includes(label)))
        && (!batchDecisionStatusFilter.length || batchDecisionStatusFilter.some((status) => statuses.includes(status)))
      );
    });
  }, [batchDecisionLabelFilter, batchDecisionNotesByBatchId, batchDecisionStatusFilter, batches]);
  useEffect(() => {
    if (selectedBatchId === ALL_BATCHES || (!batchDecisionLabelFilter.length && !batchDecisionStatusFilter.length)) {
      return;
    }
    if (!filteredBatches.some((batch) => batch.batch_id === selectedBatchId)) {
      setSelectedBatchId(ALL_BATCHES);
    }
  }, [batchDecisionLabelFilter.length, batchDecisionStatusFilter.length, filteredBatches, selectedBatchId, setSelectedBatchId]);
  const autoLabelFilterDisabled = selectedBatchId === ALL_BATCHES;
  const batchGroupLabelsByKey = useMemo(() => {
    const labelMap = new Map<string, AutoLabelInfo[]>();
    if (!selectedBatchDetail) {
      return labelMap;
    }
    const applyLabel = (
      groups: Array<{ fast_period: number | null; slow_period: number | null; leverage: number | null; reason: string }>,
      label: string,
    ) => {
      for (const group of groups) {
        const key = buildParameterGroupKey(group);
        const current = labelMap.get(key) ?? [];
        if (!current.some((item) => item.label === label)) {
          labelMap.set(key, [...current, { label, reason: group.reason }]);
        }
      }
    };
    applyLabel(selectedBatchDetail.recommendations.robust_candidates, 'auto_robust_candidate');
    applyLabel(selectedBatchDetail.recommendations.high_return_candidates, 'auto_high_return_candidate');
    applyLabel(selectedBatchDetail.recommendations.exploratory_candidates ?? [], 'auto_exploratory_candidate');
    applyLabel(selectedBatchDetail.recommendations.excluded_combinations, 'auto_excluded');
    return labelMap;
  }, [selectedBatchDetail]);
  const batchGroupResearchNotesByKey = useMemo(() => {
    const noteMap = new Map<string, ResearchNote[]>();
    if (!selectedBatchDetail) {
      return noteMap;
    }
    for (const group of selectedBatchDetail.parameter_groups) {
      const targetId = buildParameterGroupTargetId(selectedBatchDetail.batch.batch_id, group);
      noteMap.set(buildParameterGroupKey(group), notesByTarget.get(`parameter_group:${targetId}`) ?? []);
    }
    return noteMap;
  }, [notesByTarget, selectedBatchDetail]);
  const batchManualLabelsByRunId = useMemo(() => {
    const labelMap = new Map<string, string[]>();
    for (const row of selectedBatchRows) {
      labelMap.set(row.run_id, [...(manualLabelsByRunId.get(row.run_id) ?? [])]);
    }
    for (const group of selectedBatchDetail?.parameter_groups ?? []) {
      const noteLabels = Array.from(new Set((batchGroupResearchNotesByKey.get(buildParameterGroupKey(group)) ?? []).flatMap((note) => note.labels ?? [])));
      if (!noteLabels.length) {
        continue;
      }
      for (const runId of group.run_ids) {
        const current = labelMap.get(runId) ?? [];
        labelMap.set(runId, Array.from(new Set([...current, ...noteLabels])));
      }
    }
    return labelMap;
  }, [batchGroupResearchNotesByKey, manualLabelsByRunId, selectedBatchDetail, selectedBatchRows]);
  const latestBatchGroupDecisionStatusByKey = useMemo(() => {
    const statusMap = new Map<string, string>();
    for (const [key, notes] of batchGroupResearchNotesByKey.entries()) {
      const latestNote = notes[0];
      if (latestNote) {
        statusMap.set(key, latestNote.decision_status ?? 'candidate');
      }
    }
    return statusMap;
  }, [batchGroupResearchNotesByKey]);
  const batchManualDecisionStatusByRunId = useMemo(() => {
    const statusMap = new Map<string, string>();
    for (const group of selectedBatchDetail?.parameter_groups ?? []) {
      const latestStatus = latestBatchGroupDecisionStatusByKey.get(buildParameterGroupKey(group));
      if (!latestStatus) {
        continue;
      }
      for (const runId of group.run_ids) {
        statusMap.set(runId, latestStatus);
      }
    }
    return statusMap;
  }, [latestBatchGroupDecisionStatusByKey, selectedBatchDetail]);
  const availableGroupDecisionLabels = useMemo(
    () => Array.from(new Set(Array.from(batchGroupResearchNotesByKey.values()).flatMap((notes) => notes.flatMap((note) => note.labels ?? [])))),
    [batchGroupResearchNotesByKey],
  );
  const availableGroupDecisionStatuses = useMemo(
    () => Array.from(new Set(Array.from(batchGroupResearchNotesByKey.values()).flatMap((notes) => notes.map((note) => note.decision_status ?? 'candidate')))),
    [batchGroupResearchNotesByKey],
  );
  const activeManualDecisionGroups = useMemo(() => {
    const groups = (selectedBatchDetail?.parameter_groups ?? []).filter((group) => {
      const status = latestBatchGroupDecisionStatusByKey.get(buildParameterGroupKey(group));
      return status === 'approved' || status === 'observing';
    });
    return [...groups].sort((left, right) => {
      const leftStatus = latestBatchGroupDecisionStatusByKey.get(buildParameterGroupKey(left));
      const rightStatus = latestBatchGroupDecisionStatusByKey.get(buildParameterGroupKey(right));
      if (leftStatus !== rightStatus) {
        return leftStatus === 'approved' ? -1 : 1;
      }
      return right.score - left.score;
    });
  }, [latestBatchGroupDecisionStatusByKey, selectedBatchDetail]);
  const selectedBatchGroupMetricsByRunId = useMemo(() => {
    const metrics = new Map<string, { score: number; confidence: number }>();
    for (const group of selectedBatchDetail?.parameter_groups ?? []) {
      for (const runId of group.run_ids) {
        const current = metrics.get(runId);
        if (!current || group.score > current.score) {
          metrics.set(runId, { score: group.score, confidence: group.confidence });
        }
      }
    }
    return metrics;
  }, [selectedBatchDetail]);

  function matchesScoreFilters(
    score: number | null | undefined,
    confidence: number | null | undefined,
    avgMaxDrawdown?: number | null,
    returnOverDrawdown?: number | null,
  ): boolean {
    if (minScoreFilter !== null && (score ?? Number.NEGATIVE_INFINITY) < minScoreFilter) {
      return false;
    }
    if (minConfidenceFilter !== null && (confidence ?? Number.NEGATIVE_INFINITY) < minConfidenceFilter) {
      return false;
    }
    if (maxDrawdownFilter !== null && (avgMaxDrawdown ?? Number.POSITIVE_INFINITY) > maxDrawdownFilter / 100) {
      return false;
    }
    if (minReturnDrawdownFilter !== null && (returnOverDrawdown ?? Number.NEGATIVE_INFINITY) < minReturnDrawdownFilter) {
      return false;
    }
    return true;
  }

  function matchesRunLabelFilters(
    runId: string,
    options: {
      applyAutoLabelFilters: boolean;
      applyBatchScoreFilters: boolean;
      manualLabelsByRunIdSource?: Map<string, string[]>;
      manualFilterValues?: string[];
    },
  ): boolean {
    const manualLabels = options.manualLabelsByRunIdSource?.get(runId) ?? manualLabelsByRunId.get(runId) ?? [];
    const autoLabels = (autoLabelsByRunId.get(runId) ?? []).map((item) => item.label);
    const manualFilterValues = options.manualFilterValues ?? runManualLabelFilter;
    if (manualFilterValues.length && !manualFilterValues.some((label) => manualLabels.includes(label))) {
      return false;
    }
    if (options.applyAutoLabelFilters && autoLabelFilter.length && !autoLabelFilter.some((label) => autoLabels.includes(label))) {
      return false;
    }
    if (options.applyBatchScoreFilters && selectedBatchId !== ALL_BATCHES) {
      const metrics = selectedBatchGroupMetricsByRunId.get(runId);
      if (!matchesScoreFilters(metrics?.score, metrics?.confidence)) {
        return false;
      }
    }
    return true;
  }

  function matchesBatchGroupFilters(group: NonNullable<ParameterExperimentBatchDetail['parameter_groups']>[number]): boolean {
    if (!matchesScoreFilters(group.score, group.confidence, group.avg_max_drawdown, group.return_over_drawdown)) {
      return false;
    }
    const groupKey = buildParameterGroupKey(group);
    const autoLabels = (batchGroupLabelsByKey.get(groupKey) ?? []).map((item) => item.label);
    const manualNotes = batchGroupResearchNotesByKey.get(groupKey) ?? [];
    const manualLabels = Array.from(new Set(manualNotes.flatMap((note) => note.labels ?? [])));
    const manualStatuses = Array.from(new Set(manualNotes.map((note) => note.decision_status ?? 'candidate')));
    if (autoLabelFilter.length && !autoLabelFilter.some((label) => autoLabels.includes(label))) {
      return false;
    }
    if (groupDecisionLabelFilter.length && !groupDecisionLabelFilter.some((label) => manualLabels.includes(label))) {
      return false;
    }
    if (groupDecisionStatusFilter.length && !groupDecisionStatusFilter.some((status) => manualStatuses.includes(status))) {
      return false;
    }
    return true;
  }

  function matchesBatchRecommendationFilters(group: NonNullable<ParameterExperimentBatchDetail['parameter_groups']>[number]): boolean {
    if (!matchesBatchGroupFilters(group)) {
      return false;
    }
    if (groupDecisionStatusFilter.length) {
      return true;
    }
    const latestStatus = latestBatchGroupDecisionStatusByKey.get(buildParameterGroupKey(group));
    return !isInactiveDecisionStatus(latestStatus);
  }

  const filteredBatchParameterGroups = useMemo(() => {
    const groups = (selectedBatchDetail?.parameter_groups ?? []).filter((group) => matchesBatchGroupFilters(group));
    const sortedGroups = [...groups].sort((left, right) => right.score - left.score);
    return topNFilter ? sortedGroups.slice(0, topNFilter) : sortedGroups;
  }, [autoLabelFilter, batchGroupLabelsByKey, batchGroupResearchNotesByKey, groupDecisionLabelFilter, groupDecisionStatusFilter, maxDrawdownFilter, minConfidenceFilter, minReturnDrawdownFilter, minScoreFilter, selectedBatchDetail, topNFilter]);
  const filteredBatchGroupRunIds = useMemo(
    () => new Set(filteredBatchParameterGroups.flatMap((group) => group.run_ids)),
    [filteredBatchParameterGroups],
  );
  const hasBatchGroupFilters = selectedBatchId !== ALL_BATCHES && (
    autoLabelFilter.length > 0
    || groupDecisionLabelFilter.length > 0
    || groupDecisionStatusFilter.length > 0
    || minScoreFilter !== null
    || minConfidenceFilter !== null
    || maxDrawdownFilter !== null
    || minReturnDrawdownFilter !== null
    || topNFilter !== null
  );
  const filteredBatchRunRows = useMemo(
    () => selectedBatchRows.filter((row) => (
      matchesRunLabelFilters(row.run_id, {
        applyAutoLabelFilters: false,
        applyBatchScoreFilters: true,
        manualLabelsByRunIdSource: batchManualLabelsByRunId,
        manualFilterValues: [],
      })
      && (!hasBatchGroupFilters || filteredBatchGroupRunIds.has(row.run_id))
    )),
    [batchManualLabelsByRunId, filteredBatchGroupRunIds, hasBatchGroupFilters, selectedBatchRows, autoLabelsByRunId, manualLabelsByRunId, selectedBatchGroupMetricsByRunId, minScoreFilter, minConfidenceFilter],
  );
  const filteredExperimentRunRows = useMemo(
    () => selectedExperimentRows.filter((row) => (
      matchesRunLabelFilters(row.run_id, { applyAutoLabelFilters: false, applyBatchScoreFilters: false })
    )),
    [runManualLabelFilter, selectedExperimentRows, autoLabelsByRunId, manualLabelsByRunId],
  );
  const experimentResultColumns = useMemo<ColumnDef<ParameterLabRow>[]>(() => [
    {
      header: 'Run',
      size: 220,
      minSize: 220,
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
      size: 72,
      minSize: 72,
      accessorFn: (row) => row.timeframe,
      cell: ({ row }) => row.original.timeframe.toUpperCase(),
    },
    {
      id: 'fast_slow',
      header: '快 / 慢',
      size: 88,
      minSize: 88,
      accessorFn: (row) => `${row.fast_period ?? ''}/${row.slow_period ?? ''}`,
      cell: ({ row }) => `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}`,
    },
    { id: 'leverage', header: '杠杆', size: 68, minSize: 68, accessorFn: (row) => row.leverage ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.leverage ?? '--' },
    { id: 'total_return', header: '收益率', size: 104, minSize: 104, accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    { id: 'max_drawdown', header: '最大回撤', size: 104, minSize: 104, accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    { id: 'excess_return', header: '超额收益', size: 108, minSize: 108, accessorFn: (row) => row.excess_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.excess_return) },
    { id: 'oos_total_return', header: '样本外收益', size: 120, minSize: 120, accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_total_return) },
    { id: 'oos_excess_return', header: '样本外超额', size: 120, minSize: 120, accessorFn: (row) => row.oos_excess_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_excess_return) },
    { id: 'final_equity', header: '最终权益', size: 120, minSize: 120, accessorFn: (row) => row.final_equity, cell: ({ row }) => formatNumber(row.original.final_equity) },
    { id: 'trade_count', header: '交易数', size: 84, minSize: 84, accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    { id: 'win_rate', header: '胜率', size: 88, minSize: 88, accessorFn: (row) => row.win_rate, cell: ({ row }) => formatPct(row.original.win_rate) },
    {
      id: 'labels',
      header: '标签',
      size: 220,
      minSize: 220,
      enableSorting: false,
      cell: ({ row }) => {
        const autoLabels = autoLabelsByRunId.get(row.original.run_id) ?? [];
        const manualLabels = workspaceMode === 'batch'
          ? (batchManualLabelsByRunId.get(row.original.run_id) ?? [])
          : (manualLabelsByRunId.get(row.original.run_id) ?? []);
        const groupDecisionStatus = workspaceMode === 'batch'
          ? batchManualDecisionStatusByRunId.get(row.original.run_id)
          : undefined;
        if (!autoLabels.length && !manualLabels.length && !groupDecisionStatus) {
          return <Text type="secondary">--</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {groupDecisionStatus ? (
              <Tag color={decisionStatusColor(groupDecisionStatus)}>
                {decisionStatusText(groupDecisionStatus)}
              </Tag>
            ) : null}
            {autoLabels.map((item) => (
              <Tooltip key={`${row.original.run_id}-${item.label}`} title={item.reason}>
                <Tag color={item.label === 'auto_excluded' ? 'red' : item.label === 'auto_high_return_candidate' ? 'blue' : item.label === 'auto_exploratory_candidate' ? 'purple' : 'green'}>
                  {AUTO_GROUP_MEMBERSHIP_LABEL_TEXT[item.label] ?? item.label}
                </Tag>
              </Tooltip>
            ))}
            {manualLabels.map((label) => (
              <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'default'} key={`${row.original.run_id}-${label}`}>
                {RESEARCH_LABEL_TEXT[label] ?? label}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    {
      id: 'actions',
      header: '操作',
      size: 160,
      minSize: 160,
      enableSorting: false,
      cell: ({ row }) => (
        <Space>
          <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开分析</Button>
          <Popconfirm
            title="删除这个实验 Run？"
            description={`run_id: ${row.original.run_id}`}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDeleteRun(row.original.run_id)}
          >
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ], [autoLabelsByRunId, batchManualDecisionStatusByRunId, batchManualLabelsByRunId, manualLabelsByRunId, onDeleteRun, onOpenRun, workspaceMode]);
  const experimentColumns = useMemo<ColumnDef<ParameterExperimentSummary>[]>(() => [
    {
      header: '实验 ID',
      size: 360,
      minSize: 300,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.original.experiment_id}</Text>
          <Text type="secondary">{row.original.task_id ?? '--'}</Text>
        </Space>
      ),
    },
    { header: '模式', size: 88, minSize: 88, cell: ({ row }) => experimentSearchTypeLabel(row.original.search_type) },
    { header: '计划 / 已完成', size: 108, minSize: 108, cell: ({ row }) => `${row.original.planned_run_count} / ${row.original.run_count}` },
    { header: '失败数', size: 72, minSize: 72, accessorKey: 'failed_run_count' },
    {
      header: '状态',
      size: 96,
      minSize: 96,
      cell: ({ row }) => {
        const status = row.original.status;
        return <Tag color={experimentStatusColor(status)}>{status}</Tag>;
      },
    },
    { id: 'created_at', header: '提交时间', size: 150, minSize: 150, accessorFn: (row) => row.created_at, cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: 'actions',
      header: '操作',
      size: 180,
      minSize: 180,
      enableSorting: false,
      cell: ({ row }) => (
        <Space>
          <Button size="small" type={row.original.experiment_id === selectedExperimentId ? 'primary' : 'default'} onClick={() => setSelectedExperimentId(row.original.experiment_id)}>
            查看结果
          </Button>
          <Popconfirm
            title="删除这个参数实验？"
            description={`experiment_id: ${row.original.experiment_id}`}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deletingExperimentId === row.original.experiment_id }}
            onConfirm={() => onDeleteExperiment(row.original.experiment_id)}
          >
            <Button size="small" danger loading={deletingExperimentId === row.original.experiment_id}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ], [deletingExperimentId, onDeleteExperiment, selectedExperimentId, setSelectedExperimentId]);
  const batchColumns = useMemo<ColumnDef<ParameterExperimentBatchSummary>[]>(() => [
    {
      header: '批次 ID',
      size: 320,
      minSize: 280,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.original.batch_id}</Text>
          <Text type="secondary">{row.original.task_id ?? '--'}</Text>
        </Space>
      ),
    },
    { header: '快照 / 实验', size: 100, minSize: 100, cell: ({ row }) => `${row.original.snapshot_count} / ${row.original.experiment_count}` },
    { header: '计划 / 已完成', size: 110, minSize: 110, cell: ({ row }) => `${row.original.planned_run_count} / ${row.original.run_count}` },
    { header: '失败实验', size: 84, minSize: 84, accessorKey: 'failed_experiment_count' },
    {
      id: 'batch_decision',
      header: '批次决策',
      size: 220,
      minSize: 200,
      enableSorting: false,
      cell: ({ row }) => {
        const notes = batchDecisionNotesByBatchId.get(row.original.batch_id) ?? [];
        const labels = Array.from(new Set(notes.flatMap((note) => note.labels ?? [])));
        const statuses = Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate')));
        if (!labels.length && !statuses.length) {
          return <Text type="secondary">--</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {statuses.map((status) => (
              <Tooltip
                key={`${row.original.batch_id}-${status}`}
                title={notes.filter((note) => (note.decision_status ?? 'candidate') === status).map((note) => note.decision_reason || note.content).join(' / ')}
              >
                <Tag color={decisionStatusColor(status)}>
                  {decisionStatusText(status)}
                </Tag>
              </Tooltip>
            ))}
            {labels.map((label) => (
              <Tooltip
                key={`${row.original.batch_id}-${label}`}
                title={notes.filter((note) => note.labels.includes(label)).map((note) => note.content).join(' / ')}
              >
                <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'blue'}>
                  {researchLabelText(label)}
                </Tag>
              </Tooltip>
            ))}
          </Space>
        );
      },
    },
    {
      header: '状态',
      size: 96,
      minSize: 96,
      cell: ({ row }) => <Tag color={experimentStatusColor(row.original.status)}>{row.original.status}</Tag>,
    },
    { id: 'created_at', header: '提交时间', size: 150, minSize: 150, accessorFn: (row) => row.created_at, cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: 'actions',
      header: '操作',
      size: 180,
      minSize: 180,
      enableSorting: false,
      cell: ({ row }) => (
        <Space>
          <Button size="small" type={row.original.batch_id === selectedBatchId ? 'primary' : 'default'} onClick={() => setSelectedBatchId(row.original.batch_id)}>
            查看批次
          </Button>
          <Popconfirm
            title="删除这个实验批次？"
            description={`batch_id: ${row.original.batch_id}`}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deletingBatchId === row.original.batch_id }}
            onConfirm={() => onDeleteBatch(row.original.batch_id)}
          >
            <Button size="small" danger loading={deletingBatchId === row.original.batch_id}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ], [batchDecisionNotesByBatchId, deletingBatchId, onDeleteBatch, selectedBatchId, setSelectedBatchId]);
  function openDecisionModal(targetType: string, targetId: string, title: string) {
    decisionForm.resetFields();
    decisionForm.setFieldsValue({ author: 'local', decision_status: 'candidate', labels: [] });
    setDecisionTarget({ targetType, targetId, title });
  }

  const batchParameterGroupColumns = useMemo<ColumnDef<NonNullable<ParameterExperimentBatchDetail['parameter_groups']>[number]>[]>(() => [
    { id: 'fast_slow', header: '快 / 慢', accessorFn: (row) => `${row.fast_period ?? ''}/${row.slow_period ?? ''}`, cell: ({ row }) => `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}` },
    { id: 'leverage', header: '杠杆', accessorFn: (row) => row.leverage ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.leverage ?? '--' },
    {
      id: 'labels',
      header: '参数组推荐标签',
      enableSorting: false,
      size: 240,
      minSize: 220,
      cell: ({ row }) => {
        const key = `${row.original.fast_period ?? 'na'}:${row.original.slow_period ?? 'na'}:${row.original.leverage ?? 'na'}`;
        const autoLabels = batchGroupLabelsByKey.get(key) ?? [];
        if (!autoLabels.length) {
          return <Text type="secondary">--</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {autoLabels.map((item) => (
              <Tooltip key={`${key}-${item.label}`} title={item.reason}>
                <Tag color={item.label === 'auto_excluded' ? 'red' : item.label === 'auto_high_return_candidate' ? 'blue' : item.label === 'auto_exploratory_candidate' ? 'purple' : 'green'}>
                  {item.label === 'auto_excluded'
                    ? '自动排除'
                    : item.label === 'auto_high_return_candidate'
                      ? '自动高收益候选'
                      : item.label === 'auto_exploratory_candidate'
                        ? '自动探索候选'
                        : '自动稳健候选'}
                </Tag>
              </Tooltip>
            ))}
          </Space>
        );
      },
    },
    {
      id: 'manual_labels',
      header: '人工决策标签',
      enableSorting: false,
      size: 220,
      minSize: 200,
      cell: ({ row }) => {
        const notes = batchGroupResearchNotesByKey.get(buildParameterGroupKey(row.original)) ?? [];
        const labels = Array.from(new Set(notes.flatMap((note) => note.labels ?? [])));
        const statuses = Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate')));
        if (!labels.length && !statuses.length) {
          return <Text type="secondary">--</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {statuses.map((status) => (
              <Tag color={decisionStatusColor(status)} key={`${buildParameterGroupKey(row.original)}-${status}`}>
                {decisionStatusText(status)}
              </Tag>
            ))}
            {labels.map((label) => (
              <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'default'} key={`${buildParameterGroupKey(row.original)}-${label}`}>
                {researchLabelText(label)}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    { id: 'snapshot_count', header: '覆盖快照', accessorFn: (row) => row.snapshot_count, cell: ({ row }) => row.original.snapshot_count },
    { id: 'run_count', header: 'Run 数', accessorFn: (row) => row.run_count, cell: ({ row }) => row.original.run_count },
    { id: 'score', header: '总分', accessorFn: (row) => row.score, cell: ({ row }) => formatNumber(row.original.score, 1) },
    { id: 'confidence', header: '置信度', accessorFn: (row) => row.confidence, cell: ({ row }) => formatNumber(row.original.confidence, 1) },
    { id: 'avg_total_return', header: '平均收益率', accessorFn: (row) => row.avg_total_return, cell: ({ row }) => formatPct(row.original.avg_total_return) },
    { id: 'avg_max_drawdown', header: '平均最大回撤', accessorFn: (row) => row.avg_max_drawdown, cell: ({ row }) => formatPct(row.original.avg_max_drawdown) },
    { id: 'worst_max_drawdown', header: '最差最大回撤', accessorFn: (row) => row.worst_max_drawdown, cell: ({ row }) => formatPct(row.original.worst_max_drawdown) },
    { id: 'return_over_drawdown', header: '收益回撤比', accessorFn: (row) => row.return_over_drawdown, cell: ({ row }) => formatNumber(row.original.return_over_drawdown, 2) },
    { id: 'avg_excess_return', header: '平均超额收益', accessorFn: (row) => row.avg_excess_return, cell: ({ row }) => formatPct(row.original.avg_excess_return) },
    { id: 'avg_oos_total_return', header: '平均样本外收益', accessorFn: (row) => row.avg_oos_total_return, cell: ({ row }) => formatPct(row.original.avg_oos_total_return) },
    { id: 'avg_oos_excess_return', header: '平均样本外超额', accessorFn: (row) => row.avg_oos_excess_return, cell: ({ row }) => formatPct(row.original.avg_oos_excess_return) },
    { id: 'is_oos_gap', header: 'IS/OOS 差', accessorFn: (row) => row.is_oos_gap ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.is_oos_gap) },
    { id: 'best_total_return', header: '最佳收益率', accessorFn: (row) => row.best_total_return, cell: ({ row }) => formatPct(row.original.best_total_return) },
    { id: 'positive_ratio', header: '正收益占比', accessorFn: (row) => row.positive_ratio, cell: ({ row }) => formatPct(row.original.positive_ratio) },
    { id: 'oos_positive_ratio', header: '样本外正收益占比', accessorFn: (row) => row.oos_positive_ratio ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_positive_ratio) },
    { id: 'neighbor_stability_score', header: '邻域稳定度', accessorFn: (row) => row.neighbor_stability_score ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.neighbor_stability_score) },
    { id: 'stable_neighbor_count', header: '稳定邻居', accessorFn: (row) => row.stable_neighbor_count, cell: ({ row }) => `${row.original.stable_neighbor_count} / ${row.original.neighbor_count}` },
    { id: 'min_trade_count', header: '最少交易数', accessorFn: (row) => row.min_trade_count ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.min_trade_count ?? '--' },
    {
      id: 'decision',
      header: '研究决策',
      enableSorting: false,
      size: 150,
      minSize: 140,
      cell: ({ row }) => {
        const targetId = selectedBatchDetail
          ? buildParameterGroupTargetId(selectedBatchDetail.batch.batch_id, row.original)
          : '';
        const notes = notesByTarget.get(`parameter_group:${targetId}`) ?? [];
        return (
          <Space>
            {notes.length ? (
              <Space size={[4, 4]} wrap>
                <Tag color="blue">{notes.length} 条</Tag>
                <Tag color={decisionStatusColor(notes[0]?.decision_status)}>{decisionStatusText(notes[0]?.decision_status)}</Tag>
              </Space>
            ) : <Text type="secondary">--</Text>}
            {targetId ? (
              <Button
                size="small"
                onClick={() => openDecisionModal(
                  'parameter_group',
                  targetId,
                  `参数组 快 ${row.original.fast_period ?? '--'} / 慢 ${row.original.slow_period ?? '--'} / 杠杆 ${row.original.leverage ?? '--'}`,
                )}
              >
                记录
              </Button>
            ) : null}
          </Space>
        );
      },
    },
  ], [batchGroupLabelsByKey, batchGroupResearchNotesByKey, notesByTarget, selectedBatchDetail]);
  const decisionLedgerColumns = useMemo<ColumnDef<ResearchNote>[]>(() => [
    {
      id: 'decision_status',
      header: '状态',
      size: 96,
      minSize: 96,
      accessorFn: (row) => row.decision_status ?? 'candidate',
      cell: ({ row }) => (
        <Tag color={decisionStatusColor(row.original.decision_status)}>
          {decisionStatusText(row.original.decision_status)}
        </Tag>
      ),
    },
    {
      id: 'target',
      header: '对象',
      size: 280,
      minSize: 240,
      accessorFn: (row) => `${row.target_type}:${row.target_id}`,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{targetTypeText(row.original.target_type)}</Text>
          <Text type="secondary" copyable>{row.original.target_id}</Text>
        </Space>
      ),
    },
    {
      id: 'labels',
      header: '标签',
      size: 220,
      minSize: 180,
      enableSorting: false,
      cell: ({ row }) => {
        const labels = row.original.labels ?? [];
        if (!labels.length) {
          return <Text type="secondary">--</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {labels.map((label) => (
              <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'blue'} key={`${row.original.note_id}-${label}`}>
                {researchLabelText(label)}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    {
      id: 'linked_batch_id',
      header: '关联批次',
      size: 220,
      minSize: 180,
      accessorFn: (row) => row.linked_batch_id ?? '',
      cell: ({ row }) => row.original.linked_batch_id ? <Text copyable>{row.original.linked_batch_id}</Text> : <Text type="secondary">--</Text>,
    },
    {
      id: 'linked_parameter_group',
      header: '关联参数组',
      size: 260,
      minSize: 220,
      accessorFn: (row) => row.linked_parameter_group ?? '',
      cell: ({ row }) => row.original.linked_parameter_group ? <Text copyable>{row.original.linked_parameter_group}</Text> : <Text type="secondary">--</Text>,
    },
    {
      id: 'confidence_score',
      header: '置信度',
      size: 92,
      minSize: 92,
      accessorFn: (row) => row.confidence_score ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => row.original.confidence_score ?? '--',
    },
    {
      id: 'decision_reason',
      header: '原因 / 备注',
      size: 320,
      minSize: 260,
      accessorFn: (row) => `${row.decision_reason ?? ''} ${row.content}`,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text>{row.original.decision_reason || '--'}</Text>
          <Text type="secondary" ellipsis={{ tooltip: row.original.content }}>{row.original.content}</Text>
        </Space>
      ),
    },
    { id: 'author', header: '记录人', size: 100, minSize: 90, accessorFn: (row) => row.author, cell: ({ row }) => row.original.author },
    { id: 'created_at', header: '时间', size: 160, minSize: 150, accessorFn: (row) => row.created_at, cell: ({ row }) => formatDateTime(row.original.created_at) },
  ], []);

  const resultStats = useMemo(() => {
    const sourceRows = workspaceMode === 'batch' ? filteredBatchRunRows : filteredExperimentRunRows;
    const baseRows = workspaceMode === 'batch' ? selectedBatchRows : selectedExperimentRows;
    const avgReturn = sourceRows.length
      ? sourceRows.reduce((sum, row) => sum + row.total_return, 0) / sourceRows.length
      : null;
    const bestReturn = sourceRows.length
      ? Math.max(...sourceRows.map((row) => row.total_return))
      : null;
    return {
      runCount: sourceRows.length,
      filteredCount: sourceRows.length,
      baseCount: baseRows.length,
      totalCount: allRows.length,
      avgReturn,
      bestReturn,
    };
  }, [allRows.length, filteredBatchRunRows, filteredExperimentRunRows, selectedBatchRows, selectedExperimentRows, workspaceMode]);

  const batchRecommendationSections = selectedBatchDetail
    ? [
      {
        key: 'robust',
        title: '稳健候选',
        type: 'success' as const,
        items: selectedBatchDetail.recommendations.robust_candidates.filter((item) => matchesBatchRecommendationFilters(item)),
        empty: groupDecisionLabelFilter.length || groupDecisionStatusFilter.length || autoLabelFilter.length ? '当前筛选下没有满足条件的稳健候选。' : '当前批次还没有满足规则的稳健候选，或已被人工拒绝 / 归档。',
        description: (item: ParameterExperimentBatchDetail['recommendations']['robust_candidates'][number]) => {
          const notes = batchGroupResearchNotesByKey.get(buildParameterGroupKey(item)) ?? [];
          const noteSummary = notes.length
            ? `；人工结论 ${Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate'))).map((status) => decisionStatusText(status)).join(' / ')}`
            : '';
          return `${item.reason}；总分 ${formatNumber(item.score, 1)}，置信度 ${formatNumber(item.confidence, 1)}，平均收益 ${formatPct(item.avg_total_return)}，最大回撤 ${formatPct(item.avg_max_drawdown)}，收益回撤比 ${formatNumber(item.return_over_drawdown, 2)}${noteSummary}。`;
        },
      },
      {
        key: 'high',
        title: '高收益候选',
        type: 'info' as const,
        items: selectedBatchDetail.recommendations.high_return_candidates.filter((item) => matchesBatchRecommendationFilters(item)),
        empty: groupDecisionLabelFilter.length || groupDecisionStatusFilter.length || autoLabelFilter.length ? '当前筛选下没有满足条件的高收益候选。' : '当前批次还没有可单独标记的高收益候选，或已被人工拒绝 / 归档。',
        description: (item: ParameterExperimentBatchDetail['recommendations']['high_return_candidates'][number]) => {
          const notes = batchGroupResearchNotesByKey.get(buildParameterGroupKey(item)) ?? [];
          const noteSummary = notes.length
            ? `；人工结论 ${Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate'))).map((status) => decisionStatusText(status)).join(' / ')}`
            : '';
          return `${item.reason}；总分 ${formatNumber(item.score, 1)}，置信度 ${formatNumber(item.confidence, 1)}，最佳收益 ${formatPct(item.best_total_return)}，最大回撤 ${formatPct(item.avg_max_drawdown)}${noteSummary}。`;
        },
      },
      {
        key: 'exclude',
        title: '需排除组合',
        type: 'warning' as const,
        items: selectedBatchDetail.recommendations.excluded_combinations.filter((item) => matchesBatchRecommendationFilters(item)),
        empty: groupDecisionLabelFilter.length || groupDecisionStatusFilter.length || autoLabelFilter.length ? '当前筛选下没有命中排除规则的组合。' : '当前批次没有明显应排除的组合，或已被人工归档。',
        description: (item: ParameterExperimentBatchDetail['recommendations']['excluded_combinations'][number]) => {
          const notes = batchGroupResearchNotesByKey.get(buildParameterGroupKey(item)) ?? [];
          const noteSummary = notes.length
            ? `；人工结论 ${Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate'))).map((status) => decisionStatusText(status)).join(' / ')}`
            : '';
          return `${item.reason}；总分 ${formatNumber(item.score, 1)}，置信度 ${formatNumber(item.confidence, 1)}，平均收益 ${formatPct(item.avg_total_return)}，最差回撤 ${formatPct(item.worst_max_drawdown)}${noteSummary}。`;
        },
      },
      {
        key: 'explore',
        title: '探索候选',
        type: 'info' as const,
        items: (selectedBatchDetail.recommendations.exploratory_candidates ?? []).filter((item) => matchesBatchRecommendationFilters(item)),
        empty: groupDecisionLabelFilter.length || groupDecisionStatusFilter.length || autoLabelFilter.length ? '当前筛选下没有探索候选。' : '当前批次没有仅可观察的探索候选，或已被人工拒绝 / 归档。',
        description: (item: ParameterExperimentBatchDetail['recommendations']['high_return_candidates'][number]) => {
          const notes = batchGroupResearchNotesByKey.get(buildParameterGroupKey(item)) ?? [];
          const noteSummary = notes.length
            ? `；人工结论 ${Array.from(new Set(notes.map((note) => note.decision_status ?? 'candidate'))).map((status) => decisionStatusText(status)).join(' / ')}`
            : '';
          return `${item.reason}；总分 ${formatNumber(item.score, 1)}，置信度 ${formatNumber(item.confidence, 1)}，平均收益 ${formatPct(item.avg_total_return)}，样本外交易数 ${item.min_oos_trade_count ?? 0}${noteSummary}。`;
        },
      },
    ]
    : [];
  const candidateRecommendationSections = batchRecommendationSections.filter((section) => section.key !== 'exclude');
  const excludedRecommendationSection = batchRecommendationSections.find((section) => section.key === 'exclude');

  return (
    <>
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {showExperimentForm ? (
        <Card
          className="cbw-experiment-form-card"
          title="发起实验批次"
          extra={(
            <Space>
              <Button onClick={() => void onRefreshExperiments()}>刷新状态</Button>
              <Button onClick={() => setShowExperimentForm(false)}>收起</Button>
            </Space>
          )}
        >
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            提交新的 EMA 参数实验批次。提交后回到下方工作区查看批次推荐、参数组和研究决策。
          </Paragraph>
          <Form form={experimentForm} layout="vertical" onFinish={(values) => void onSubmitExperiment(values as Record<string, unknown>)}>
            <Row gutter={12}>
              <Col xs={24} md={12} xl={8}>
                <Form.Item name="batch_id" label="批次 ID" rules={[{ required: true, whitespace: true, message: '请输入批次 ID' }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col xs={24} md={12} xl={8}>
                <Form.Item name="search_type" label="搜索方式" rules={[{ required: true }]}>
                  <Select
                    options={[
                      { label: '网格搜索', value: 'grid' },
                      { label: '随机搜索', value: 'random' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12} xl={8}>
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
              <Col span={24}>
                <Form.Item name="snapshot_ids" label="数据快照" rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一个数据快照' }]}>
                  <Select mode="multiple" options={datasetOptions} showSearch optionFilterProp="label" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="validation_split_mode" label="验证切分" rules={[{ required: true }]}>
                  <Segmented
                    block
                    options={[
                      { label: '自动 70/30', value: 'auto_ratio' },
                      { label: '手动', value: 'manual' },
                      { label: '不使用', value: 'none' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="oos_ratio_pct"
                  label="样本外比例 (%)"
                  rules={[
                    {
                      validator: async (_, value) => {
                        if (validationSplitMode !== 'auto_ratio') {
                          return;
                        }
                        if (value === null || value === undefined || value === '') {
                          throw new Error('请输入样本外比例');
                        }
                        const numeric = Number(value);
                        if (!Number.isFinite(numeric) || numeric <= 0 || numeric >= 100) {
                          throw new Error('样本外比例必须在 0 到 100 之间');
                        }
                      },
                    },
                  ]}
                >
                  <InputNumber min={1} max={99} step={5} disabled={validationSplitMode !== 'auto_ratio'} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="warmup_bars" label="切分预热 K 线">
                  <InputNumber min={0} step={1} disabled={validationSplitMode === 'none'} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              {validationSplitMode === 'manual' ? (
                <>
                  <Col xs={24} md={6}>
                    <Form.Item name="is_start" label="IS 开始" rules={[{ required: true, message: '请选择 IS 开始时间' }]}>
                      <DatePicker showTime style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item name="is_end" label="IS 结束" rules={[{ required: true, message: '请选择 IS 结束时间' }]}>
                      <DatePicker showTime style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item name="oos_start" label="OOS 开始" rules={[{ required: true, message: '请选择 OOS 开始时间' }]}>
                      <DatePicker showTime style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item name="oos_end" label="OOS 结束" rules={[{ required: true, message: '请选择 OOS 结束时间' }]}>
                      <DatePicker showTime style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </>
              ) : null}
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
                  name="leverage_candidates"
                  label="杠杆候选"
                  rules={[
                    {
                      validator: async (_, value) => {
                        const message = validatePositiveNumberListInput(value, '杠杆候选');
                        if (message) {
                          throw new Error(message);
                        }
                      },
                    },
                  ]}
                >
                  <Input placeholder="例如 1,2,3,5" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8} xl={4}>
                <Form.Item name="cash_allocation_pct" label="资金使用比例 (%)" rules={[{ required: true, message: '请输入资金使用比例' }]}>
                  <InputNumber min={0.01} max={100} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8} xl={4}>
                <Form.Item name="initial_cash" label="初始资金" rules={[{ required: true, message: '请输入初始资金' }]}>
                  <InputNumber min={0.01} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8} xl={4}>
                <Form.Item name="fee_rate" label="手续费率">
                  <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8} xl={4}>
                <Form.Item name="slippage_bps" label="滑点基点">
                  <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8} xl={4}>
                <Form.Item name="min_notional" label="最小名义价值">
                  <InputNumber min={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Alert
                type="info"
                showIcon
                message="当前边界"
                description="仍然只支持 EMA，多快照会拆成多个单快照实验。自动切分会按每个快照自己的时间范围使用前 70% 做 IS、后 30% 做 OOS。"
              />
              <Button block type="primary" htmlType="submit" loading={submitting === 'experiment'}>
                提交实验批次
              </Button>
            </Space>
          </Form>
        </Card>
      ) : null}
        <Card
          className="cbw-research-workbench"
          title={(
            <Space direction="vertical" size={0}>
              <Text strong>参数实验工作区</Text>
              <Text type="secondary" style={{ fontWeight: 400 }}>先看批次推荐和人工关注，再进入参数组、Run 和台账明细。</Text>
            </Space>
          )}
          extra={(
            <Space wrap>
              <Input
                placeholder="搜索 run / 数据集 / 标的"
                value={parameterQuery}
                onChange={(event) => setParameterQuery(event.target.value)}
                style={{ width: 260 }}
              />
              <Button onClick={() => setShowExperimentForm((value) => !value)}>
                {showExperimentForm ? '收起实验表单' : '新建实验批次'}
              </Button>
              <Button onClick={() => void onRefreshExperiments()}>刷新状态</Button>
            </Space>
          )}
        >
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="当前结果" value={resultStats.runCount} suffix={`/ ${resultStats.baseCount}`} /></Card></Col>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="筛选命中" value={resultStats.filteredCount} /></Card></Col>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="平均收益率" value={resultStats.avgReturn === null ? '--' : formatPct(resultStats.avgReturn)} /></Card></Col>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="最佳收益率" value={resultStats.bestReturn === null ? '--' : formatPct(resultStats.bestReturn)} /></Card></Col>
            </Row>
            <Segmented<'batch' | 'experiment' | 'decisions' | 'sensitivity'>
              block
              className="cbw-workbench-switcher"
              value={workspaceMode}
              onChange={setWorkspaceMode}
              options={[
                { label: '批次结果', value: 'batch' },
                { label: '单实验明细', value: 'experiment' },
                { label: '研究决策台账', value: 'decisions' },
                { label: '参数敏感度', value: 'sensitivity' },
              ]}
            />
            <Card size="small" className="cbw-filter-panel" title="筛选与定位">
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Space wrap>
                  {workspaceMode === 'batch' ? (
                    <>
                      <Select
                        mode="multiple"
                        allowClear
                        value={batchDecisionStatusFilter}
                        style={{ minWidth: 200 }}
                        placeholder="批次状态"
                        onChange={setBatchDecisionStatusFilter}
                        options={DECISION_STATUS_OPTIONS.filter((option) => availableBatchDecisionStatuses.includes(option.value))}
                      />
                      <Select
                        mode="multiple"
                        allowClear
                        value={batchDecisionLabelFilter}
                        style={{ minWidth: 210 }}
                        placeholder="批次标签"
                        onChange={setBatchDecisionLabelFilter}
                        options={availableBatchDecisionLabels.map((label) => ({
                          label: RESEARCH_LABEL_TEXT[label] ?? label,
                          value: label,
                        }))}
                      />
                      <Select
                        mode="multiple"
                        allowClear
                        disabled={autoLabelFilterDisabled}
                        value={autoLabelFilter}
                        style={{ minWidth: 220 }}
                        placeholder={autoLabelFilterDisabled ? '选择单个批次后筛自动标签' : '参数组自动标签'}
                        onChange={setAutoLabelFilter}
                        options={availableAutoLabels.map((label) => ({
                          label: AUTO_GROUP_MEMBERSHIP_LABEL_TEXT[label] ?? label,
                          value: label,
                        }))}
                      />
                      <Select
                        mode="multiple"
                        allowClear
                        disabled={selectedBatchId === ALL_BATCHES}
                        value={groupDecisionStatusFilter}
                        style={{ minWidth: 220 }}
                        placeholder={selectedBatchId === ALL_BATCHES ? '选择单个批次后筛参数组状态' : '参数组状态'}
                        onChange={setGroupDecisionStatusFilter}
                        options={DECISION_STATUS_OPTIONS.filter((option) => availableGroupDecisionStatuses.includes(option.value))}
                      />
                      <Select
                        mode="multiple"
                        allowClear
                        disabled={selectedBatchId === ALL_BATCHES}
                        value={groupDecisionLabelFilter}
                        style={{ minWidth: 220 }}
                        placeholder={selectedBatchId === ALL_BATCHES ? '选择单个批次后筛参数组标签' : '参数组标签'}
                        onChange={setGroupDecisionLabelFilter}
                        options={availableGroupDecisionLabels.map((label) => ({
                          label: RESEARCH_LABEL_TEXT[label] ?? label,
                          value: label,
                        }))}
                      />
                    </>
                  ) : (
                    <Select
                      mode="multiple"
                      allowClear
                      value={runManualLabelFilter}
                      style={{ minWidth: 220 }}
                      placeholder="Run 人工标签"
                      onChange={setRunManualLabelFilter}
                      options={availableRunManualLabels.map((label) => ({
                        label: RESEARCH_LABEL_TEXT[label] ?? label,
                        value: label,
                      }))}
                    />
                  )}
                </Space>
                {workspaceMode === 'batch' ? (
                  <Space wrap>
                    <InputNumber
                      min={0}
                      max={100}
                      step={5}
                      style={{ width: 132 }}
                      disabled={selectedBatchId === ALL_BATCHES}
                      value={minScoreFilter}
                      placeholder="最小总分"
                      onChange={(value) => setMinScoreFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={0}
                      max={100}
                      step={5}
                      style={{ width: 132 }}
                      disabled={selectedBatchId === ALL_BATCHES}
                      value={minConfidenceFilter}
                      placeholder="最小置信度"
                      onChange={(value) => setMinConfidenceFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={0}
                      max={100}
                      step={5}
                      style={{ width: 146 }}
                      disabled={selectedBatchId === ALL_BATCHES}
                      value={maxDrawdownFilter}
                      placeholder="最大回撤%"
                      onChange={(value) => setMaxDrawdownFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={0}
                      step={0.1}
                      style={{ width: 150 }}
                      disabled={selectedBatchId === ALL_BATCHES}
                      value={minReturnDrawdownFilter}
                      placeholder="最小收益回撤比"
                      onChange={(value) => setMinReturnDrawdownFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={1}
                      max={100}
                      step={1}
                      style={{ width: 120 }}
                      disabled={selectedBatchId === ALL_BATCHES}
                      value={topNFilter}
                      placeholder="Top N"
                      onChange={(value) => setTopNFilter(value === null ? null : Number(value))}
                    />
                  </Space>
                ) : null}
              </Space>
            </Card>

            {workspaceMode === 'batch' && (
              <Spin spinning={experimentDetailLoading}>
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text type="secondary">
                      批次视角优先看跨快照聚合后的推荐和参数稳定性，再决定是否进入单次 run 分析。
                    </Text>
                    <Space wrap>
                      <Select
                        value={selectedBatchId}
                        style={{ minWidth: 320 }}
                        placeholder="选择实验批次"
                        onChange={(value) => {
                          setSelectedBatchId(value);
                          setWorkspaceMode('batch');
                        }}
                        options={[
                          { label: '全部批次', value: ALL_BATCHES },
                          ...filteredBatches.map((batch) => ({
                            label: `${batch.batch_id} · ${batch.snapshot_count} 快照 · ${batch.status}`,
                            value: batch.batch_id,
                          })),
                        ]}
                      />
                      {selectedBatchSummary ? (
                        <Tag color={experimentStatusColor(selectedBatchSummary.status)}>{selectedBatchSummary.status}</Tag>
                      ) : null}
                      {selectedBatchId !== ALL_BATCHES ? (
                        <Popconfirm
                          title="删除当前实验批次？"
                          description={`batch_id: ${selectedBatchId}`}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deletingBatchId === selectedBatchId }}
                          onConfirm={() => onDeleteBatch(selectedBatchId)}
                        >
                          <Button danger loading={deletingBatchId === selectedBatchId}>删除当前批次</Button>
                        </Popconfirm>
                      ) : null}
                    </Space>
                  </Space>

                  {!batches.length ? (
                    <Alert type="info" showIcon message="当前还没有可查看的实验批次" />
                  ) : selectedBatchId === ALL_BATCHES ? (
                    <>
                      <DataTable
                        columns={batchColumns}
                        data={filteredBatches}
                        tableClassName="cbw-parameter-meta-table"
                        initialPageSize={6}
                        pageSizeOptions={[6, 12, 24]}
                        initialSorting={[{ id: 'created_at', desc: true }]}
                      />
                      {batchDecisionLabelFilter.length && !filteredBatches.length ? (
                        <Alert type="info" showIcon message="当前批次人工决策筛选没有命中批次" />
                      ) : null}
                      <Card size="small" title="全部批次结果">
                        <Paragraph type="secondary">
                          当前显示 {filteredBatchRunRows.length} 条 run。先整体排序筛掉明显差的组合，再进入具体批次查看推荐。
                        </Paragraph>
                        <DataTable
                          columns={experimentResultColumns}
                          data={filteredBatchRunRows}
                          tableClassName="cbw-parameter-result-table"
                          initialPageSize={8}
                          pageSizeOptions={[8, 16, 32]}
                          initialSorting={[{ id: 'total_return', desc: true }]}
                        />
                      </Card>
                    </>
                  ) : (
                    <>
                      <Card size="small" className="cbw-context-panel">
                        <Flex justify="space-between" align="flex-start" wrap="wrap" gap={12}>
                          <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ flex: 1, minWidth: 520 }}>
                            <Descriptions.Item label="批次 ID">{selectedBatchDetail?.batch.batch_id ?? selectedBatchId}</Descriptions.Item>
                            <Descriptions.Item label="搜索方式">{experimentSearchTypeLabel(selectedBatchDetail?.batch.search_type ?? selectedBatchSummary?.search_type)}</Descriptions.Item>
                            <Descriptions.Item label="快照 / 实验">{selectedBatchDetail?.batch.dataset_snapshot_ids.length ?? selectedBatchSummary?.snapshot_count ?? 0} / {selectedBatchDetail?.batch.experiment_ids.length ?? selectedBatchSummary?.experiment_count ?? 0}</Descriptions.Item>
                            <Descriptions.Item label="父任务">{selectedBatchDetail?.execution.task_id ?? selectedBatchSummary?.task_id ?? '--'}</Descriptions.Item>
                            <Descriptions.Item label="提交时间">{selectedBatchDetail?.batch.created_at ? formatDateTime(selectedBatchDetail.batch.created_at) : (selectedBatchSummary ? formatDateTime(selectedBatchSummary.created_at) : '--')}</Descriptions.Item>
                          </Descriptions>
                          {selectedBatchDetail ? (
                            <Button
                              size="small"
                              onClick={() => openDecisionModal(
                                'parameter_experiment_batch',
                                selectedBatchDetail.batch.batch_id,
                                `批次 ${selectedBatchDetail.batch.batch_id}`,
                              )}
                            >
                              记录批次结论
                            </Button>
                          ) : null}
                        </Flex>
                        <Space size={[6, 6]} wrap style={{ marginTop: 8 }}>
                          {batchDecisionNotes.length ? (
                            batchDecisionNotes.map((note) => (
                              <Tooltip key={note.note_id} title={note.content}>
                                <Tag color={decisionStatusColor(note.decision_status)}>
                                  {decisionStatusText(note.decision_status)} · {formatDateTime(note.created_at)}
                                </Tag>
                              </Tooltip>
                            ))
                          ) : <Text type="secondary">当前批次还没有人工结论。</Text>}
                        </Space>
                      </Card>
                      <Row gutter={[12, 12]} align="top">
                        <Col xs={24} xl={16}>
                          <Row gutter={[12, 12]}>
                            {candidateRecommendationSections.map((section) => (
                              <Col xs={24} lg={12} key={section.key}>
                                <Card size="small" title={section.title}>
                                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                                    {section.items.length ? section.items.map((item) => (
                                      <Alert
                                        key={`${section.key}-${item.fast_period}-${item.slow_period}-${item.leverage}`}
                                        type={section.type}
                                        showIcon
                                        message={`快 ${item.fast_period ?? '--'} / 慢 ${item.slow_period ?? '--'} / 杠杆 ${item.leverage ?? '--'}`}
                                        description={section.description(item)}
                                      />
                                    )) : <Text type="secondary">{section.empty}</Text>}
                                  </Space>
                                </Card>
                              </Col>
                            ))}
                          </Row>
                        </Col>
                        {excludedRecommendationSection ? (
                          <Col xs={24} xl={8}>
                            <Card size="small" title={excludedRecommendationSection.title}>
                              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                                {excludedRecommendationSection.items.length ? excludedRecommendationSection.items.map((item) => (
                                  <Alert
                                    key={`${excludedRecommendationSection.key}-${item.fast_period}-${item.slow_period}-${item.leverage}`}
                                    type={excludedRecommendationSection.type}
                                    showIcon
                                    message={`快 ${item.fast_period ?? '--'} / 慢 ${item.slow_period ?? '--'} / 杠杆 ${item.leverage ?? '--'}`}
                                    description={excludedRecommendationSection.description(item)}
                                  />
                                )) : <Text type="secondary">{excludedRecommendationSection.empty}</Text>}
                              </Space>
                            </Card>
                          </Col>
                        ) : null}
                      </Row>
                      <Card size="small" title="人工关注参数组">
                        {activeManualDecisionGroups.length ? (
                          <Row gutter={[12, 12]}>
                            {activeManualDecisionGroups.slice(0, 6).map((group) => {
                              const groupKey = buildParameterGroupKey(group);
                              const latestStatus = latestBatchGroupDecisionStatusByKey.get(groupKey) ?? 'candidate';
                              const notes = batchGroupResearchNotesByKey.get(groupKey) ?? [];
                              const latestNote = notes[0];
                              return (
                                <Col xs={24} xl={12} key={`manual-focus-${groupKey}`}>
                                  <Alert
                                    type={latestStatus === 'approved' ? 'success' : 'info'}
                                    showIcon
                                    message={(
                                      <Space size={[6, 6]} wrap>
                                        <Tag color={decisionStatusColor(latestStatus)}>{decisionStatusText(latestStatus)}</Tag>
                                        <Text>快 {group.fast_period ?? '--'} / 慢 {group.slow_period ?? '--'} / 杠杆 {group.leverage ?? '--'}</Text>
                                      </Space>
                                    )}
                                    description={`总分 ${formatNumber(group.score, 1)}，置信度 ${formatNumber(group.confidence, 1)}，平均收益 ${formatPct(group.avg_total_return)}，样本外收益 ${formatPct(group.avg_oos_total_return)}，最大回撤 ${formatPct(group.avg_max_drawdown)}${latestNote?.decision_reason ? `；${latestNote.decision_reason}` : ''}。`}
                                  />
                                </Col>
                              );
                            })}
                          </Row>
                        ) : (
                          <Text type="secondary">还没有通过或观察中的参数组。对参数组点“记录”，状态选择“观察”或“通过”后会出现在这里。</Text>
                        )}
                      </Card>
                      <Card size="small" title="批次聚合结果">
                        <Paragraph type="secondary">
                          这里已经把同一组快慢参数和杠杆按跨快照结果聚合。现在应优先看样本外收益、最大回撤、收益回撤比，再看样本内收益和覆盖快照数。
                        </Paragraph>
                        <DataTable
                          columns={batchParameterGroupColumns}
                          data={filteredBatchParameterGroups}
                          tableClassName="cbw-parameter-group-table"
                          initialPageSize={8}
                          pageSizeOptions={[8, 16, 32]}
                          initialSorting={[{ id: 'score', desc: true }]}
                        />
                      </Card>
                      <Card size="small" title="批次 Run 结果">
                        <Paragraph type="secondary">
                          当前显示 {filteredBatchRunRows.length} 条来自该批次的 run，可继续按收益、超额收益、胜率排序后跳转单次分析。
                        </Paragraph>
                        <DataTable
                          columns={experimentResultColumns}
                          data={filteredBatchRunRows}
                          tableClassName="cbw-parameter-result-table"
                          initialPageSize={8}
                          pageSizeOptions={[8, 16, 32]}
                          initialSorting={[{ id: 'total_return', desc: true }]}
                        />
                      </Card>
                      {selectedBatchDetail ? (
                        <Card size="small" title="评分标准">
                          <Row gutter={[12, 12]}>
                            {Object.values(selectedBatchDetail.scoring_rules).map((rule) => (
                              <Col xs={24} xl={8} key={rule.label}>
                                <Alert
                                  type="info"
                                  showIcon
                                  message={rule.label}
                                  description={(
                                    <Space direction="vertical" size={4}>
                                      <Text>{rule.summary}</Text>
                                      {rule.thresholds.map((threshold) => (
                                        <Text key={`${rule.label}-${threshold}`} type="secondary">- {threshold}</Text>
                                      ))}
                                    </Space>
                                  )}
                                />
                              </Col>
                            ))}
                          </Row>
                        </Card>
                      ) : null}
                    </>
                  )}
                </Space>
              </Spin>
            )}

            {workspaceMode === 'experiment' && (
              <Spin spinning={experimentDetailLoading}>
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text type="secondary">
                      单实验明细只看一次实验内部的子 run 结果，适合精确比较某个快照上的参数组合。
                    </Text>
                    <Space wrap>
                      <Select
                        value={selectedExperimentId}
                        style={{ minWidth: 320 }}
                        placeholder="选择参数实验"
                        onChange={(value) => {
                          setSelectedExperimentId(value);
                          setWorkspaceMode('experiment');
                        }}
                        options={[
                          { label: '全部实验', value: ALL_EXPERIMENTS },
                          ...visibleExperiments.map((experiment) => ({
                            label: `${experiment.experiment_id} · ${experimentSearchTypeLabel(experiment.search_type)} · ${experiment.status}`,
                            value: experiment.experiment_id,
                          })),
                        ]}
                      />
                      {selectedExperimentSummary ? (
                        <Tag color={experimentStatusColor(selectedExperimentSummary.status)}>{selectedExperimentSummary.status}</Tag>
                      ) : null}
                      {selectedExperimentId !== ALL_EXPERIMENTS ? (
                        <Popconfirm
                          title="删除当前参数实验？"
                          description={`experiment_id: ${selectedExperimentId}`}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deletingExperimentId === selectedExperimentId }}
                          onConfirm={() => onDeleteExperiment(selectedExperimentId)}
                        >
                          <Button danger loading={deletingExperimentId === selectedExperimentId}>删除当前实验</Button>
                        </Popconfirm>
                      ) : null}
                    </Space>
                  </Space>

                  {!visibleExperiments.length ? (
                    <Alert type="info" showIcon message="当前没有可查看的单实验结果" />
                  ) : (
                    <>
                      <Row gutter={[12, 12]}>
                        <Col xs={12} md={6}><Card size="small"><Statistic title="实验数" value={selectedExperimentId === ALL_EXPERIMENTS ? visibleExperiments.length : 1} /></Card></Col>
                        <Col xs={12} md={6}><Card size="small"><Statistic title="计划组合" value={selectedExperimentId === ALL_EXPERIMENTS ? visibleExperiments.reduce((sum, experiment) => sum + experiment.planned_run_count, 0) : (selectedExperimentDetail?.execution.planned_run_count ?? selectedExperimentSummary?.planned_run_count ?? 0)} /></Card></Col>
                        <Col xs={12} md={6}><Card size="small"><Statistic title="已生成 Run" value={selectedExperimentId === ALL_EXPERIMENTS ? selectedExperimentRows.length : (selectedExperimentDetail?.execution.run_ids?.length ?? selectedExperimentSummary?.run_count ?? 0)} /></Card></Col>
                        <Col xs={12} md={6}><Card size="small"><Statistic title="失败子任务" value={selectedExperimentId === ALL_EXPERIMENTS ? visibleExperiments.reduce((sum, experiment) => sum + experiment.failed_run_count, 0) : (failedChildTaskIds.length || selectedExperimentSummary?.failed_run_count || 0)} /></Card></Col>
                      </Row>
                      {selectedExperimentId === ALL_EXPERIMENTS ? (
                        <DataTable
                          columns={experimentColumns}
                          data={visibleExperiments}
                          tableClassName="cbw-parameter-meta-table"
                          initialPageSize={8}
                          pageSizeOptions={[8, 16, 24]}
                          initialSorting={[{ id: 'created_at', desc: true }]}
                        />
                      ) : (
                        <>
                          <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                            <Descriptions.Item label="实验 ID">{selectedExperimentDetail?.experiment.experiment_id ?? selectedExperimentId}</Descriptions.Item>
                            <Descriptions.Item label="搜索方式">{experimentSearchTypeLabel(selectedExperimentDetail?.experiment.search_type ?? selectedExperimentSummary?.search_type)}</Descriptions.Item>
                            <Descriptions.Item label="数据集">{selectedExperimentDetail?.experiment.dataset_bundle_id ?? selectedExperimentSummary?.dataset_bundle_id ?? '--'}</Descriptions.Item>
                            <Descriptions.Item label="父任务">{selectedExperimentDetail?.execution.task_id ?? selectedExperimentSummary?.task_id ?? '--'}</Descriptions.Item>
                            <Descriptions.Item label="提交时间">{selectedExperimentDetail?.experiment.created_at ? formatDateTime(selectedExperimentDetail.experiment.created_at) : (selectedExperimentSummary ? formatDateTime(selectedExperimentSummary.created_at) : '--')}</Descriptions.Item>
                            <Descriptions.Item label="随机种子策略">{selectedExperimentDetail?.experiment.seed_policy ?? '--'}</Descriptions.Item>
                          </Descriptions>
                          {failedChildTaskIds.length ? (
                            <Alert
                              type="warning"
                              showIcon
                              message={`有 ${failedChildTaskIds.length} 个子任务失败`}
                              description={`失败任务：${failedChildTaskIds.join('，')}`}
                            />
                          ) : null}
                        </>
                      )}
                      <Card size="small" title="实验 Run 结果">
                        <Paragraph type="secondary">
                          当前显示 {filteredExperimentRunRows.length} 条已落盘 run。优先按样本外收益、样本外超额排序，再回头看总收益和胜率。
                        </Paragraph>
                        <DataTable
                          columns={experimentResultColumns}
                          data={filteredExperimentRunRows}
                          tableClassName="cbw-parameter-result-table"
                          initialPageSize={8}
                          pageSizeOptions={[8, 16, 32]}
                          initialSorting={[{ id: 'total_return', desc: true }]}
                        />
                      </Card>
                    </>
                  )}
                </Space>
              </Spin>
            )}

            {workspaceMode === 'decisions' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Alert
                  type="info"
                  showIcon
                  message="研究决策台账"
                  description="这里保留所有人工判断记录。最新状态用于当前参数组判断，历史记录用于复盘决策变化。"
                />
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="全部记录" value={researchNotes.length} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="当前命中" value={filteredDecisionLedgerNotes.length} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="通过 / 观察" value={researchNotes.filter((note) => note.decision_status === 'approved' || note.decision_status === 'observing').length} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="拒绝 / 归档" value={researchNotes.filter((note) => note.decision_status === 'rejected' || note.decision_status === 'archived').length} /></Card></Col>
                </Row>
                <Space wrap>
                  <Select
                    mode="multiple"
                    allowClear
                    value={decisionLedgerStatusFilter}
                    style={{ minWidth: 220 }}
                    placeholder="按状态筛选"
                    onChange={setDecisionLedgerStatusFilter}
                    options={DECISION_STATUS_OPTIONS.filter((option) => availableDecisionLedgerStatuses.includes(option.value))}
                  />
                  <Select
                    mode="multiple"
                    allowClear
                    value={decisionLedgerLabelFilter}
                    style={{ minWidth: 220 }}
                    placeholder="按标签筛选"
                    onChange={setDecisionLedgerLabelFilter}
                    options={availableDecisionLedgerLabels.map((label) => ({
                      label: researchLabelText(label),
                      value: label,
                    }))}
                  />
                  <Select
                    mode="multiple"
                    allowClear
                    value={decisionLedgerTargetTypeFilter}
                    style={{ minWidth: 220 }}
                    placeholder="按对象类型筛选"
                    onChange={setDecisionLedgerTargetTypeFilter}
                    options={availableDecisionLedgerTargetTypes.map((targetType) => ({
                      label: targetTypeText(targetType),
                      value: targetType,
                    }))}
                  />
                  <Select
                    allowClear
                    showSearch
                    value={decisionLedgerBatchFilter}
                    style={{ minWidth: 280 }}
                    placeholder="按关联批次筛选"
                    onChange={(value) => setDecisionLedgerBatchFilter(value ?? null)}
                    options={availableDecisionLedgerBatchIds.map((batchId) => ({
                      label: batchId,
                      value: batchId,
                    }))}
                  />
                  <Select
                    allowClear
                    showSearch
                    value={decisionLedgerParameterGroupFilter}
                    style={{ minWidth: 320 }}
                    placeholder="按关联参数组筛选"
                    onChange={(value) => setDecisionLedgerParameterGroupFilter(value ?? null)}
                    options={availableDecisionLedgerParameterGroups.map((groupId) => ({
                      label: groupId,
                      value: groupId,
                    }))}
                  />
                </Space>
                <DataTable
                  columns={decisionLedgerColumns}
                  data={filteredDecisionLedgerNotes}
                  tableClassName="cbw-parameter-meta-table"
                  initialPageSize={10}
                  pageSizeOptions={[10, 20, 50]}
                  initialSorting={[{ id: 'created_at', desc: true }]}
                />
              </Space>
            )}

            {workspaceMode === 'sensitivity' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Alert
                  type="info"
                  showIcon
                  message="怎么看这两张图"
                  description="先看蓝线 Avg Return 是否整体在 0 上方，再看橙线 Best Return 是否只是个别尖峰。优先选择一段稳定区间，不要只追单点冠军。"
                />
                <Row gutter={[16, 16]}>
                  <Col xs={24} xl={12}>
                    <Card size="small" title="Fast period 敏感度">
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
                    <Card size="small" title="Slow period 敏感度">
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
                </Row>
                <Card size="small" title="当前筛选结果">
                  <DataTable
                    columns={experimentResultColumns}
                    data={rows}
                    initialPageSize={8}
                    pageSizeOptions={[8, 16, 32]}
                    initialSorting={[{ id: 'total_return', desc: true }]}
                  />
                </Card>
              </Space>
            )}
          </Space>
        </Card>
    </Space>
    <Modal
      title={decisionTarget ? `研究决策 · ${decisionTarget.title}` : '研究决策'}
      open={Boolean(decisionTarget)}
      okText="保存"
      cancelText="取消"
      confirmLoading={savingResearchNote}
      onCancel={() => setDecisionTarget(null)}
      onOk={async () => {
        if (!decisionTarget) {
          return;
        }
        const values = await decisionForm.validateFields();
        await onSaveResearchNote(decisionTarget.targetType, decisionTarget.targetId, values);
        setDecisionTarget(null);
      }}
    >
      <Form form={decisionForm} layout="vertical">
        <Form.Item name="author" label="记录人" rules={[{ required: true, whitespace: true, message: '请输入记录人' }]}>
          <Input />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={24} md={12}>
            <Form.Item name="decision_status" label="决策状态" rules={[{ required: true, message: '请选择决策状态' }]}>
              <Select options={DECISION_STATUS_OPTIONS} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="confidence_score" label="置信度">
              <InputNumber min={0} max={100} precision={1} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="labels" label="标签">
          <Select mode="multiple" options={RESEARCH_LABEL_OPTIONS} />
        </Form.Item>
        <Form.Item name="decision_reason" label="状态原因">
          <Input />
        </Form.Item>
        <Form.Item name="content" label="结论" rules={[{ required: true, whitespace: true, message: '请输入研究结论' }]}>
          <Input.TextArea rows={4} />
        </Form.Item>
      </Form>
    </Modal>
    </>
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
