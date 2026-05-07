import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import type { ColumnDef, SortingState } from '@tanstack/react-table';
import dayjs from 'dayjs';
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  ConfigProvider,
  Collapse,
  DatePicker,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Layout,
  Modal,
  Popconfirm,
  Progress,
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
  deleteResearchNote,
  deleteRun,
  loadDatasets,
  loadParameterExperimentBatchDetail,
  loadParameterExperimentBatches,
  loadParameterExperimentDetail,
  loadParameterExperiments,
  loadParameterGroupDetail,
  loadParameterResearch,
  loadResearchCandidateFilterResults,
  loadResearchCandidateTradeAttribution,
  loadResearchWorkflow,
  loadOverview,
  loadOverviewEquity,
  loadParameters,
  loadPaperSession,
  loadPaperSessions,
  loadPaperSignalSnapshot,
  loadResearchNotes,
  loadRunDetail,
  loadRuns,
  postIngest,
  postParameterExperimentBatch,
  postPaperSession,
  postPaperSessionTick,
  postResearchCandidateFilterExperiment,
  postResearchCandidateRiskMatrix,
  postResearchNote,
  postResearchPool,
  postRun,
  postRunEma,
  postStableCandidateExecutionVerification,
  postStableCandidateExecutionFilterExperiment,
  postStablePool,
} from './lib/api';
import { formatDateRange, formatDateTime, formatNumber, formatPct, shortRunId } from './lib/format';
import type {
  DatasetSnapshotView,
  ParameterExperimentBatchDetail,
  ParameterExperimentBatchSummary,
  ParameterExperimentDetail,
  ParameterExperimentSummary,
  ParameterGroupDetail,
  ParameterGroupRunView,
  ParameterGroupView,
  ParameterResearchWorkspace,
  ParameterLabRow,
  ResearchCandidateFilterResults,
  FilterResultGroup,
  EarlyFailAttributionBucket,
  StopLossAttributionBucket,
  TradeAttributionBucket,
  TradeAttributionView,
  ResearchCandidateView,
  ResearchWorkflow,
  ScreeningRunView,
  StableCandidateView,
  ResearchNote,
  RunAnalysisView,
  RunSummaryView,
  SensitivityRow,
  MultiRunEquityRow,
  PaperFillView,
  PaperOrderView,
  PaperSessionView,
  PaperSignalSnapshotView,
  PaperTradeView,
  PaperWarningView,
  WorkspaceParameterLab,
  WorkspaceOverview,
  WorkspaceSource,
} from './types';

const { Header, Content } = Layout;
const { Title, Paragraph, Text } = Typography;

type TabId = 'execution' | 'overview' | 'analysis' | 'parameters' | 'paper';

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

interface ResearchRunCandidate {
  row: ParameterLabRow;
  score: number;
  tags: string[];
  gap: number | null;
  reason: string;
}

interface RunDrawdownWindow {
  peakIndex: number;
  troughIndex: number;
  peakTime: string;
  troughTime: string;
  peakEquity: number;
  troughEquity: number;
  maxDrawdown: number;
  drawdownAmount: number;
  recoveryTime: string | null;
  recoveryBars: number | null;
}

interface RunDrawdownAttributionBucket {
  dimension: string;
  bucket_key: string;
  label: string;
  trade_count: number;
  loss_count: number;
  net_pnl: number;
  loss_pnl: number;
  loss_share: number;
  avg_return_pct: number;
  stop_loss_count: number;
  stop_loss_rate: number;
  early_exit_count: number;
}

interface RunEntryFeatureAttributionBucket {
  dimension: string;
  bucket_key: string;
  label: string;
  drawdown_trade_count: number;
  drawdown_loss_count: number;
  drawdown_loss_rate: number;
  drawdown_loss_pnl: number;
  drawdown_loss_share: number;
  drawdown_avg_return_pct: number;
  baseline_trade_count: number;
  baseline_loss_rate: number | null;
  baseline_avg_return_pct: number | null;
  loss_rate_delta: number | null;
  avg_return_delta: number | null;
  sample_ok: boolean;
  judgement: 'candidate' | 'weak' | 'baseline_missing' | 'not_issue';
}

interface RiskMatrixProgress {
  batchId: string;
  status: string;
  runCount: number;
  plannedRunCount: number;
}

interface FilterExperimentProgress {
  batchId: string;
  status: string;
  runCount: number;
  plannedRunCount: number;
}

type FilterExperimentProfile = 'early_fail_proxy' | 'general';

interface DrawdownProtectionComparisonRow {
  protection: string;
  run_id: string;
  total_return: number;
  oos_total_return: number | null;
  max_drawdown: number;
  profit_factor: number | null;
  trade_count: number;
  oos_trade_count: number | null;
  oos_delta: number | null;
  drawdown_delta: number | null;
  profit_factor_delta: number | null;
  trade_retention: number | null;
  verdict: 'baseline' | 'improved' | 'mixed' | 'worse';
}

const EARLY_FAIL_PROXY_FILTER_TYPES = [
  'early_fail_proxy_core',
] as const;

const EARLY_FAIL_PROXY_SIGNAL_FILTER_SETS = [
  ...[-0.005, 0, 0.005, 0.01].map((threshold) => ({
    filter_set_id: `pre-mom3-gte-${String(threshold).replace('-', 'neg-').replace('.', 'p')}`,
    label: `MOM3>=${formatPct(threshold)}`,
    mode: 'single',
    filters: [{
      filter_type: 'pre_entry_momentum',
      enabled: true,
      params: { lookback_bars: 3, min_momentum_pct: threshold },
    }],
  })),
  ...[0.4, 0.5, 0.6, 0.7].map((threshold) => ({
    filter_set_id: `local-position-gte-${String(threshold).replace('.', 'p')}`,
    label: `局部位>=${formatNumber(threshold, 1)}`,
    mode: 'single',
    filters: [{
      filter_type: 'local_range_position',
      enabled: true,
      params: { lookback_bars: 20, min_position: threshold },
    }],
  })),
  {
    filter_set_id: 'local04-exclude-chop-mom3-1-3',
    label: '局部位>=0.4 + 排除震荡MOM3',
    mode: 'stacked',
    filters: [
      {
        filter_type: 'local_range_position',
        enabled: true,
        params: { lookback_bars: 20, min_position: 0.4 },
      },
      {
        filter_type: 'entry_context_exclusion',
        enabled: true,
        params: {
          conditions: [
            { field: 'range_chop_score_20', min: 0.8 },
            { field: 'pre_entry_momentum_3_pct', min: 0.01, max: 0.03 },
          ],
        },
      },
    ],
  },
  {
    filter_set_id: 'local04-exclude-chop-trendgap',
    label: '局部位>=0.4 + 排除震荡趋势间距',
    mode: 'stacked',
    filters: [
      {
        filter_type: 'local_range_position',
        enabled: true,
        params: { lookback_bars: 20, min_position: 0.4 },
      },
      {
        filter_type: 'entry_context_exclusion',
        enabled: true,
        params: {
          conditions: [
            { field: 'range_chop_score_20', min: 0.8 },
            { field: 'trend_gap_atr', min: 0.5, max: 2 },
          ],
        },
      },
    ],
  },
  {
    filter_set_id: 'local04-exclude-mom3-entrydist',
    label: '局部位>=0.4 + 排除MOM3回踩',
    mode: 'stacked',
    filters: [
      {
        filter_type: 'local_range_position',
        enabled: true,
        params: { lookback_bars: 20, min_position: 0.4 },
      },
      {
        filter_type: 'entry_context_exclusion',
        enabled: true,
        params: {
          conditions: [
            { field: 'pre_entry_momentum_3_pct', min: 0.01, max: 0.03 },
            { field: 'entry_distance_atr', min: 0.5, max: 1 },
          ],
        },
      },
    ],
  },
  {
    filter_set_id: 'early-fail-proxy-core',
    label: 'MOM3>=0 + 连续>=1 + 局部位>=0.5',
    mode: 'stacked',
    filters: [
      {
        filter_type: 'pre_entry_momentum',
        enabled: true,
        params: { lookback_bars: 3, min_momentum_pct: 0 },
      },
      {
        filter_type: 'consecutive_move',
        enabled: true,
        params: { min_consecutive: 1 },
      },
      {
        filter_type: 'local_range_position',
        enabled: true,
        params: { lookback_bars: 20, min_position: 0.5 },
      },
    ],
  },
];

const GENERAL_FILTER_TYPES = [
  'higher_timeframe_trend',
  'atr_percentile',
  'adx',
] as const;

type ResearchConclusionBucketKey = 'primary' | 'robust' | 'aggressive' | 'risk_reduction' | 'excluded';

interface ResearchConclusionItem {
  group: ParameterGroupView;
  score: number;
  reasons: string[];
}

interface ResearchConclusionBucket {
  key: ResearchConclusionBucketKey;
  title: string;
  tone: 'success' | 'info' | 'warning' | 'error';
  description: string;
  items: ResearchConclusionItem[];
}

type ParameterWorkspaceMode = 'launch' | 'screening' | 'research' | 'stable' | 'tracking' | 'batch' | 'experiment' | 'decisions' | 'sensitivity';

interface NeighborhoodRunMatch {
  row: ParameterLabRow;
  isSource: boolean;
  fastDelta: number | null;
  slowDelta: number | null;
  distance: number;
}

type RunCompareSectionKey = 'identity' | 'parameters' | 'performance' | 'risk';

interface RunCompareField {
  key: string;
  label: string;
  section: RunCompareSectionKey;
  value: (row: ParameterLabRow) => number | string | null | undefined;
  format?: (value: number | string | null | undefined) => string;
  better?: 'higher' | 'lower';
}

interface RunCompareRow {
  key: string;
  label: string;
  leftValue: number | string | null | undefined;
  rightValue: number | string | null | undefined;
  leftText: string;
  rightText: string;
  same: boolean;
  leftBetter: boolean;
  rightBetter: boolean;
}

interface RunCompareSection {
  key: RunCompareSectionKey;
  title: string;
  rows: RunCompareRow[];
}

interface RunCompareModel {
  left: ParameterLabRow;
  right: ParameterLabRow;
  sections: RunCompareSection[];
  sameCount: number;
  diffCount: number;
  summary: string;
}

interface NeighborhoodStabilityStats {
  sampleCount: number;
  positiveOosRatio: number | null;
  positiveReturnRatio: number | null;
  avgOosReturn: number | null;
  avgGap: number | null;
  worstDrawdown: number | null;
  minTradeCount: number | null;
  avgProfitFactor: number | null;
  score: number | null;
  verdict: 'stable' | 'watch' | 'unstable' | 'insufficient';
  verdictText: string;
  reason: string;
}

const TAB_OPTIONS = [
  { label: '执行台', value: 'execution' },
  { label: '运行总览', value: 'overview' },
  { label: '单次分析', value: 'analysis' },
  { label: '参数实验', value: 'parameters' },
  { label: '模拟盘', value: 'paper' },
] satisfies Array<{ label: string; value: TabId }>;

const ALL_EXPERIMENTS = '__all__';
const ALL_BATCHES = '__all_batches__';
const SCREENING_VIEW_STATE_STORAGE_KEY = 'cbw.screening.view.v1';
const RUN_DETAIL_READMODEL_VERSION = 'entry-feature-backfill-20260505-3';
const PAPER_SESSION_REFRESH_MS = 60_000;
const makeParameterBatchId = () => `batch-${dayjs().format('YYYYMMDDHHmmssSSS')}`;
function stableStringHash(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

const safeBatchKeyPart = (value: string) => {
  const normalized = value.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'run';
  return `${normalized.slice(0, 64)}-${stableStringHash(value)}`;
};
const TREND_PERIOD_LADDER = [2, 3, 5, 8, 13, 21, 34, 55, 89];
const RESEARCH_LABEL_OPTIONS = [
  { label: '基准', value: 'baseline' },
  { label: '候选', value: 'candidate' },
  { label: '稳健候选', value: 'robust_candidate' },
  { label: '高收益候选', value: 'high_return_candidate' },
  { label: '冻结参数', value: 'frozen_run' },
  { label: '追踪中', value: 'tracking' },
  { label: '待复核', value: 'review' },
  { label: '排除', value: 'excluded' },
];
const RESEARCH_LABEL_TEXT: Record<string, string> = {
  baseline: '基准',
  candidate: '候选',
  robust_candidate: '稳健候选',
  high_return_candidate: '高收益候选',
  frozen_run: '冻结参数',
  tracking: '追踪中',
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
const BATCH_STATUS_TEXT: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  success: '成功',
  failed: '失败',
};
const AUTO_GROUP_MEMBERSHIP_LABEL_TEXT: Record<string, string> = {
  auto_robust_candidate: '所属稳健参数组',
  auto_high_return_candidate: '所属高收益参数组',
  auto_exploratory_candidate: '所属探索参数组',
  auto_excluded: '所属排除参数组',
};
const STRATEGY_OPTIONS = [
  { label: 'EMA Crossover v1', value: 'ema_crossover' },
  { label: 'EMA Pullback ATR v2', value: 'ema_pullback_atr_v2' },
];

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
  risk_pct_per_trade: '单笔风险比例',
  fee_rate: '手续费率',
  slippage_bps: '滑点基点',
  min_notional: '最小名义价值',
  qty_by_policy: '按策略下单数量',
  cash_allocation_pct_by_policy: '按策略资金使用比例 (%)',
  risk_pct_per_trade_by_policy: '按策略单笔风险比例',
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
    ema_pullback_atr_v2: 'EMA Pullback ATR',
  },
  qty_policy_ref: {
    fixed_1: '固定数量 fixed_1',
    percent_of_cash: '按可用资金比例动态开仓 percent_of_cash',
    risk_pct_of_equity: '按账户权益风险开仓 risk_pct_of_equity',
    risk_pct_of_cash_allocation: '先圈定资金、再按单笔风险开仓 risk_pct_of_cash_allocation',
  },
};

const QTY_POLICY_OPTIONS = [
  { label: '资金比例', value: 'percent_of_cash' },
  { label: '单笔风险', value: 'risk_pct_of_equity' },
  { label: '资金内单笔风险', value: 'risk_pct_of_cash_allocation' },
];

const usesRiskPct = (qtyPolicyRef: string) => (
  qtyPolicyRef === 'risk_pct_of_equity' || qtyPolicyRef === 'risk_pct_of_cash_allocation'
);

const usesCashAllocation = (qtyPolicyRef: string) => (
  qtyPolicyRef === 'percent_of_cash' || qtyPolicyRef === 'risk_pct_of_cash_allocation'
);

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

function experimentStatusText(status: string | undefined): string {
  return status ? (BATCH_STATUS_TEXT[status] ?? status) : '--';
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

function executionVerificationStatusText(value: string | null | undefined): string {
  if (value === 'passed') {
    return '已验证';
  }
  if (value === 'failed') {
    return '未通过';
  }
  return '待验证';
}

function executionVerificationStatusColor(value: string | null | undefined): string {
  if (value === 'passed') {
    return 'green';
  }
  if (value === 'failed') {
    return 'red';
  }
  return 'default';
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

function parameterGroupClassificationText(value: string): string {
  if (value === 'robust_candidate') {
    return '稳健候选';
  }
  if (value === 'high_return_candidate') {
    return '高收益候选';
  }
  if (value === 'exploratory_candidate') {
    return '探索候选';
  }
  if (value === 'excluded') {
    return '排除';
  }
  return value;
}

function parameterGroupClassificationColor(value: string): string {
  if (value === 'robust_candidate') {
    return 'green';
  }
  if (value === 'high_return_candidate') {
    return 'blue';
  }
  if (value === 'exploratory_candidate') {
    return 'purple';
  }
  if (value === 'excluded') {
    return 'red';
  }
  return 'default';
}

type ParameterPoint = { key: string; label: string; value: string };
type ScreeningRiskItem = {
  key: string;
  dimension: string;
  label: string;
  sampleCount: number;
  avgOosReturn: number | null;
  avgOosExcess: number | null;
  avgDrawdown: number | null;
  avgProfitFactor: number | null;
  negativeOosRatio: number | null;
  severity: 'danger' | 'warning';
  reason: string;
};
type ScreeningViewState = {
  labelFilter: string[];
  strategyFilter: string | null;
  symbolFilter: string | null;
  minScoreFilter: number | null;
  minOosReturnFilter: number | null;
  minIsExcessReturnFilter: number | null;
  maxGapFilter: number | null;
  maxDrawdownFilter: number | null;
  minProfitFactorFilter: number | null;
  minTradeCountFilter: number | null;
  sorting: SortingState;
};

function markRunAddedToResearchPool(workflow: ResearchWorkflow | null, run: ScreeningRunView | ParameterLabRow): ResearchWorkflow | null {
  if (!workflow) {
    return workflow;
  }
  const sourceRun = 'auto_labels' in run
    ? run
    : workflow.screening_pool.runs.find((item) => item.run_id === run.run_id);
  if (!sourceRun) {
    return workflow;
  }
  const candidateExists = workflow.research_pool.candidates.some((candidate) => candidate.source_run_ids.includes(sourceRun.run_id));
  return {
    ...workflow,
    screening_pool: {
      ...workflow.screening_pool,
      runs: workflow.screening_pool.runs.map((item) => (
        item.run_id === sourceRun.run_id ? { ...item, pool_status: 'research_pool' } : item
      )),
    },
    research_pool: candidateExists
      ? workflow.research_pool
      : {
        ...workflow.research_pool,
        candidates: [
          {
            candidate_id: `pending:${sourceRun.run_id}`,
            source_run_ids: [sourceRun.run_id],
            strategy_name: sourceRun.strategy_name,
            symbol: sourceRun.symbol,
            timeframe: sourceRun.timeframe,
            validation_split_id: sourceRun.validation_split_id,
            entry_structure: {},
            risk_profile: {},
            representative_run_id: sourceRun.run_id,
            representative_run_score: sourceRun.score,
            status: '候选',
            recommendation: '正在刷新研究池视图',
            neighborhood_summary: { status: '待刷新', verdict: null, score: null },
            risk_matrix_summary: { status: '待刷新', best_option: null },
            latest_note: null,
            updated_at: null,
          },
          ...workflow.research_pool.candidates,
        ],
      },
  };
}

function compactPct(value: number | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return `${formatNumber(value * 100, value * 100 >= 10 ? 0 : 1)}%`;
}

function formatSignedPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '--';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${formatPct(value)}`;
}

function formatSignedNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '--';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${formatNumber(value, digits)}`;
}

function findRunMaxDrawdownWindow(equityRows: RunAnalysisView['equity_rows']): RunDrawdownWindow | null {
  if (equityRows.length < 2) {
    return null;
  }
  let peakIndex = 0;
  let peakEquity = equityRows[0].strategy_equity;
  let best: RunDrawdownWindow | null = null;
  for (let index = 1; index < equityRows.length; index += 1) {
    const equity = equityRows[index].strategy_equity;
    if (equity > peakEquity) {
      peakEquity = equity;
      peakIndex = index;
      continue;
    }
    if (peakEquity <= 0) {
      continue;
    }
    const drawdown = (peakEquity - equity) / peakEquity;
    if (!best || drawdown > best.maxDrawdown) {
      best = {
        peakIndex,
        troughIndex: index,
        peakTime: equityRows[peakIndex].timestamp,
        troughTime: equityRows[index].timestamp,
        peakEquity,
        troughEquity: equity,
        maxDrawdown: drawdown,
        drawdownAmount: peakEquity - equity,
        recoveryTime: null,
        recoveryBars: null,
      };
    }
  }
  if (!best) {
    return null;
  }
  const recoveryIndex = equityRows.findIndex((row, index) => index > best.troughIndex && row.strategy_equity >= best.peakEquity);
  return {
    ...best,
    recoveryTime: recoveryIndex >= 0 ? equityRows[recoveryIndex].timestamp : null,
    recoveryBars: recoveryIndex >= 0 ? recoveryIndex - best.troughIndex : null,
  };
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== 'string') {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function finiteNumberFromUnknown(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function numericTradeMeta(trade: RunAnalysisView['trade_rows'][number], key: string): number | null {
  const rowValue = finiteNumberFromUnknown((trade as unknown as Record<string, unknown>)[key]);
  if (rowValue !== null) {
    return rowValue;
  }
  const meta = recordFromUnknown(trade.entry_signal_meta_json);
  const directValue = finiteNumberFromUnknown(meta?.[key]);
  if (directValue !== null) {
    return directValue;
  }
  const nestedFeatures = recordFromUnknown(meta?.feature_values);
  return finiteNumberFromUnknown(nestedFeatures?.[key]);
}

function bucketNumber(value: number | null, buckets: Array<[number, string, string]>, fallback = '未知'): { key: string; label: string } {
  if (value === null) {
    return { key: 'unknown', label: fallback };
  }
  for (const [limit, key, label] of buckets) {
    if (value < limit) {
      return { key, label };
    }
  }
  const last = buckets[buckets.length - 1];
  return { key: `gte_${last?.[0] ?? 0}`, label: `>= ${last?.[0] ?? 0}` };
}

function runDrawdownBucketForTrade(trade: RunAnalysisView['trade_rows'][number], dimension: string): { key: string; label: string } {
  if (dimension === 'side') {
    return { key: trade.side, label: trade.side === 'long' ? '多头' : trade.side === 'short' ? '空头' : trade.side };
  }
  if (dimension === 'exit_reason') {
    return { key: trade.exit_reason || 'open', label: tradeAttributionBucketLabel({ dimension: 'exit_reason', label: trade.exit_reason || 'open' }) };
  }
  if (dimension === 'holding_bars') {
    if (trade.holding_bars <= 3) {
      return { key: 'le_3', label: '<= 3 根' };
    }
    if (trade.holding_bars <= 12) {
      return { key: '4_12', label: '4-12 根' };
    }
    return { key: 'gt_12', label: '> 12 根' };
  }
  if (dimension === 'pre_entry_momentum_3_pct' || dimension === 'pre_entry_momentum_5_pct') {
    const value = numericTradeMeta(trade, dimension);
    if (value === null) {
      return { key: 'unknown', label: '未知' };
    }
    if (value < -0.01) {
      return { key: 'lt_neg_1', label: '< -1%' };
    }
    if (value < 0) {
      return { key: 'neg_1_0', label: '-1%-0%' };
    }
    if (value < 0.01) {
      return { key: '0_1', label: '0%-1%' };
    }
    if (value < 0.03) {
      return { key: '1_3', label: '1%-3%' };
    }
    return { key: 'gte_3', label: '>= 3%' };
  }
  if (dimension === 'pre_entry_consecutive_move') {
    const value = numericTradeMeta(trade, dimension);
    if (value === null) {
      return { key: 'unknown', label: '未知' };
    }
    if (value <= 0) {
      return { key: 'none', label: '连续顺向 0' };
    }
    if (value <= 2) {
      return { key: '1_2', label: '连续顺向 1-2' };
    }
    if (value <= 4) {
      return { key: '3_4', label: '连续顺向 3-4' };
    }
    return { key: 'gte_5', label: '连续顺向 >= 5' };
  }
  if (dimension === 'local_range_position_20') {
    const value = numericTradeMeta(trade, dimension);
    return bucketNumber(value, [
      [0.4, 'lt_0_4', '< 0.4'],
      [0.6, '0_4_0_6', '0.4-0.6'],
      [0.8, '0_6_0_8', '0.6-0.8'],
    ], '未知');
  }
  if (dimension === 'trend_gap_atr') {
    const value = numericTradeMeta(trade, dimension);
    return bucketNumber(value, [
      [0.5, 'lt_0_5', '< 0.5'],
      [1, '0_5_1', '0.5-1'],
      [2, '1_2', '1-2'],
    ], '未知');
  }
  if (dimension === 'entry_distance_atr') {
    const value = numericTradeMeta(trade, dimension);
    return bucketNumber(value, [
      [0.25, 'lt_0_25', '< 0.25'],
      [0.5, '0_25_0_5', '0.25-0.5'],
      [1, '0_5_1', '0.5-1'],
    ], '未知');
  }
  if (dimension === 'breakout_wick_atr' || dimension === 'range_chop_score_20') {
    const value = numericTradeMeta(trade, dimension);
    return bucketNumber(value, [
      [0.2, 'lt_0_2', '< 0.2'],
      [0.5, '0_2_0_5', '0.2-0.5'],
      [0.8, '0_5_0_8', '0.5-0.8'],
    ], '未知');
  }
  if (dimension === 'ema_fast_slope_3_atr') {
    const value = numericTradeMeta(trade, dimension);
    return bucketNumber(value, [
      [-0.25, 'lt_neg_0_25', '< -0.25'],
      [0, 'neg_0_25_0', '-0.25-0'],
      [0.25, '0_0_25', '0-0.25'],
      [0.75, '0_25_0_75', '0.25-0.75'],
    ], '未知');
  }
  if (dimension === 'path_no_favorable_3') {
    const value = numericTradeMeta(trade, dimension);
    if (value === null) {
      return { key: 'unknown', label: '未知' };
    }
    return value >= 0.5 ? { key: 'yes', label: '前三根无浮盈' } : { key: 'no', label: '前三根有浮盈' };
  }
  return { key: 'unknown', label: '未知' };
}

function buildRunDrawdownAttributionBuckets(trades: RunAnalysisView['trade_rows'], dimensions: string[]): RunDrawdownAttributionBucket[] {
  const totalLoss = trades.reduce((sum, trade) => sum + (trade.net_pnl < 0 ? Math.abs(trade.net_pnl) : 0), 0);
  const groups = new Map<string, RunDrawdownAttributionBucket>();
  for (const trade of trades) {
    for (const dimension of dimensions) {
      const bucket = runDrawdownBucketForTrade(trade, dimension);
      const groupKey = `${dimension}:${bucket.key}`;
      const current = groups.get(groupKey) ?? {
        dimension,
        bucket_key: bucket.key,
        label: bucket.label,
        trade_count: 0,
        loss_count: 0,
        net_pnl: 0,
        loss_pnl: 0,
        loss_share: 0,
        avg_return_pct: 0,
        stop_loss_count: 0,
        stop_loss_rate: 0,
        early_exit_count: 0,
      };
      current.trade_count += 1;
      current.net_pnl += trade.net_pnl;
      current.avg_return_pct += trade.return_pct;
      if (trade.net_pnl < 0) {
        current.loss_count += 1;
        current.loss_pnl += Math.abs(trade.net_pnl);
      }
      if (trade.exit_reason === 'stop_loss_intrabar') {
        current.stop_loss_count += 1;
      }
      if (trade.holding_bars <= 3) {
        current.early_exit_count += 1;
      }
      groups.set(groupKey, current);
    }
  }
  return Array.from(groups.values())
    .map((bucket) => ({
      ...bucket,
      avg_return_pct: bucket.trade_count ? bucket.avg_return_pct / bucket.trade_count : 0,
      loss_share: totalLoss > 0 ? bucket.loss_pnl / totalLoss : 0,
      stop_loss_rate: bucket.trade_count ? bucket.stop_loss_count / bucket.trade_count : 0,
    }))
    .filter((bucket) => bucket.loss_pnl > 0)
    .sort((left, right) => right.loss_share - left.loss_share || right.loss_pnl - left.loss_pnl);
}

function buildRunEntryFeatureAttributionBuckets(
  drawdownTrades: RunAnalysisView['trade_rows'],
  baselineTrades: RunAnalysisView['trade_rows'],
  dimensions: string[],
): RunEntryFeatureAttributionBucket[] {
  const totalDrawdownLoss = drawdownTrades.reduce((sum, trade) => sum + (trade.net_pnl < 0 ? Math.abs(trade.net_pnl) : 0), 0);
  const rows: RunEntryFeatureAttributionBucket[] = [];

  for (const dimension of dimensions) {
    const drawdownGroups = new Map<string, { key: string; label: string; trades: RunAnalysisView['trade_rows'] }>();
    const baselineGroups = new Map<string, { key: string; label: string; trades: RunAnalysisView['trade_rows'] }>();

    for (const trade of drawdownTrades) {
      const bucket = runDrawdownBucketForTrade(trade, dimension);
      const current = drawdownGroups.get(bucket.key) ?? { key: bucket.key, label: bucket.label, trades: [] };
      current.trades.push(trade);
      drawdownGroups.set(bucket.key, current);
    }
    for (const trade of baselineTrades) {
      const bucket = runDrawdownBucketForTrade(trade, dimension);
      const current = baselineGroups.get(bucket.key) ?? { key: bucket.key, label: bucket.label, trades: [] };
      current.trades.push(trade);
      baselineGroups.set(bucket.key, current);
    }

    for (const group of drawdownGroups.values()) {
      if (group.key === 'unknown') {
        continue;
      }
      const drawdownTradeCount = group.trades.length;
      const drawdownLossTrades = group.trades.filter((trade) => trade.net_pnl < 0);
      const drawdownLossPnl = drawdownLossTrades.reduce((sum, trade) => sum + Math.abs(trade.net_pnl), 0);
      if (drawdownLossPnl <= 0) {
        continue;
      }
      const baseline = baselineGroups.get(group.key);
      const baselineTradeCount = baseline?.trades.length ?? 0;
      const baselineLossTrades = baseline?.trades.filter((trade) => trade.net_pnl < 0) ?? [];
      const drawdownAvgReturn = group.trades.reduce((sum, trade) => sum + trade.return_pct, 0) / drawdownTradeCount;
      const baselineAvgReturn = baselineTradeCount
        ? baseline!.trades.reduce((sum, trade) => sum + trade.return_pct, 0) / baselineTradeCount
        : null;
      const drawdownLossRate = drawdownLossTrades.length / drawdownTradeCount;
      const baselineLossRate = baselineTradeCount ? baselineLossTrades.length / baselineTradeCount : null;
      const lossRateDelta = baselineLossRate === null ? null : drawdownLossRate - baselineLossRate;
      const avgReturnDelta = baselineAvgReturn === null ? null : drawdownAvgReturn - baselineAvgReturn;
      const drawdownLossShare = totalDrawdownLoss > 0 ? drawdownLossPnl / totalDrawdownLoss : 0;
      const sample_ok = drawdownTradeCount >= 5 && baselineTradeCount >= 20;
      const judgement: RunEntryFeatureAttributionBucket['judgement'] = baselineTradeCount === 0
        ? 'baseline_missing'
        : sample_ok && drawdownLossShare >= 0.15 && (lossRateDelta ?? 0) >= 0.15 && (avgReturnDelta ?? 0) < 0
          ? 'candidate'
          : drawdownLossShare >= 0.1 && ((lossRateDelta ?? 0) > 0.05 || (avgReturnDelta ?? 0) < 0)
            ? 'weak'
            : 'not_issue';

      rows.push({
        dimension,
        bucket_key: group.key,
        label: group.label,
        drawdown_trade_count: drawdownTradeCount,
        drawdown_loss_count: drawdownLossTrades.length,
        drawdown_loss_rate: drawdownLossRate,
        drawdown_loss_pnl: drawdownLossPnl,
        drawdown_loss_share: drawdownLossShare,
        drawdown_avg_return_pct: drawdownAvgReturn,
        baseline_trade_count: baselineTradeCount,
        baseline_loss_rate: baselineLossRate,
        baseline_avg_return_pct: baselineAvgReturn,
        loss_rate_delta: lossRateDelta,
        avg_return_delta: avgReturnDelta,
        sample_ok,
        judgement,
      });
    }
  }

  return rows.sort((left, right) => {
    const judgementRank = (value: RunEntryFeatureAttributionBucket['judgement']) => (
      value === 'candidate' ? 3 : value === 'weak' ? 2 : value === 'baseline_missing' ? 1 : 0
    );
    return judgementRank(right.judgement) - judgementRank(left.judgement)
      || right.drawdown_loss_share - left.drawdown_loss_share
      || right.drawdown_loss_pnl - left.drawdown_loss_pnl;
  });
}

function runEntryFeatureJudgement(bucket: RunEntryFeatureAttributionBucket): { text: string; color: string } {
  if (bucket.judgement === 'candidate') {
    return { text: '候选', color: 'red' };
  }
  if (bucket.judgement === 'weak') {
    return { text: '弱线索', color: 'orange' };
  }
  if (bucket.judgement === 'baseline_missing') {
    return { text: '缺基线', color: 'default' };
  }
  return { text: '一般', color: 'blue' };
}

function buildRunEntryFeatureConclusion(
  buckets: RunEntryFeatureAttributionBucket[],
): { type: 'warning' | 'info' | 'success'; message: string; description: string } {
  const candidates = buckets.filter((bucket) => bucket.judgement === 'candidate');
  if (candidates.length) {
    const top = candidates[0];
    return {
      type: 'warning',
      message: `${tradeAttributionDimensionLabel(top.dimension)} ${top.label} 是优先验证的入场前回撤代理`,
      description: `最大回撤段亏损占比 ${formatPct(top.drawdown_loss_share)}，亏损率比非回撤段高 ${formatSignedPct(top.loss_rate_delta)}，均收益差 ${formatSignedPct(top.avg_return_delta)}。下一步适合把它转成过滤实验，而不是继续调 DD 停开。`,
    };
  }
  const weak = buckets.filter((bucket) => bucket.judgement === 'weak');
  if (weak.length) {
    const top = weak[0];
    return {
      type: 'info',
      message: `${tradeAttributionDimensionLabel(top.dimension)} ${top.label} 有弱线索，但还不足以直接做规则`,
      description: `它贡献了 ${formatPct(top.drawdown_loss_share)} 的回撤段亏损；但样本或相对非回撤段差异不够强，建议结合第二个特征做组合拆解。`,
    };
  }
  return {
    type: 'success',
    message: '当前回撤段没有被单一入场前特征稳定解释',
    description: '这通常说明需要补充更贴近行情状态的特征，或用两个特征组合拆解，例如动量+局部位置、波动+趋势间距。',
  };
}

const TRADE_ATTRIBUTION_DIMENSION_LABELS: Record<string, string> = {
  side: '方向',
  exit_reason: '退出结果',
  segment: '样本段',
  holding_bars: '持仓时长',
  stop_distance_pct: '止损距离',
  take_profit_distance_pct: '止盈距离',
  reward_risk_ratio: '盈亏比',
  atr_pct: '波动率',
  trend_gap_pct: '趋势间距',
  trend_gap_atr: '趋势间距',
  entry_distance_atr: '回踩贴近度',
  breakout_distance_atr: '突破力度',
  pre_entry_momentum_3_pct: '入场前3根动量',
  pre_entry_momentum_5_pct: '入场前5根动量',
  pre_entry_consecutive_move: '连续顺向',
  local_range_position_20: '20根局部位置',
  local_extreme_distance_atr: '局部极值距离',
  ema_reclaim: 'EMA收回',
  ema_reclaim_strength_atr: 'EMA收回力度',
  ema_fast_slope_3_atr: '快线斜率',
  range_chop_score_20: '震荡程度',
  breakout_wick_atr: '突破影线压力',
  volatility_percentile_100: '波动分位',
  '趋势+回踩': '趋势+回踩',
  '趋势+突破': '趋势+突破',
  '波动+回踩': '波动+回踩',
  '方向+趋势': '方向+趋势',
  '动量+回踩': '动量+回踩',
  '局部位置+突破': '局部位置+突破',
  '波动分位+趋势': '波动分位+趋势',
  'EMA收回+突破': 'EMA收回+突破',
  path_mfe_3_stop_r: '前三根浮盈',
  path_mae_1_stop_r: '首根反向幅度',
  path_mae_3_stop_r: '前三根反向幅度',
  path_first_bar_adverse: '首根路径',
  path_no_favorable_3: '前三根路径',
};

const TRADE_ATTRIBUTION_DIMENSION_HELP: Record<string, string> = {
  side: '入场前已知，可比较多空两侧是否质量差异明显。',
  exit_reason: '交易结束后的结果，只能解释亏损来源，不能直接当入场过滤条件。',
  segment: '样本切分标签，主要用于检查 IS/OOS 覆盖。',
  holding_bars: '交易结束后才知道的持仓长度，只能辅助解释，不能直接过滤入场。',
  stop_distance_pct: '止损距离占价格比例，来自入场时的风险结构。',
  take_profit_distance_pct: '止盈距离占价格比例，来自入场时的目标空间。',
  reward_risk_ratio: '止盈距离与止损距离的比例，来自入场时的收益风险结构。',
  atr_pct: '入场时 ATR 占价格比例，反映当时波动环境。',
  trend_gap_pct: '入场前快慢趋势线拉开的距离，占价格比例。',
  trend_gap_atr: '入场前快慢趋势线拉开的距离，以 ATR 为单位；不是止损倍数。',
  entry_distance_atr: '回踩点距离入场 EMA 的距离，以 ATR 为单位。',
  breakout_distance_atr: '价格突破前高/前低的幅度，以 ATR 为单位。',
  pre_entry_momentum_3_pct: '入场前 3 根 K 的顺交易方向涨跌幅；数值越高表示越追顺向拉伸。',
  pre_entry_momentum_5_pct: '入场前 5 根 K 的顺交易方向涨跌幅，用来观察入场前是否已经消耗过多。',
  pre_entry_consecutive_move: '入场前连续顺交易方向收盘的根数。',
  local_range_position_20: '入场价在前 20 根局部区间里的顺向位置；越高越接近多头前高或空头前低。',
  local_extreme_distance_atr: '入场价距离前 20 根顺向局部高/低点的距离，以 ATR 为单位。',
  ema_reclaim: '信号 K 是否触及入场 EMA 后又按交易方向收回。',
  ema_reclaim_strength_atr: '信号 K 收盘相对入场 EMA 的顺向距离，以 ATR 为单位。',
  ema_fast_slope_3_atr: '入场前快 EMA 最近 3 根的顺交易方向斜率，以 ATR 为单位。',
  range_chop_score_20: '前 20 根总振幅相对首尾净位移的比值归一化；越高越接近震荡消耗。',
  breakout_wick_atr: '突破前高/前低后留下的反向影线压力，以 ATR 为单位。',
  volatility_percentile_100: '当前 ATR 相对前 100 根波动范围的分位，反映波动环境是否极端。',
  '趋势+回踩': '入场前趋势间距与回踩贴近度的组合。',
  '趋势+突破': '入场前趋势间距与突破力度的组合。',
  '波动+回踩': '入场前波动水平与回踩贴近度的组合。',
  '方向+趋势': '交易方向与入场前趋势间距的组合。',
  '动量+回踩': '入场前顺向拉伸与回踩贴近度的组合。',
  '局部位置+突破': '20 根局部位置与突破影线压力的组合。',
  '波动分位+趋势': '波动分位与趋势间距的组合。',
  'EMA收回+突破': 'EMA 收回状态与突破影线压力的组合。',
  path_mfe_3_stop_r: '入场后前三根 K 的最大浮盈，按止损距离 R 计。',
  path_mae_1_stop_r: '入场后第一根 K 的最大反向幅度，按止损距离 R 计。',
  path_mae_3_stop_r: '入场后前三根 K 的最大反向幅度，按止损距离 R 计。',
  path_first_bar_adverse: '入场后第一根 K 是否反向大于顺向。',
  path_no_favorable_3: '入场后三根 K 是否基本没有给出浮盈空间。',
};

const TRADE_ATTRIBUTION_ACTIONABLE_DIMENSIONS = new Set([
  'side',
  'atr_pct',
  'trend_gap_pct',
  'trend_gap_atr',
  'entry_distance_atr',
  'breakout_distance_atr',
  'pre_entry_momentum_3_pct',
  'pre_entry_momentum_5_pct',
  'pre_entry_consecutive_move',
  'local_range_position_20',
  'local_extreme_distance_atr',
  'ema_reclaim',
  'ema_reclaim_strength_atr',
  'ema_fast_slope_3_atr',
  'range_chop_score_20',
  'breakout_wick_atr',
  'volatility_percentile_100',
  '趋势+回踩',
  '趋势+突破',
  '波动+回踩',
  '方向+趋势',
  '动量+回踩',
  '局部位置+突破',
  '波动分位+趋势',
  'EMA收回+突破',
]);

const TRADE_ATTRIBUTION_RESULT_DIMENSIONS = new Set(['exit_reason', 'segment', 'holding_bars']);

type TradeAttributionLabelLike = {
  dimension: string;
  label: string;
};

function tradeAttributionDimensionLabel(value: string): string {
  return TRADE_ATTRIBUTION_DIMENSION_LABELS[value] ?? value;
}

function tradeAttributionDimensionHelp(value: string): string {
  return TRADE_ATTRIBUTION_DIMENSION_HELP[value] ?? '归因分桶字段。';
}

function tradeAttributionBucketLabel(bucket: TradeAttributionLabelLike): string {
  const raw = bucket.label.replace(`${bucket.dimension} `, '');
  if (bucket.dimension === 'side') {
    return raw === 'long' ? '多头' : raw === 'short' ? '空头' : raw;
  }
  if (bucket.dimension === 'exit_reason') {
    const labels: Record<string, string> = {
      stop_loss_intrabar: '触发止损',
      take_profit_intrabar: '触发止盈',
      open: '未平仓',
    };
    return labels[raw] ?? raw;
  }
  if (bucket.dimension === 'segment') {
    return raw.toUpperCase();
  }
  if (bucket.dimension === 'holding_bars') {
    return raw.replace('holding <= 3', '<= 3 根').replace('holding 4-12', '4-12 根').replace('holding > 12', '> 12 根');
  }
  if (bucket.dimension.includes('+')) {
    return raw
      .replace(/long/g, '多头')
      .replace(/short/g, '空头')
      .replace(/path_first_bar_adverse /g, '')
      .replace(/path_no_favorable_3 /g, '');
  }
  if (bucket.dimension.startsWith('path_')) {
    return raw.replace(`${bucket.dimension} `, '');
  }
  if (bucket.dimension.endsWith('_atr')) {
    return `${raw} ATR`;
  }
  return raw;
}

function earlyFailAttributionJudgement(bucket: EarlyFailAttributionBucket): { text: string; color: string } {
  if (!bucket.sample_ok) {
    return { text: '样本不足', color: 'default' };
  }
  if (bucket.oos_trade_count > 0 && bucket.oos_trade_count < 10) {
    return { text: 'OOS不足', color: 'orange' };
  }
  if (bucket.oos_confirms === true) {
    return { text: 'OOS复现', color: 'red' };
  }
  if (bucket.is_early_fail_rate_delta >= 0.05) {
    return { text: 'IS高早败', color: 'red' };
  }
  if (bucket.oos_confirms === false) {
    return { text: 'OOS未复现', color: 'default' };
  }
  if (bucket.is_early_fail_rate_delta <= -0.03) {
    return { text: '低早败', color: 'green' };
  }
  return { text: '接近总体', color: 'blue' };
}

function earlyFailAttributionScore(bucket: EarlyFailAttributionBucket): number {
  return (bucket.sample_ok ? 100 : 0)
    + (bucket.oos_confirms ? 50 : 0)
    + Math.max(0, bucket.is_early_fail_rate_delta) * 120
    + bucket.is_early_fail_count
    + bucket.is_early_fail_stop_loss_rate * 20;
}

function buildEarlyFailAttributionConclusion(buckets: EarlyFailAttributionBucket[]): { type: 'warning' | 'info' | 'success'; message: string; description: string } {
  if (!buckets.length) {
    return {
      type: 'info',
      message: '没有达到复验门槛的早期失败入场前共性',
      description: '强信号为空时，下方会展示可用的弱线索；这些线索只能说明方向，不适合直接转过滤规则。',
    };
  }
  const confirmed = buckets.filter((bucket) => bucket.oos_confirms === true);
  if (confirmed.length) {
    const top = confirmed[0];
    return {
      type: 'warning',
      message: `${tradeAttributionDimensionLabel(top.dimension)} ${tradeAttributionBucketLabel(top)} 更容易出现早期失败`,
      description: `IS 早败率高于总体 ${formatSignedPct(top.is_early_fail_rate_delta)}，早败后止损率 ${formatPct(top.is_early_fail_stop_loss_rate)}；OOS 同桶早败率也高于总体 ${formatSignedPct(top.oos_early_fail_rate_delta)}。这是过滤实验候选，不是直接交易规则。`,
    };
  }
  const top = buckets[0];
  if (top.is_early_fail_rate_delta >= 0.05) {
    return {
      type: 'info',
      message: `${tradeAttributionDimensionLabel(top.dimension)} ${tradeAttributionBucketLabel(top)} 在 IS 中早败偏高，但 OOS 暂未确认`,
      description: `IS ${top.is_trade_count} 笔中 ${top.is_early_fail_count} 笔早败，早败率高于总体 ${formatSignedPct(top.is_early_fail_rate_delta)}。需要 OOS 或跨候选复验后才能转成过滤实验。`,
    };
  }
  return {
    type: 'success',
    message: '没有稳定复现的早期失败入场前代理特征',
    description: '当前早期失败没有被入场前分桶稳定解释；下方弱线索可用于判断是否需要补充特征或继续做组合拆解。',
  };
}

function tradeAttributionBucketTagColor(bucket: TradeAttributionBucket): string {
  if (!bucket.sample_ok) {
    return 'default';
  }
  if (bucket.is_underperforming) {
    return 'red';
  }
  if (!bucket.is_underperforming && bucket.is_avg_return_delta >= 0 && (bucket.is_profit_factor ?? 0) >= 1) {
    return 'green';
  }
  return 'blue';
}

function tradeAttributionBucketIssueScore(bucket: TradeAttributionBucket): number {
  const pfDeltaPenalty = bucket.is_pf_delta === null ? 0 : Math.max(0, -bucket.is_pf_delta) * 20;
  const returnPenalty = Math.max(0, -bucket.is_avg_return_delta) * 1000;
  const netPenalty = bucket.is_net_pnl < 0 ? 10 : 0;
  return (bucket.is_underperforming ? 100 : 0) + (bucket.oos_confirms ? 50 : 0) + pfDeltaPenalty + returnPenalty + netPenalty;
}

function tradeAttributionBucketJudgement(bucket: TradeAttributionBucket): { text: string; color: string } {
  if (!bucket.sample_ok) {
    return { text: '样本不足', color: 'default' };
  }
  if (TRADE_ATTRIBUTION_RESULT_DIMENSIONS.has(bucket.dimension)) {
    return { text: '解释结果', color: 'orange' };
  }
  if (bucket.oos_confirms === true) {
    return { text: 'OOS复现', color: 'red' };
  }
  if (bucket.is_underperforming) {
    return { text: 'IS变差', color: 'red' };
  }
  if (bucket.oos_confirms === false) {
    return { text: 'OOS未复现', color: 'default' };
  }
  if (!bucket.is_underperforming && bucket.is_avg_return_delta >= 0 && (bucket.is_profit_factor ?? 0) >= 1) {
    return { text: '相对健康', color: 'green' };
  }
  return { text: '观察', color: 'blue' };
}

function stopLossAttributionJudgement(bucket: StopLossAttributionBucket): { text: string; color: string } {
  if (!bucket.sample_ok) {
    return { text: '样本不足', color: 'default' };
  }
  if (bucket.oos_confirms === true) {
    return { text: 'OOS复现', color: 'red' };
  }
  if (bucket.is_stop_loss_rate_delta >= 0.05) {
    return { text: 'IS高止损', color: 'red' };
  }
  if (bucket.oos_confirms === false) {
    return { text: 'OOS未复现', color: 'default' };
  }
  if (bucket.is_stop_loss_rate_delta <= -0.03) {
    return { text: '低止损', color: 'green' };
  }
  return { text: '接近总体', color: 'blue' };
}

function stopLossAttributionScore(bucket: StopLossAttributionBucket): number {
  return (bucket.sample_ok ? 100 : 0)
    + (bucket.oos_confirms ? 50 : 0)
    + bucket.is_stop_loss_loss_share * 200
    + Math.max(0, bucket.is_stop_loss_rate_delta) * 100
    + bucket.is_stop_loss_count;
}

function buildStopLossAttributionConclusion(buckets: StopLossAttributionBucket[]): { type: 'warning' | 'info' | 'success'; message: string; description: string } {
  if (!buckets.length) {
    return {
      type: 'info',
      message: '没有找到足够样本的止损亏损拆解',
      description: '当前可用入场特征不足，或止损样本没有形成稳定分桶。',
    };
  }
  const confirmed = buckets.filter((bucket) => bucket.oos_confirms === true);
  if (confirmed.length) {
    const top = confirmed[0];
    return {
      type: 'warning',
      message: `${tradeAttributionDimensionLabel(top.dimension)} ${tradeAttributionBucketLabel(top as unknown as TradeAttributionBucket)} 是优先复验的止损原因`,
      description: `IS 止损亏损 ${formatNumber(top.is_stop_loss_net_pnl, 2)}，占 IS 止损亏损 ${formatPct(top.is_stop_loss_loss_share)}，止损率高于总体 ${formatSignedPct(top.is_stop_loss_rate_delta)}；OOS 同桶止损率也高于总体 ${formatSignedPct(top.oos_stop_loss_rate_delta)}。`,
    };
  }
  const top = buckets[0];
  if (top.is_stop_loss_loss_share >= 0.1) {
    return {
      type: 'info',
      message: `IS 止损亏损主要集中在 ${tradeAttributionDimensionLabel(top.dimension)} ${tradeAttributionBucketLabel(top as unknown as TradeAttributionBucket)}，但 OOS 暂未确认`,
      description: `这说明它是 IS 里的亏损来源之一：IS 止损亏损 ${formatNumber(top.is_stop_loss_net_pnl, 2)}，占比 ${formatPct(top.is_stop_loss_loss_share)}。如果 OOS高于总体没有同步为正，不能直接按这个桶改规则。`,
    };
  }
  return {
    type: 'success',
    message: '没有稳定复现的止损原因',
    description: '当前止损亏损没有被某个入场前特征稳定解释。更可能是策略常态止损、可用特征不够，或原因需要用组合特征/行情阶段继续拆解。',
  };
}

function isPrimaryTradeAttributionBucket(bucket: TradeAttributionBucket, totalTradeCount: number): boolean {
  if (!bucket.sample_ok || !TRADE_ATTRIBUTION_ACTIONABLE_DIMENSIONS.has(bucket.dimension)) {
    return false;
  }
  if (totalTradeCount > 0 && bucket.trade_count / totalTradeCount > 0.95) {
    return false;
  }
  return bucket.is_trade_count >= 30 && (bucket.is_underperforming || bucket.oos_confirms !== null);
}

function isPrimaryStopLossAttributionBucket(bucket: StopLossAttributionBucket): boolean {
  return bucket.sample_ok
    && bucket.is_trade_count >= 30
    && (bucket.is_stop_loss_rate_delta >= 0.03 || bucket.is_stop_loss_loss_share >= 0.1);
}

function isPathStopLossAttributionBucket(bucket: StopLossAttributionBucket): boolean {
  return bucket.sample_ok
    && bucket.is_trade_count >= 20
    && (bucket.bucket_family === 'combo' || bucket.dimension.startsWith('path_'))
    && (bucket.is_stop_loss_rate_delta >= 0.03 || bucket.is_stop_loss_loss_share >= 0.08);
}

function isPrimaryEarlyFailAttributionBucket(bucket: EarlyFailAttributionBucket): boolean {
  return bucket.sample_ok
    && bucket.is_trade_count >= 30
    && TRADE_ATTRIBUTION_ACTIONABLE_DIMENSIONS.has(bucket.dimension)
    && (
      bucket.oos_confirms === true
      || bucket.bucket_family === 'combo'
      || bucket.is_early_fail_rate_delta >= 0.05
    );
}

function isFallbackEarlyFailAttributionBucket(bucket: EarlyFailAttributionBucket): boolean {
  return bucket.sample_ok
    && bucket.is_trade_count >= 30
    && TRADE_ATTRIBUTION_ACTIONABLE_DIMENSIONS.has(bucket.dimension);
}

function compactStrategyName(value: string): string {
  const knownNames: Record<string, string> = {
    ema_crossover_v1: 'crossover v1',
    ema_pullback_atr_v2: 'pullback ATR v2',
  };
  return knownNames[value] ?? value.replace(/^ema_/, '').replace(/_/g, ' ');
}

function formatParameterPointValue(key: string, value: number | string | null | undefined): string | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (key === 'cash_allocation_pct') {
    return `${formatNumber(Number(value), 1)}%`;
  }
  if (key === 'risk_pct_per_trade') {
    return compactPct(Number(value));
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : formatNumber(value, 2);
  }
  return String(value);
}

function loadScreeningViewState(): ScreeningViewState {
  const fallback: ScreeningViewState = {
    labelFilter: [],
    strategyFilter: null,
    symbolFilter: null,
    minScoreFilter: null,
    minOosReturnFilter: null,
    minIsExcessReturnFilter: null,
    maxGapFilter: null,
    maxDrawdownFilter: null,
    minProfitFactorFilter: null,
    minTradeCountFilter: null,
    sorting: [{ id: 'score', desc: true }],
  };
  if (typeof window === 'undefined') {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(SCREENING_VIEW_STATE_STORAGE_KEY);
    if (!raw) {
      return fallback;
    }
    const parsed = JSON.parse(raw) as Partial<ScreeningViewState>;
    return {
      ...fallback,
      ...parsed,
      labelFilter: Array.isArray(parsed.labelFilter) ? parsed.labelFilter : fallback.labelFilter,
      sorting: Array.isArray(parsed.sorting) ? parsed.sorting : fallback.sorting,
    };
  } catch {
    return fallback;
  }
}

function parameterGroupPoints(group: ParameterGroupView): ParameterPoint[] {
  const rawPoints: Array<{ key: string; label: string; value: number | string | null | undefined }> = group.strategy_name === 'ema_pullback_atr_v2'
    ? [
      { key: 'trend_fast_period', label: 'tf', value: group.trend_fast_period },
      { key: 'trend_slow_period', label: 'ts', value: group.trend_slow_period },
      { key: 'entry_ema_period', label: 'ema', value: group.entry_ema_period },
      { key: 'atr_period', label: 'atr', value: group.atr_period },
      { key: 'atr_entry_tolerance', label: 'tol', value: group.atr_entry_tolerance },
      { key: 'atr_stop_mult', label: 'sl', value: group.atr_stop_mult },
      { key: 'risk_reward_ratio', label: 'rr', value: group.risk_reward_ratio },
    ]
    : [
      { key: 'fast_period', label: 'fast', value: group.fast_period },
      { key: 'slow_period', label: 'slow', value: group.slow_period },
    ];
  rawPoints.push(
    { key: 'qty_policy_ref', label: '仓位', value: group.qty_policy_ref },
    { key: 'cash_allocation_pct', label: 'cash', value: group.cash_allocation_pct },
    { key: 'risk_pct_per_trade', label: 'risk', value: group.risk_pct_per_trade },
    { key: 'leverage', label: '杠杆', value: group.leverage },
  );
  return rawPoints
    .map((point) => ({ ...point, value: formatParameterPointValue(point.key, point.value) }))
    .filter((point): point is ParameterPoint => point.value !== null);
}

function parameterGroupEntryPoints(group: ParameterGroupView): ParameterPoint[] {
  const excludedKeys = new Set(['cash_allocation_pct', 'risk_pct_per_trade', 'leverage']);
  return parameterGroupPoints(group).filter((point) => !excludedKeys.has(point.key));
}

function parameterGroupRiskPoints(group: ParameterGroupView): ParameterPoint[] {
  const includedKeys = new Set(['cash_allocation_pct', 'risk_pct_per_trade', 'leverage']);
  return parameterGroupPoints(group).filter((point) => includedKeys.has(point.key));
}

function parameterGroupEntryCompareKey(group: ParameterGroupView): string {
  return [
    group.strategy_name,
    group.symbol,
    group.timeframe,
    ...parameterGroupEntryPoints(group).map((point) => `${point.key}:${point.value}`),
  ].join('|');
}

function commonParameterPointKeys(groups: ParameterGroupView[]): Set<string> {
  if (!groups.length) {
    return new Set();
  }
  const valuesByKey = new Map<string, Set<string>>();
  for (const group of groups) {
    for (const point of parameterGroupPoints(group)) {
      const values = valuesByKey.get(point.key) ?? new Set<string>();
      values.add(point.value);
      valuesByKey.set(point.key, values);
    }
  }
  return new Set([...valuesByKey.entries()].filter(([, values]) => values.size === 1).map(([key]) => key));
}

function renderParameterPoints(points: ParameterPoint[], color: string = 'default') {
  if (!points.length) {
    return <Text type="secondary">--</Text>;
  }
  return (
    <Space size={[4, 4]} wrap>
      {points.map((point) => (
        <Tag key={point.key} color={color}>
          {point.label} {point.value}
        </Tag>
      ))}
    </Space>
  );
}

const RUN_COMPARE_SECTION_TITLES: Record<RunCompareSectionKey, string> = {
  identity: '对象',
  parameters: '参数',
  performance: '收益',
  risk: '风险与交易',
};

const RUN_COMPARE_FIELDS: RunCompareField[] = [
  { key: 'strategy_name', label: '策略', section: 'identity', value: (row) => row.strategy_name },
  { key: 'symbol', label: '标的', section: 'identity', value: (row) => row.symbol },
  { key: 'timeframe', label: '周期', section: 'identity', value: (row) => row.timeframe.toUpperCase() },
  { key: 'validation_split_id', label: '验证切分', section: 'identity', value: (row) => row.validation_split_id },
  { key: 'dataset_snapshot_id', label: '数据快照', section: 'identity', value: (row) => row.dataset_snapshot_id },
  { key: 'parameter_summary', label: '参数摘要', section: 'parameters', value: (row) => row.parameter_summary },
  { key: 'fast_period', label: '快线', section: 'parameters', value: (row) => row.fast_period },
  { key: 'slow_period', label: '慢线', section: 'parameters', value: (row) => row.slow_period },
  { key: 'trend_fast_period', label: '趋势快线', section: 'parameters', value: (row) => row.trend_fast_period },
  { key: 'trend_slow_period', label: '趋势慢线', section: 'parameters', value: (row) => row.trend_slow_period },
  { key: 'entry_ema_period', label: '入场 EMA', section: 'parameters', value: (row) => row.entry_ema_period },
  { key: 'atr_period', label: 'ATR 周期', section: 'parameters', value: (row) => row.atr_period },
  { key: 'atr_entry_tolerance', label: 'ATR 容差', section: 'parameters', value: (row) => row.atr_entry_tolerance },
  { key: 'atr_stop_mult', label: 'ATR 止损倍数', section: 'parameters', value: (row) => row.atr_stop_mult },
  { key: 'risk_reward_ratio', label: '盈亏比', section: 'parameters', value: (row) => row.risk_reward_ratio },
  { key: 'qty_policy_ref', label: '仓位模式', section: 'parameters', value: (row) => row.qty_policy_ref },
  { key: 'cash_allocation_pct', label: '资金使用', section: 'parameters', value: (row) => row.cash_allocation_pct, format: (value) => formatParameterPointValue('cash_allocation_pct', value) ?? '--' },
  { key: 'risk_pct_per_trade', label: '单笔风险', section: 'parameters', value: (row) => row.risk_pct_per_trade, format: (value) => formatParameterPointValue('risk_pct_per_trade', value) ?? '--', better: 'lower' },
  { key: 'leverage', label: '杠杆', section: 'parameters', value: (row) => row.leverage, better: 'lower' },
  { key: 'fee_rate', label: '手续费率', section: 'parameters', value: (row) => row.fee_rate, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'lower' },
  { key: 'slippage_bps', label: '滑点 bps', section: 'parameters', value: (row) => row.slippage_bps, better: 'lower' },
  { key: 'total_return', label: '总收益', section: 'performance', value: (row) => row.total_return, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'excess_return', label: '总超额', section: 'performance', value: (row) => row.excess_return, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'is_total_return', label: 'IS 收益', section: 'performance', value: (row) => row.is_total_return, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'is_excess_return', label: 'IS 超额', section: 'performance', value: (row) => row.is_excess_return, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'oos_total_return', label: 'OOS 收益', section: 'performance', value: (row) => row.oos_total_return, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'oos_excess_return', label: 'OOS 超额', section: 'performance', value: (row) => row.oos_excess_return, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'is_oos_gap', label: 'IS/OOS Gap', section: 'performance', value: (row) => (row.is_total_return !== null && row.oos_total_return !== null ? row.is_total_return - row.oos_total_return : null), format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'lower' },
  { key: 'final_equity', label: '最终权益', section: 'performance', value: (row) => row.final_equity, format: (value) => typeof value === 'number' ? formatNumber(value, 2) : '--', better: 'higher' },
  { key: 'max_drawdown', label: '最大回撤', section: 'risk', value: (row) => row.max_drawdown, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'lower' },
  { key: 'profit_factor', label: 'PF', section: 'risk', value: (row) => row.profit_factor, format: (value) => typeof value === 'number' ? formatNumber(value, 2) : '--', better: 'higher' },
  { key: 'trade_count', label: '交易数', section: 'risk', value: (row) => row.trade_count },
  { key: 'oos_trade_count', label: 'OOS 交易', section: 'risk', value: (row) => row.oos_trade_count },
  { key: 'win_rate', label: '胜率', section: 'risk', value: (row) => row.win_rate, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'oos_win_rate', label: 'OOS 胜率', section: 'risk', value: (row) => row.oos_win_rate, format: (value) => typeof value === 'number' ? formatPct(value) : '--', better: 'higher' },
  { key: 'warning_count', label: '告警数', section: 'risk', value: (row) => row.warning_count, better: 'lower' },
];

function normalizeRunCompareValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value.toFixed(10).replace(/0+$/, '').replace(/\.$/, '') : '';
  }
  return String(value);
}

function formatRunCompareValue(field: RunCompareField, value: number | string | null | undefined): string {
  if (field.format) {
    return field.format(value);
  }
  if (value === null || value === undefined || value === '') {
    return '--';
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : formatNumber(value, 2);
  }
  return String(value);
}

function buildRunCompareModel(left: ParameterLabRow, right: ParameterLabRow): RunCompareModel {
  const sectionRows = new Map<RunCompareSectionKey, RunCompareRow[]>();
  let sameCount = 0;
  let diffCount = 0;
  for (const field of RUN_COMPARE_FIELDS) {
    const leftValue = field.value(left);
    const rightValue = field.value(right);
    if (
      (leftValue === null || leftValue === undefined || leftValue === '')
      && (rightValue === null || rightValue === undefined || rightValue === '')
    ) {
      continue;
    }
    const same = normalizeRunCompareValue(leftValue) === normalizeRunCompareValue(rightValue);
    sameCount += same ? 1 : 0;
    diffCount += same ? 0 : 1;
    const leftNumber = typeof leftValue === 'number' && Number.isFinite(leftValue) ? leftValue : null;
    const rightNumber = typeof rightValue === 'number' && Number.isFinite(rightValue) ? rightValue : null;
    const canRank = !same && leftNumber !== null && rightNumber !== null && Boolean(field.better);
    const leftBetter = canRank ? (field.better === 'higher' ? leftNumber > rightNumber : leftNumber < rightNumber) : false;
    const rightBetter = canRank ? (field.better === 'higher' ? rightNumber > leftNumber : rightNumber < leftNumber) : false;
    const rows = sectionRows.get(field.section) ?? [];
    rows.push({
      key: field.key,
      label: field.label,
      leftValue,
      rightValue,
      leftText: formatRunCompareValue(field, leftValue),
      rightText: formatRunCompareValue(field, rightValue),
      same,
      leftBetter,
      rightBetter,
    });
    sectionRows.set(field.section, rows);
  }
  const sections = (Object.keys(RUN_COMPARE_SECTION_TITLES) as RunCompareSectionKey[])
    .map((key) => ({ key, title: RUN_COMPARE_SECTION_TITLES[key], rows: sectionRows.get(key) ?? [] }))
    .filter((section) => section.rows.length);
  const parameterDiffs = (sectionRows.get('parameters') ?? []).filter((row) => !row.same).map((row) => row.label);
  const identitySame = ['strategy_name', 'symbol', 'timeframe'].every((key) => (
    normalizeRunCompareValue(RUN_COMPARE_FIELDS.find((field) => field.key === key)?.value(left))
    === normalizeRunCompareValue(RUN_COMPARE_FIELDS.find((field) => field.key === key)?.value(right))
  ));
  const oosLeft = left.oos_total_return ?? left.total_return;
  const oosRight = right.oos_total_return ?? right.total_return;
  const oosWinner = oosLeft === oosRight ? 'OOS 接近' : `${oosLeft > oosRight ? 'A' : 'B'} 的 OOS 更高`;
  const drawdownWinner = left.max_drawdown === right.max_drawdown ? '回撤接近' : `${left.max_drawdown < right.max_drawdown ? 'A' : 'B'} 的回撤更低`;
  const diffText = parameterDiffs.length ? `主要参数差异：${parameterDiffs.slice(0, 6).join('、')}` : '核心参数基本一致';
  const summary = `${identitySame ? '策略/标的/周期一致' : '研究对象不同'}，${diffText}；${oosWinner}，${drawdownWinner}。`;
  return { left, right, sections, sameCount, diffCount, summary };
}

function parameterGroupOosDrawdownRatio(group: ParameterGroupView): number {
  return (group.avg_oos_total_return ?? group.avg_total_return) / Math.max(group.worst_max_drawdown, 0.01);
}

function isHighRiskParameterGroup(group: ParameterGroupView): boolean {
  return (
    (group.risk_pct_per_trade ?? 0) >= 0.08
    || (group.leverage ?? 0) >= 10
    || group.worst_max_drawdown >= 0.6
  );
}

function scoreResearchConclusionGroup(group: ParameterGroupView): number {
  const oos = group.avg_oos_total_return ?? group.avg_total_return;
  const pf = group.avg_profit_factor ?? 0;
  const neighbor = group.neighbor_stability_score ?? 0;
  const positiveOos = group.oos_positive_ratio ?? 0;
  const efficiency = parameterGroupOosDrawdownRatio(group);
  const gapPenalty = Math.min(Math.abs(group.avg_gap ?? 0), 5) * 2;
  const drawdownPenalty = group.worst_max_drawdown * 35;
  const riskPenalty = isHighRiskParameterGroup(group) ? 12 : 0;
  return (
    group.research_score
    + Math.min(oos * 8, 24)
    + Math.min(efficiency * 3, 18)
    + Math.min(Math.max(pf - 1, 0) * 18, 10)
    + positiveOos * 8
    + neighbor * 8
    - drawdownPenalty
    - gapPenalty
    - riskPenalty
  );
}

function buildResearchConclusionReasons(group: ParameterGroupView): string[] {
  const reasons = [
    `${group.symbol} ${group.timeframe.toUpperCase()}`,
    `OOS ${formatPct(group.avg_oos_total_return)}`,
    `回撤 ${formatPct(group.worst_max_drawdown)}`,
    `PF ${formatNumber(group.avg_profit_factor, 2)}`,
    `交易 ${group.min_trade_count}`,
  ];
  const efficiency = parameterGroupOosDrawdownRatio(group);
  reasons.push(`OOS/DD ${formatNumber(efficiency, 2)}`);
  if (group.oos_positive_ratio !== null) {
    reasons.push(`OOS正比 ${formatPct(group.oos_positive_ratio)}`);
  }
  if (group.avg_gap !== null && Math.abs(group.avg_gap) >= 1) {
    reasons.push(`Gap ${formatPct(group.avg_gap)}`);
  }
  if (group.neighbor_stability_score !== null) {
    reasons.push(`邻域 ${formatPct(group.neighbor_stability_score)}`);
  }
  if (group.risk_pct_per_trade !== null) {
    reasons.push(`risk ${compactPct(group.risk_pct_per_trade)}`);
  }
  if (group.leverage !== null) {
    reasons.push(`杠杆 ${group.leverage}`);
  }
  return reasons.filter((reason): reason is string => Boolean(reason));
}

function toResearchConclusionItem(group: ParameterGroupView): ResearchConclusionItem {
  return {
    group,
    score: scoreResearchConclusionGroup(group),
    reasons: buildResearchConclusionReasons(group),
  };
}

function takeResearchConclusionItems(
  groups: ParameterGroupView[],
  predicate: (group: ParameterGroupView) => boolean,
  seenGroupKeys: Set<string>,
  limit = 3,
): ResearchConclusionItem[] {
  const items = groups
    .filter((group) => !seenGroupKeys.has(group.group_key) && predicate(group))
    .map(toResearchConclusionItem)
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      const rightOos = right.group.avg_oos_total_return ?? right.group.avg_total_return;
      const leftOos = left.group.avg_oos_total_return ?? left.group.avg_total_return;
      return rightOos - leftOos;
    })
    .slice(0, limit);
  for (const item of items) {
    seenGroupKeys.add(item.group.group_key);
  }
  return items;
}

function buildResearchConclusionBuckets(groups: ParameterGroupView[]): ResearchConclusionBucket[] {
  const seenGroupKeys = new Set<string>();
  const hasEnoughSamples = (group: ParameterGroupView) => group.run_count >= 1 && group.snapshot_count >= 1;
  const isTradable = (group: ParameterGroupView) => (
    hasEnoughSamples(group)
    && group.classification !== 'excluded'
    && (group.avg_oos_total_return ?? -1) > 0
    && (group.avg_profit_factor ?? 0) >= 1
    && group.min_trade_count >= 50
  );
  const primary = takeResearchConclusionItems(groups, (group) => (
    isTradable(group)
    && !isHighRiskParameterGroup(group)
    && (group.oos_positive_ratio ?? 0) >= 0.75
    && (group.avg_profit_factor ?? 0) >= 1.1
    && group.worst_max_drawdown <= 0.5
    && group.min_trade_count >= 150
    && (group.neighbor_stability_score ?? 0.5) >= 0.5
  ), seenGroupKeys);
  const robust = takeResearchConclusionItems(groups, (group) => (
    isTradable(group)
    && !isHighRiskParameterGroup(group)
    && group.worst_max_drawdown <= 0.45
    && (group.oos_positive_ratio ?? 0) >= 0.65
    && group.min_trade_count >= 100
  ), seenGroupKeys);
  const aggressive = takeResearchConclusionItems(groups, (group) => (
    isTradable(group)
    && (group.avg_oos_total_return ?? group.avg_total_return) >= 1
    && (group.avg_profit_factor ?? 0) >= 1.05
    && group.min_trade_count >= 100
    && (isHighRiskParameterGroup(group) || Math.abs(group.avg_gap ?? 0) >= 1)
  ), seenGroupKeys);
  const riskReduction = takeResearchConclusionItems(groups, (group) => (
    isTradable(group)
    && isHighRiskParameterGroup(group)
    && (group.avg_oos_total_return ?? group.avg_total_return) > 0
  ), seenGroupKeys);
  const excluded = takeResearchConclusionItems(groups, (group) => (
    !seenGroupKeys.has(group.group_key)
    && (
      group.classification === 'excluded'
      || (group.avg_oos_total_return ?? -1) <= 0
      || (group.avg_profit_factor ?? 0) < 1
      || group.worst_max_drawdown >= 0.85
      || group.min_trade_count < 30
    )
  ), seenGroupKeys);
  return [
    {
      key: 'primary',
      title: '首选候选',
      tone: 'success',
      description: '优先研究：OOS、PF、回撤和样本数同时过线。',
      items: primary,
    },
    {
      key: 'robust',
      title: '稳健候选',
      tone: 'info',
      description: '收益不一定最高，但风险轮廓更容易继续验证。',
      items: robust,
    },
    {
      key: 'aggressive',
      title: '高收益但激进',
      tone: 'warning',
      description: '收益显眼，但 Gap、回撤或风险参数偏激，需要降风险复测。',
      items: aggressive,
    },
    {
      key: 'risk_reduction',
      title: '需要降风险验证',
      tone: 'warning',
      description: '方向可能有效，但 risk 或杠杆过高，不应直接采用。',
      items: riskReduction,
    },
    {
      key: 'excluded',
      title: '暂不研究',
      tone: 'error',
      description: '样本、OOS、PF 或回撤不过线，先不要投入分析时间。',
      items: excluded,
    },
  ];
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

function parameterGroupSummary(group: { parameter_summary?: string; signal_filter_summary?: string | null; fast_period?: number | null; slow_period?: number | null; leverage?: number | null }): string {
  return group.parameter_summary || `快 ${group.fast_period ?? '--'} / 慢 ${group.slow_period ?? '--'} / 杠杆 ${group.leverage ?? '--'}`;
}

function buildParameterGroupTargetId(batchId: string, group: { strategy_name?: string; parameter_summary?: string; signal_filter_summary?: string | null; fast_period?: number | null; slow_period?: number | null; leverage?: number | null }): string {
  const summary = `${parameterGroupSummary(group)} ${group.signal_filter_summary ?? ''}`.trim().replace(/[^a-zA-Z0-9._-]+/g, '-');
  return `${batchId}:${group.strategy_name ?? 'ema_crossover'}:${summary}`;
}

function buildParameterGroupKey(group: { strategy_name?: string; parameter_summary?: string; signal_filter_summary?: string | null; fast_period?: number | null | undefined; slow_period?: number | null | undefined; leverage?: number | null | undefined }): string {
  const base = group.parameter_summary || `${group.fast_period ?? 'na'}:${group.slow_period ?? 'na'}:${group.leverage ?? 'na'}`;
  return `${group.strategy_name ?? 'ema_crossover'}:${base}:${group.signal_filter_summary ?? 'nofilter'}`;
}

function runIsoosGap(row: ParameterLabRow): number | null {
  if (row.is_total_return === null || row.oos_total_return === null) {
    return null;
  }
  return row.is_total_return - row.oos_total_return;
}

function rowMatchesParameterGroupSignature(group: ParameterGroupView, row: ParameterLabRow): boolean {
  return group.strategy_name === row.strategy_name
    && group.symbol === row.symbol
    && group.timeframe === row.timeframe
    && group.fast_period === row.fast_period
    && group.slow_period === row.slow_period
    && group.trend_fast_period === row.trend_fast_period
    && group.trend_slow_period === row.trend_slow_period
    && group.entry_ema_period === row.entry_ema_period
    && group.atr_period === row.atr_period
    && group.atr_entry_tolerance === row.atr_entry_tolerance
    && group.atr_stop_mult === row.atr_stop_mult
    && group.risk_reward_ratio === row.risk_reward_ratio
    && group.qty_policy_ref === row.qty_policy_ref
    && group.cash_allocation_pct === row.cash_allocation_pct
    && group.risk_pct_per_trade === row.risk_pct_per_trade
    && group.leverage === row.leverage;
}

function parameterRowToGroupRunView(row: ParameterLabRow, groupKey: string): ParameterGroupRunView {
  return {
    group_key: groupKey,
    run_id: row.run_id,
    batch_id: null,
    experiment_id: null,
    dataset_snapshot_id: row.dataset_snapshot_id,
    created_at: row.created_at,
    total_return: row.total_return,
    oos_total_return: row.oos_total_return,
    gap: runIsoosGap(row),
    max_drawdown: row.max_drawdown,
    profit_factor: row.profit_factor,
    trade_count: row.trade_count,
    oos_trade_count: row.oos_trade_count,
    win_rate: row.win_rate,
    oos_win_rate: row.oos_win_rate,
    final_equity: row.final_equity,
  };
}

function buildLocalFilterResultGroup(filterSummary: string, rows: ParameterLabRow[], baseGroup: ParameterGroupView): FilterResultGroup {
  const oosValues = rows.map((row) => row.oos_total_return).filter((value): value is number => value !== null);
  const totalValues = rows.map((row) => row.total_return);
  const drawdowns = rows.map((row) => row.max_drawdown);
  const profitFactors = rows.map((row) => row.profit_factor).filter((value): value is number => value !== null);
  const tradeCounts = rows.map((row) => row.trade_count);
  const oosTradeCounts = rows.map((row) => row.oos_trade_count).filter((value): value is number => value !== null);
  const average = (values: number[]) => (values.length ? values.reduce((total, value) => total + value, 0) / values.length : null);
  const avgOos = average(oosValues);
  const avgDrawdown = average(drawdowns);
  const avgProfitFactor = average(profitFactors);
  const minTradeCount = tradeCounts.length ? Math.min(...tradeCounts) : null;
  return {
    filter_summary: filterSummary,
    run_count: rows.length,
    snapshot_count: new Set(rows.map((row) => row.dataset_snapshot_id)).size,
    avg_total_return: average(totalValues),
    avg_oos_total_return: avgOos,
    avg_oos_delta: avgOos !== null && baseGroup.avg_oos_total_return !== null ? avgOos - baseGroup.avg_oos_total_return : null,
    avg_max_drawdown: avgDrawdown,
    avg_drawdown_delta: avgDrawdown !== null ? avgDrawdown - baseGroup.avg_max_drawdown : null,
    worst_max_drawdown: drawdowns.length ? Math.max(...drawdowns) : null,
    avg_profit_factor: avgProfitFactor,
    avg_profit_factor_delta: avgProfitFactor !== null && baseGroup.avg_profit_factor !== null ? avgProfitFactor - baseGroup.avg_profit_factor : null,
    min_trade_count: minTradeCount,
    min_oos_trade_count: oosTradeCounts.length ? Math.min(...oosTradeCounts) : null,
    trade_retention: minTradeCount !== null && baseGroup.min_trade_count ? minTradeCount / baseGroup.min_trade_count : null,
    run_ids: [...rows].sort((left, right) => dayjs(right.created_at).valueOf() - dayjs(left.created_at).valueOf()).map((row) => row.run_id),
  };
}

function buildLocalResearchCandidateFilterResults(
  candidateId: string,
  groups: ParameterGroupView[],
  rows: ParameterLabRow[],
): ResearchCandidateFilterResults | null {
  const baseGroup = groups.find((group) => group.group_key === candidateId);
  if (!baseGroup) {
    return null;
  }
  const filterRuns = rows.filter((row) => row.signal_filter_summary && rowMatchesParameterGroupSignature(baseGroup, row));
  const filterRowsBySummary = new Map<string, ParameterLabRow[]>();
  for (const row of filterRuns) {
    const key = row.signal_filter_summary ?? '';
    filterRowsBySummary.set(key, [...(filterRowsBySummary.get(key) ?? []), row]);
  }
  const filterGroups = [...filterRowsBySummary.entries()]
    .map(([filterSummary, filterRows]) => buildLocalFilterResultGroup(filterSummary, filterRows, baseGroup))
    .sort((left, right) => (right.avg_oos_delta ?? -10_000) - (left.avg_oos_delta ?? -10_000));
  return {
    candidate_id: candidateId,
    base_group: baseGroup,
    base_runs: rows
      .filter((row) => baseGroup.run_ids.includes(row.run_id))
      .map((row) => parameterRowToGroupRunView(row, baseGroup.group_key)),
    filter_groups: filterGroups,
    filter_runs: filterRuns.sort((left, right) => dayjs(right.created_at).valueOf() - dayjs(left.created_at).valueOf()),
  };
}

function protectionSummaryLabel(row: ParameterLabRow): string {
  return row.execution_protection_summary || '无保护';
}

function buildDrawdownProtectionComparisonRows(rows: ParameterLabRow[]): DrawdownProtectionComparisonRow[] {
  if (!rows.length) {
    return [];
  }
  const baseline = rows.find((row) => !row.execution_protection_summary || row.execution_protection_summary === '无保护') ?? rows[0];
  return rows.map((row) => {
    const oosDelta = row.oos_total_return !== null && baseline.oos_total_return !== null
      ? row.oos_total_return - baseline.oos_total_return
      : null;
    const drawdownDelta = row.max_drawdown - baseline.max_drawdown;
    const profitFactorDelta = row.profit_factor !== null && baseline.profit_factor !== null
      ? row.profit_factor - baseline.profit_factor
      : null;
    const tradeRetention = baseline.trade_count > 0 ? row.trade_count / baseline.trade_count : null;
    const isBaseline = row.run_id === baseline.run_id;
    const drawdownImproved = drawdownDelta < -0.005;
    const oosNotDamaged = oosDelta === null || oosDelta >= -0.02;
    const pfNotDamaged = profitFactorDelta === null || profitFactorDelta >= -0.03;
    const verdict: DrawdownProtectionComparisonRow['verdict'] = isBaseline
      ? 'baseline'
      : drawdownImproved && oosNotDamaged && pfNotDamaged
        ? 'improved'
        : drawdownDelta > 0.005 || (oosDelta !== null && oosDelta < -0.1)
          ? 'worse'
          : 'mixed';
    return {
      protection: protectionSummaryLabel(row),
      run_id: row.run_id,
      total_return: row.total_return,
      oos_total_return: row.oos_total_return,
      max_drawdown: row.max_drawdown,
      profit_factor: row.profit_factor,
      trade_count: row.trade_count,
      oos_trade_count: row.oos_trade_count,
      oos_delta: isBaseline ? null : oosDelta,
      drawdown_delta: isBaseline ? null : drawdownDelta,
      profit_factor_delta: isBaseline ? null : profitFactorDelta,
      trade_retention: isBaseline ? 1 : tradeRetention,
      verdict,
    };
  });
}

function scoreResearchRun(row: ParameterLabRow): ResearchRunCandidate {
  const gap = runIsoosGap(row);
  const oosReturn = row.oos_total_return ?? row.total_return;
  const oosExcess = row.oos_excess_return ?? row.excess_return ?? 0;
  const oosTrades = row.oos_trade_count ?? row.trade_count;
  const profitFactor = row.profit_factor ?? 0;
  const score = (
    oosReturn
    + oosExcess * 0.35
    + Math.min(oosTrades / 80, 1) * 0.18
    + Math.min(Math.max(profitFactor - 1, 0), 1) * 0.18
    - row.max_drawdown * 0.75
    - Math.max(0, gap ?? 0) * 0.25
  );
  const tags: string[] = [];
  if (row.oos_total_return !== null && row.oos_total_return >= 1) {
    tags.push('OOS 强');
  }
  if (gap !== null && gap <= 0.35) {
    tags.push('Gap 小');
  } else if (gap !== null && gap >= 2) {
    tags.push('Gap 大');
  }
  if (row.max_drawdown <= 0.3) {
    tags.push('回撤低');
  }
  if (oosTrades >= 80) {
    tags.push('样本充足');
  }
  if (profitFactor >= 1.5) {
    tags.push('PF 高');
  }
  if (!tags.length) {
    tags.push('待复核');
  }
  return {
    row,
    score,
    tags,
    gap,
    reason: [
      `OOS ${formatPct(row.oos_total_return)}`,
      `Gap ${formatPct(gap)}`,
      `回撤 ${formatPct(row.max_drawdown)}`,
      `OOS 交易 ${row.oos_trade_count ?? '--'}`,
      `PF ${formatNumber(row.profit_factor, 2)}`,
    ].join('，'),
  };
}

function buildFrozenRunNoteValues(row: ParameterLabRow): Record<string, unknown> {
  const candidate = scoreResearchRun(row);
  const confidence = Math.max(0, Math.min(100, candidate.score));
  return {
    author: 'local',
    decision_status: 'observing',
    decision_reason: '冻结参数进入追踪，后续重点复测和观察。',
    confidence_score: Number(confidence.toFixed(1)),
    labels: ['frozen_run', 'tracking'],
    content: [
      '冻结参数进入追踪。',
      `标的/周期：${row.symbol} · ${row.timeframe.toUpperCase()}`,
      `参数：${row.parameter_summary}`,
      `研究分：${formatNumber(candidate.score, 1)}；OOS：${formatPct(row.oos_total_return)}；Gap：${formatPct(candidate.gap)}；回撤：${formatPct(row.max_drawdown)}；PF：${formatNumber(row.profit_factor, 2)}；交易数：${row.trade_count}`,
      `Run：${row.run_id}`,
    ].join('\n'),
  };
}

function buildFrozenAnalysisNoteValues(run: RunAnalysisView, summary: RunSummaryView | undefined): Record<string, unknown> {
  const strategyParams = run.manifest.resolved_config_json.strategy_params as Record<string, unknown> | undefined;
  const executionConstraints = run.manifest.resolved_config_json.execution_constraints as Record<string, unknown> | undefined;
  const parameterSummary = summary?.parameter_summary
    ?? Object.entries(strategyParams ?? {}).map(([key, value]) => `${key}=${String(value)}`).join(' ');
  return {
    author: 'local',
    decision_status: 'observing',
    decision_reason: '从单次分析冻结参数进入追踪。',
    labels: ['frozen_run', 'tracking'],
    content: [
      '冻结参数进入追踪。',
      `标的/周期：${run.symbol} · ${run.timeframe.toUpperCase()}`,
      `参数：${parameterSummary || '--'}`,
      `收益：${formatPct(run.metrics.total_return)}；最终权益：${formatNumber(run.metrics.final_equity)}；交易数：${run.metrics.trade_count}；PF：${formatNumber(run.metrics.profit_factor, 2)}`,
      executionConstraints ? `执行约束：${JSON.stringify(executionConstraints)}` : null,
      `Run：${run.run_id}`,
    ].filter(Boolean).join('\n'),
  };
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

function firstPolicyNumber(value: unknown): number | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const firstValue = Object.values(value as Record<string, unknown>)[0];
  const numeric = Number(firstValue);
  return Number.isFinite(numeric) ? numeric : null;
}

function numericConfigValue(value: unknown, fallback: number): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function drawdownProtectionSets(): Array<Record<string, unknown>> {
  return [
    { protection_set_id: 'none', label: '无保护', params: {} },
    { protection_set_id: 'dd-stop-20', label: 'DD停开20%', params: { max_equity_drawdown_pct: 0.2 } },
    { protection_set_id: 'dd-stop-30', label: 'DD停开30%', params: { max_equity_drawdown_pct: 0.3 } },
    {
      protection_set_id: 'cooldown-2-24',
      label: '2短止冷却24K',
      params: {
        cooldown_after_consecutive_stop_losses: 2,
        cooldown_bars: 24,
        cooldown_only_short_holding_bars: 3,
      },
    },
    {
      protection_set_id: 'cooldown-3-72',
      label: '3短止冷却72K',
      params: {
        cooldown_after_consecutive_stop_losses: 3,
        cooldown_bars: 72,
        cooldown_only_short_holding_bars: 3,
      },
    },
    {
      protection_set_id: 'dd20-cooldown-2-24',
      label: 'DD20%+2止24K',
      params: {
        max_equity_drawdown_pct: 0.2,
        cooldown_after_consecutive_stop_losses: 2,
        cooldown_bars: 24,
        cooldown_only_short_holding_bars: 3,
      },
    },
  ];
}

function uniqueSortedNumbers(values: number[]): number[] {
  return [...new Set(values.filter((value) => Number.isFinite(value) && value > 0))]
    .sort((left, right) => left - right);
}

function trendPeriodNeighborhood(period: number | null | undefined): number[] {
  if (!Number.isFinite(period ?? Number.NaN) || !period) {
    return [];
  }
  const ladderIndex = TREND_PERIOD_LADDER.indexOf(period);
  if (ladderIndex >= 0) {
    return uniqueSortedNumbers([
      TREND_PERIOD_LADDER[ladderIndex - 1],
      period,
      TREND_PERIOD_LADDER[ladderIndex + 1],
    ].filter((value): value is number => typeof value === 'number'));
  }
  return uniqueSortedNumbers([period - 1, period, period + 1]);
}

function nullableNumberEquals(left: number | null | undefined, right: number | null | undefined): boolean {
  if (left === null || left === undefined || right === null || right === undefined) {
    return left === right;
  }
  return Math.abs(left - right) < 1e-9;
}

function buildTrendNeighborhoodMatches(source: ParameterLabRow | null, rows: ParameterLabRow[]): NeighborhoodRunMatch[] {
  if (!source || source.strategy_name !== 'ema_pullback_atr_v2' || !source.trend_fast_period || !source.trend_slow_period) {
    return [];
  }
  const fastCandidates = new Set(trendPeriodNeighborhood(source.trend_fast_period));
  const slowCandidates = new Set(trendPeriodNeighborhood(source.trend_slow_period));
  return rows
    .filter((row) => (
      row.strategy_name === 'ema_pullback_atr_v2'
      && row.dataset_snapshot_id === source.dataset_snapshot_id
      && row.symbol === source.symbol
      && row.timeframe === source.timeframe
      && row.trend_fast_period !== null
      && row.trend_slow_period !== null
      && fastCandidates.has(row.trend_fast_period)
      && slowCandidates.has(row.trend_slow_period)
      && nullableNumberEquals(row.atr_entry_tolerance, source.atr_entry_tolerance)
      && nullableNumberEquals(row.atr_stop_mult, source.atr_stop_mult)
      && nullableNumberEquals(row.risk_reward_ratio, source.risk_reward_ratio)
      && nullableNumberEquals(row.leverage, source.leverage)
      && row.qty_policy_ref === source.qty_policy_ref
      && nullableNumberEquals(row.cash_allocation_pct, source.cash_allocation_pct)
      && nullableNumberEquals(row.risk_pct_per_trade, source.risk_pct_per_trade)
    ))
    .map((row) => {
      const fastDelta = row.trend_fast_period === null ? null : row.trend_fast_period - source.trend_fast_period!;
      const slowDelta = row.trend_slow_period === null ? null : row.trend_slow_period - source.trend_slow_period!;
      return {
        row,
        isSource: row.run_id === source.run_id,
        fastDelta,
        slowDelta,
        distance: Math.abs(fastDelta ?? 0) + Math.abs(slowDelta ?? 0),
      };
    })
    .sort((left, right) => {
      if (left.isSource !== right.isSource) {
        return left.isSource ? -1 : 1;
      }
      if (left.distance !== right.distance) {
        return left.distance - right.distance;
      }
      return right.row.total_return - left.row.total_return;
    });
}

function averageNullable(values: Array<number | null | undefined>): number | null {
  const numericValues = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!numericValues.length) {
    return null;
  }
  return numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length;
}

function negativeRatio(values: Array<number | null | undefined>): number | null {
  const numericValues = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!numericValues.length) {
    return null;
  }
  return numericValues.filter((value) => value < 0).length / numericValues.length;
}

function buildScreeningRiskProfile(rows: ScreeningRunView[]): ScreeningRiskItem[] {
  const groups = new Map<string, { dimension: string; label: string; rows: ScreeningRunView[] }>();
  const addGroup = (dimension: string, label: string, row: ScreeningRunView) => {
    const key = `${dimension}:${label}`;
    const current = groups.get(key);
    if (current) {
      current.rows.push(row);
      return;
    }
    groups.set(key, { dimension, label, rows: [row] });
  };

  for (const row of rows) {
    if (row.fast_period !== null && row.slow_period !== null) {
      addGroup('快慢线', `${row.fast_period}/${row.slow_period}`, row);
    }
    if (row.trend_fast_period !== null && row.trend_slow_period !== null) {
      addGroup('趋势快慢线', `${row.trend_fast_period}/${row.trend_slow_period}`, row);
    }
    if (row.atr_entry_tolerance !== null) {
      addGroup('ATR容忍', formatNumber(row.atr_entry_tolerance, 2), row);
    }
    if (row.atr_stop_mult !== null) {
      addGroup('ATR止损', formatNumber(row.atr_stop_mult, 2), row);
    }
    if (row.risk_reward_ratio !== null) {
      addGroup('盈亏比', formatNumber(row.risk_reward_ratio, 2), row);
    }
  }

  return Array.from(groups.values())
    .filter((group) => group.rows.length >= 3)
    .map((group) => {
      const avgOosReturn = averageNullable(group.rows.map((row) => row.oos_total_return));
      const avgOosExcess = averageNullable(group.rows.map((row) => row.oos_excess_return));
      const avgDrawdown = averageNullable(group.rows.map((row) => row.max_drawdown));
      const avgProfitFactor = averageNullable(group.rows.map((row) => row.profit_factor));
      const negativeOos = negativeRatio(group.rows.map((row) => row.oos_total_return));
      const severe = (
        (avgOosExcess !== null && avgOosExcess < -0.2)
        || (avgOosReturn !== null && avgOosReturn < -0.15)
        || (negativeOos !== null && negativeOos >= 0.7)
        || (avgDrawdown !== null && avgDrawdown >= 0.7)
      );
      const warning = severe || (
        (avgOosExcess !== null && avgOosExcess < 0)
        || (avgOosReturn !== null && avgOosReturn < 0)
        || (avgProfitFactor !== null && avgProfitFactor < 1)
        || (avgDrawdown !== null && avgDrawdown >= 0.5)
      );
      if (!warning) {
        return null;
      }
      const reasons = [
        `样本 ${group.rows.length}`,
        `OOS ${formatPct(avgOosReturn)}`,
        `OOS超额 ${formatPct(avgOosExcess)}`,
        `负OOS ${formatPct(negativeOos)}`,
        `回撤 ${formatPct(avgDrawdown)}`,
        `PF ${formatNumber(avgProfitFactor, 2)}`,
      ];
      return {
        key: `${group.dimension}:${group.label}`,
        dimension: group.dimension,
        label: group.label,
        sampleCount: group.rows.length,
        avgOosReturn,
        avgOosExcess,
        avgDrawdown,
        avgProfitFactor,
        negativeOosRatio: negativeOos,
        severity: severe ? 'danger' : 'warning',
        reason: reasons.join(' · '),
      } satisfies ScreeningRiskItem;
    })
    .filter((item): item is ScreeningRiskItem => item !== null)
    .sort((left, right) => {
      if (left.severity !== right.severity) {
        return left.severity === 'danger' ? -1 : 1;
      }
      return (left.avgOosExcess ?? 0) - (right.avgOosExcess ?? 0);
    })
    .slice(0, 8);
}

function buildNeighborhoodStabilityStats(matches: NeighborhoodRunMatch[]): NeighborhoodStabilityStats {
  const neighborRows = matches.filter((match) => !match.isSource).map((match) => match.row);
  const sampleCount = neighborRows.length;
  if (!sampleCount) {
    return {
      sampleCount,
      positiveOosRatio: null,
      positiveReturnRatio: null,
      avgOosReturn: null,
      avgGap: null,
      worstDrawdown: null,
      minTradeCount: null,
      avgProfitFactor: null,
      score: null,
      verdict: 'insufficient',
      verdictText: '样本不足',
      reason: '没有匹配到当前点以外的邻域 run，不能判断稳定性。',
    };
  }
  const positiveReturnRatio = neighborRows.filter((row) => row.total_return > 0).length / sampleCount;
  const oosRows = neighborRows.filter((row) => row.oos_total_return !== null);
  const positiveOosRatio = oosRows.length ? oosRows.filter((row) => (row.oos_total_return ?? 0) > 0).length / oosRows.length : null;
  const avgOosReturn = averageNullable(oosRows.map((row) => row.oos_total_return));
  const gapValues = neighborRows.map((row) => runIsoosGap(row)).filter((value): value is number => value !== null && Number.isFinite(value));
  const avgGap = gapValues.length ? gapValues.reduce((sum, value) => sum + Math.max(value, 0), 0) / gapValues.length : null;
  const worstDrawdown = Math.max(...neighborRows.map((row) => row.max_drawdown));
  const minTradeCount = Math.min(...neighborRows.map((row) => row.trade_count));
  const avgProfitFactor = averageNullable(neighborRows.map((row) => row.profit_factor));
  const oosComponent = positiveOosRatio ?? positiveReturnRatio;
  const score = Math.max(0, Math.min(100, (
    oosComponent * 45
    + positiveReturnRatio * 20
    + Math.min(Math.max((avgOosReturn ?? 0) / 1, 0), 1) * 15
    + Math.min(minTradeCount / 80, 1) * 10
    + Math.min(Math.max((avgProfitFactor ?? 1) - 1, 0), 1) * 10
    - Math.min(Math.max(worstDrawdown - 0.25, 0) / 0.35, 1) * 15
    - Math.min(Math.max((avgGap ?? 0) - 0.5, 0) / 1.5, 1) * 15
  )));
  const verdict = sampleCount < 3
    ? 'insufficient'
    : score >= 70 && oosComponent >= 0.65 && worstDrawdown <= 0.35
      ? 'stable'
      : score >= 45 && oosComponent >= 0.5
        ? 'watch'
        : 'unstable';
  const verdictText = verdict === 'stable'
    ? '邻域稳定'
    : verdict === 'watch'
      ? '需要观察'
      : verdict === 'unstable'
        ? '邻域不稳'
        : '样本不足';
  const reason = [
    `邻居 ${sampleCount} 个`,
    `OOS 正比例 ${formatPct(positiveOosRatio)}`,
    `平均 OOS ${formatPct(avgOosReturn)}`,
    `平均 Gap ${formatPct(avgGap)}`,
    `最差回撤 ${formatPct(worstDrawdown)}`,
    `最少交易 ${minTradeCount}`,
  ].join('，');
  return {
    sampleCount,
    positiveOosRatio,
    positiveReturnRatio,
    avgOosReturn,
    avgGap,
    worstDrawdown,
    minTradeCount,
    avgProfitFactor,
    score,
    verdict,
    verdictText,
    reason,
  };
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

function validateNonNegativeNumberListInput(value: unknown, fieldLabel: string): string | null {
  const raw = String(value ?? '').trim();
  if (!raw) {
    return `请输入${fieldLabel}`;
  }
  const parts = raw.split(',').map((entry) => entry.trim()).filter(Boolean);
  if (!parts.length) {
    return `请输入${fieldLabel}`;
  }
  const parsed = parts.map((entry) => Number.parseFloat(entry));
  if (parsed.some((entry) => !Number.isFinite(entry) || entry < 0)) {
    return `${fieldLabel}必须是逗号分隔的非负数`;
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
  const [parameterResearch, setParameterResearch] = useState<ParameterResearchWorkspace | null>(null);
  const [researchWorkflow, setResearchWorkflow] = useState<ResearchWorkflow | null>(null);
  const [parameterExperiments, setParameterExperiments] = useState<ParameterExperimentSummary[]>([]);
  const [parameterExperimentBatches, setParameterExperimentBatches] = useState<ParameterExperimentBatchSummary[]>([]);
  const [paperSessions, setPaperSessions] = useState<PaperSessionView[]>([]);
  const [researchNotes, setResearchNotes] = useState<ResearchNote[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState(ALL_BATCHES);
  const [selectedBatchDetail, setSelectedBatchDetail] = useState<ParameterExperimentBatchDetail | null>(null);
  const [selectedExperimentId, setSelectedExperimentId] = useState(ALL_EXPERIMENTS);
  const [selectedExperimentDetail, setSelectedExperimentDetail] = useState<ParameterExperimentDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunAnalysisView | null>(null);
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
  const [neighborhoodRunId, setNeighborhoodRunId] = useState<string | null>(null);
  const [drawdownProtectionRunId, setDrawdownProtectionRunId] = useState<string | null>(null);
  const [drawdownProtectionCandidateId, setDrawdownProtectionCandidateId] = useState<string | null>(null);
  const [drawdownProtectionProgressByCandidateId, setDrawdownProtectionProgressByCandidateId] = useState<Record<string, FilterExperimentProgress>>({});
  const [riskMatrixCandidateId, setRiskMatrixCandidateId] = useState<string | null>(null);
  const [riskMatrixProgressByCandidateId, setRiskMatrixProgressByCandidateId] = useState<Record<string, RiskMatrixProgress>>({});
  const [filterExperimentCandidateId, setFilterExperimentCandidateId] = useState<string | null>(null);
  const [filterExperimentProgressByCandidateId, setFilterExperimentProgressByCandidateId] = useState<Record<string, FilterExperimentProgress>>({});
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [bulkDeletingRuns, setBulkDeletingRuns] = useState(false);
  const [deletingExperimentId, setDeletingExperimentId] = useState<string | null>(null);
  const [deletingBatchId, setDeletingBatchId] = useState<string | null>(null);
  const [deletingResearchNoteId, setDeletingResearchNoteId] = useState<string | null>(null);
  const [savingResearchNote, setSavingResearchNote] = useState(false);
  const [paperSubmitting, setPaperSubmitting] = useState<'create' | 'tick' | null>(null);
  const attemptedParameterResultRefreshKeysRef = useRef<Set<string>>(new Set());
  const [ingestForm] = Form.useForm();
  const [runForm] = Form.useForm();
  const [experimentForm] = Form.useForm();
  const [paperForm] = Form.useForm();
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
    setParameterResearch(null);
    setResearchWorkflow(null);
    setParameterExperimentBatches([]);
    setPaperSessions([]);
    setSelectedBatchId(ALL_BATCHES);
    setSelectedBatchDetail(null);
    setParameterExperiments([]);
    setSelectedExperimentId(ALL_EXPERIMENTS);
    setSelectedExperimentDetail(null);
    setSelectedRun(null);
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

  async function refreshResearchWorkflow() {
    const [researchPayload, workflowPayload, notesPayload] = await Promise.all([
      loadParameterResearch(),
      loadResearchWorkflow(),
      loadResearchNotes(),
    ]);
    setParameterResearch(researchPayload.parameter_research);
    setResearchWorkflow(workflowPayload.research_workflow);
    setResearchNotes(notesPayload.research_notes);
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

    const [experimentPayload, batchPayload, workflowPayload] = await Promise.all([
      loadParameterExperiments(),
      loadParameterExperimentBatches(),
      loadResearchWorkflow(),
    ]);
    setParameterExperiments(experimentPayload.parameter_experiments);
    setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
    setResearchWorkflow(workflowPayload.research_workflow);

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
    if (!selectedRunId) {
      const runIds = new Set(runs.map((entry) => entry.run_id));
      const comparedRunId = compareRunIds.find((runId) => runIds.has(runId));
      setSelectedRunId(comparedRunId ?? runs[0].run_id);
      return;
    }
    if (!runs.some((entry) => entry.run_id === selectedRunId)) {
      if (activeTab === 'analysis') {
        return;
      }
      const runIds = new Set(runs.map((entry) => entry.run_id));
      const comparedRunId = compareRunIds.find((runId) => runIds.has(runId));
      setSelectedRunId(comparedRunId ?? runs[0].run_id);
    }
  }, [activeTab, compareRunIds, runs, selectedRunId]);

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

        if (activeTab === 'parameters' && parameterResearch === null) {
          setSectionLoading(true);
          const [researchPayload, workflowPayload, experimentPayload, batchPayload] = await Promise.all([
            loadParameterResearch(),
            loadResearchWorkflow(),
            loadParameterExperiments(),
            loadParameterExperimentBatches(),
          ]);
          if (cancelled) {
            return;
          }
          applyPayloadMeta(researchPayload);
          setParameterResearch(researchPayload.parameter_research);
          setResearchWorkflow(workflowPayload.research_workflow);
          setParameterExperiments(experimentPayload.parameter_experiments);
          setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
          setError(null);
          return;
        }

        if (activeTab === 'parameters' && parameterResearch !== null && (!parameterExperiments.length || !parameterExperimentBatches.length)) {
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

        if (activeTab === 'paper' && !paperSessions.length) {
          setSectionLoading(true);
          const payload = await loadPaperSessions();
          if (cancelled) {
            return;
          }
          applyPayloadMeta(payload);
          setPaperSessions(payload.paper_sessions);
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
  }, [activeTab, overview, paperSessions.length, parameterExperimentBatches.length, parameterResearch, parameterExperiments.length, selectedRunId, RUN_DETAIL_READMODEL_VERSION]);

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
    void Promise.all([loadParameters(), loadParameterResearch(), loadResearchWorkflow()])
      .then(([payload, researchPayload, workflowPayload]) => {
        if (cancelled) {
          return;
        }
        applyPayloadMeta(payload);
        setParameterLab(payload.parameter_lab);
        setParameterResearch(researchPayload.parameter_research);
        setResearchWorkflow(workflowPayload.research_workflow);
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

  const ensureParameterLabLoaded = useCallback(async () => {
    if (parameterLab !== null) {
      return;
    }
    setSectionLoading(true);
    try {
      const payload = await loadParameters();
      applyPayloadMeta(payload);
      setParameterLab(payload.parameter_lab);
      setError(null);
    } catch (loadError: unknown) {
      setError(loadError instanceof Error ? loadError.message : '参数实验明细加载失败');
    } finally {
      setSectionLoading(false);
    }
  }, [parameterLab]);

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
        const strategyName = String(values.strategy_name ?? 'ema_crossover');
        const qtyPolicyRef = String(values.qty_policy_ref ?? 'percent_of_cash');
        const runPayload: Record<string, unknown> = {
          run_id: runId,
          snapshot_id: snapshotId,
          strategy_name: strategyName,
          qty_policy_ref: qtyPolicyRef,
          initial_cash: values.initial_cash,
          leverage: values.leverage,
          fee_rate: values.fee_rate,
          slippage_bps: values.slippage_bps,
          min_notional: values.min_notional,
          benchmark: 'buy_and_hold',
        };
        if (usesRiskPct(qtyPolicyRef)) {
          runPayload.risk_pct_per_trade = values.risk_pct_per_trade;
        }
        if (usesCashAllocation(qtyPolicyRef)) {
          runPayload.cash_allocation_pct = values.cash_allocation_pct;
        }
        if (strategyName === 'ema_pullback_atr_v2') {
          Object.assign(runPayload, {
            trend_fast_period: values.trend_fast_period,
            trend_slow_period: values.trend_slow_period,
            atr_entry_tolerance: values.atr_entry_tolerance,
            atr_stop_mult: values.atr_stop_mult,
            risk_reward_ratio: values.risk_reward_ratio,
            entry_ema_period: 21,
            atr_period: 14,
            min_atr_pct_of_price: 0.002,
            min_stop_pct: 0.003,
          });
        } else {
          Object.assign(runPayload, {
            fast_period: values.fast_period,
            slow_period: values.slow_period,
          });
        }
        const result = strategyName === 'ema_crossover'
          ? await postRunEma(runPayload)
          : await postRun(runPayload);
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

  async function refreshPaperSessions() {
    const payload = await loadPaperSessions();
    applyPayloadMeta(payload);
    setPaperSessions(payload.paper_sessions);
  }

  useEffect(() => {
    if (activeTab !== 'paper') {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      void loadPaperSessions()
        .then((payload) => {
          if (cancelled) {
            return;
          }
          applyPayloadMeta(payload);
          setPaperSessions(payload.paper_sessions);
          setError(null);
        })
        .catch((loadError: unknown) => {
          if (!cancelled) {
            setError(loadError instanceof Error ? loadError.message : '模拟盘状态刷新失败');
          }
        });
    }, PAPER_SESSION_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeTab]);

  async function handleCreatePaperSession(values: Record<string, unknown>) {
    setPaperSubmitting('create');
    try {
      const result = await postPaperSession(values);
      const session = result.paper_session as { session_id?: string } | undefined;
      const sessionId = String(session?.session_id ?? '');
      setLastActionResult(`模拟盘已创建：${sessionId}`);
      message.success(`模拟盘已创建：${sessionId}`);
      await refreshPaperSessions();
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '模拟盘创建失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setPaperSubmitting(null);
    }
  }

  async function handleTickPaperSession(sessionId: string) {
    setPaperSubmitting('tick');
    try {
      const result = await postPaperSessionTick(sessionId, {});
      const fillCount = Number(result.fill_count ?? 0);
      const tradeCount = Number(result.closed_trade_count ?? 0);
      setLastActionResult(`模拟盘 tick 完成：成交 ${fillCount}，平仓 ${tradeCount}`);
      message.success(`模拟盘 tick 完成：成交 ${fillCount}，平仓 ${tradeCount}`);
      await refreshPaperSessions();
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '模拟盘 tick 失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setPaperSubmitting(null);
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
      const batchId = makeParameterBatchId();
      const strategyName = String(values.strategy_name ?? 'ema_crossover');
      const qtyPolicyRef = String(values.qty_policy_ref ?? 'percent_of_cash');
      const experimentPayload: Record<string, unknown> = {
        batch_id: batchId,
        snapshot_ids: snapshotIds,
        strategy_name: strategyName,
        strategy_version: strategyName === 'ema_pullback_atr_v2' ? 'v2' : 'v1',
        search_type: values.search_type,
        leverage_candidates: parsePositiveNumberList(values.leverage_candidates),
        max_samples: values.max_samples,
        qty_policy_ref: qtyPolicyRef,
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
      };
      if (usesRiskPct(qtyPolicyRef)) {
        experimentPayload.risk_pct_per_trade = values.risk_pct_per_trade;
      }
      if (usesCashAllocation(qtyPolicyRef)) {
        experimentPayload.cash_allocation_pct = values.cash_allocation_pct;
      }
      if (strategyName === 'ema_pullback_atr_v2') {
        Object.assign(experimentPayload, {
          trend_fast_periods: parseIntegerList(values.trend_fast_periods),
          trend_slow_periods: parseIntegerList(values.trend_slow_periods),
          atr_entry_tolerances: parsePositiveNumberList(values.atr_entry_tolerances),
          atr_stop_mults: parsePositiveNumberList(values.atr_stop_mults),
          risk_reward_ratios: parsePositiveNumberList(values.risk_reward_ratios),
          entry_ema_period: 21,
          atr_period: 14,
          min_atr_pct_of_price: 0.002,
          min_stop_pct: 0.003,
        });
      } else {
        Object.assign(experimentPayload, {
          fast_periods: parseIntegerList(values.fast_periods),
          slow_periods: parseIntegerList(values.slow_periods),
        });
      }
      const result = await postParameterExperimentBatch(experimentPayload);
      const createdBatchId = String(result.batch_id ?? batchId);
      setLastActionResult(`参数实验批次已提交：${createdBatchId}`);
      message.success(`参数实验批次已提交：${createdBatchId}`);
      const [batchPayload, experimentsPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setSelectedBatchId(createdBatchId || ALL_BATCHES);
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

  async function handleRunTrendNeighborhood(row: ParameterLabRow) {
    setNeighborhoodRunId(row.run_id);
    try {
      if (row.strategy_name !== 'ema_pullback_atr_v2') {
        throw new Error('趋势周期邻域实验仅支持 EMA Pullback ATR v2');
      }
      if (!row.trend_fast_period || !row.trend_slow_period) {
        throw new Error('这个 Run 缺少趋势快慢周期，不能生成邻域实验');
      }
      const baseFastCandidates = trendPeriodNeighborhood(row.trend_fast_period);
      const baseSlowCandidates = trendPeriodNeighborhood(row.trend_slow_period);
      const fastCandidates = uniqueSortedNumbers(baseFastCandidates.filter((period) => period < row.trend_slow_period!));
      const slowCandidates = uniqueSortedNumbers(baseSlowCandidates.filter((period) => period > Math.max(...fastCandidates)));
      if (!fastCandidates.length || !slowCandidates.length) {
        throw new Error('未能生成有效的 fast < slow 趋势周期邻域');
      }

      const batchId = makeParameterBatchId();
      const experimentPayload: Record<string, unknown> = {
        batch_id: batchId,
        snapshot_ids: [row.dataset_snapshot_id],
        strategy_name: 'ema_pullback_atr_v2',
        strategy_version: 'v2',
        search_type: 'grid',
        trend_fast_periods: fastCandidates,
        trend_slow_periods: slowCandidates,
        atr_entry_tolerances: [row.atr_entry_tolerance ?? 1],
        atr_stop_mults: [row.atr_stop_mult ?? 1.5],
        risk_reward_ratios: [row.risk_reward_ratio ?? 1.5],
        entry_ema_period: row.entry_ema_period ?? 21,
        atr_period: row.atr_period ?? 14,
        min_atr_pct_of_price: 0.002,
        min_stop_pct: 0.003,
        leverage_candidates: [row.leverage ?? 1],
        qty_policy_ref: row.qty_policy_ref ?? 'percent_of_cash',
        initial_cash: 10000,
        fee_rate: row.fee_rate ?? 0,
        slippage_bps: row.slippage_bps ?? 0,
        min_notional: 0,
        benchmark: 'buy_and_hold',
        validation_split_mode: 'auto_ratio',
        oos_ratio: 0.3,
        warmup_bars: 0,
      };
      const rowQtyPolicyRef = row.qty_policy_ref ?? 'percent_of_cash';
      if (usesRiskPct(rowQtyPolicyRef)) {
        experimentPayload.risk_pct_per_trade = row.risk_pct_per_trade ?? 0.01;
      }
      if (usesCashAllocation(rowQtyPolicyRef)) {
        experimentPayload.cash_allocation_pct = row.cash_allocation_pct ?? 95;
      }
      const result = await postParameterExperimentBatch(experimentPayload);
      const createdBatchId = String(result.batch_id ?? batchId);
      const summaryText = `趋势周期邻域实验已提交：${createdBatchId}（tf ${fastCandidates.join(',')} / ts ${slowCandidates.join(',')}）`;
      setLastActionResult(summaryText);
      message.success(summaryText);
      const [batchPayload, experimentsPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setSelectedBatchId(createdBatchId || ALL_BATCHES);
      setSelectedBatchDetail(null);
      setSelectedExperimentId(ALL_EXPERIMENTS);
      setSelectedExperimentDetail(null);
      setActiveTab('parameters');
      setError(null);
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '趋势周期邻域实验提交失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setNeighborhoodRunId(null);
    }
  }

  async function handleRunDrawdownProtectionExperiment(run: RunAnalysisView, progressKey?: string) {
    const trackingKey = progressKey ?? run.run_id;
    setDrawdownProtectionRunId(run.run_id);
    setDrawdownProtectionCandidateId(trackingKey);
    try {
      const strategyParams = (run.manifest.resolved_config_json.strategy_params ?? {}) as Record<string, unknown>;
      const executionConstraints = (run.manifest.resolved_config_json.execution_constraints ?? {}) as Record<string, unknown>;
      const strategyName = String(strategyParams.strategy_name ?? run.strategy_name);
      const qtyPolicyRef = String(strategyParams.qty_policy_ref ?? 'risk_pct_of_equity');
      const batchId = `drawdown-guard-${safeBatchKeyPart(trackingKey)}-${dayjs().format('YYYYMMDDHHmmssSSS')}`;
      const experimentPayload: Record<string, unknown> = {
        batch_id: batchId,
        snapshot_ids: [run.dataset_snapshot_id],
        strategy_name: strategyName,
        strategy_version: strategyName === 'ema_pullback_atr_v2' ? 'v2' : 'v1',
        search_type: 'grid',
        leverage_candidates: [numericConfigValue(executionConstraints.leverage, 1)],
        qty_policy_ref: qtyPolicyRef,
        initial_cash: numericConfigValue(executionConstraints.initial_cash, run.metrics.initial_equity || 10000),
        fee_rate: numericConfigValue(executionConstraints.fee_rate, 0),
        slippage_bps: numericConfigValue(executionConstraints.slippage_bps, 0),
        min_notional: numericConfigValue(executionConstraints.min_notional, 0),
        benchmark: 'buy_and_hold',
        validation_split_mode: 'auto_ratio',
        oos_ratio: 0.3,
        warmup_bars: 0,
        execution_protection_sets: drawdownProtectionSets(),
      };
      if (usesRiskPct(qtyPolicyRef)) {
        experimentPayload.risk_pct_per_trade = firstPolicyNumber(executionConstraints.risk_pct_per_trade_by_policy) ?? Number(strategyParams.risk_pct_per_trade ?? 0.01);
      }
      if (usesCashAllocation(qtyPolicyRef)) {
        experimentPayload.cash_allocation_pct = firstPolicyNumber(executionConstraints.cash_allocation_pct_by_policy) ?? Number(strategyParams.cash_allocation_pct ?? 95);
      }
      if (strategyName === 'ema_pullback_atr_v2') {
        const trendFast = Number(strategyParams.trend_fast_period);
        const trendSlow = Number(strategyParams.trend_slow_period);
        if (!Number.isFinite(trendFast) || !Number.isFinite(trendSlow)) {
          throw new Error('当前 Run 缺少 EMA Pullback ATR v2 趋势周期参数，不能发起回撤保护实验');
        }
        Object.assign(experimentPayload, {
          trend_fast_periods: [trendFast],
          trend_slow_periods: [trendSlow],
          atr_entry_tolerances: [numericConfigValue(strategyParams.atr_entry_tolerance, 1)],
          atr_stop_mults: [numericConfigValue(strategyParams.atr_stop_mult, 1.5)],
          risk_reward_ratios: [numericConfigValue(strategyParams.risk_reward_ratio, 1.5)],
          entry_ema_period: numericConfigValue(strategyParams.entry_ema_period, 21),
          atr_period: numericConfigValue(strategyParams.atr_period, 14),
          min_atr_pct_of_price: numericConfigValue(strategyParams.min_atr_pct_of_price, 0.002),
          min_stop_pct: numericConfigValue(strategyParams.min_stop_pct, 0.003),
        });
      } else {
        const fastPeriod = Number(strategyParams.fast_period);
        const slowPeriod = Number(strategyParams.slow_period);
        if (!Number.isFinite(fastPeriod) || !Number.isFinite(slowPeriod)) {
          throw new Error('当前 Run 缺少 EMA 交叉周期参数，不能发起回撤保护实验');
        }
        Object.assign(experimentPayload, {
          fast_periods: [fastPeriod],
          slow_periods: [slowPeriod],
        });
      }

      const result = await postParameterExperimentBatch(experimentPayload);
      const createdBatchId = String(result.batch_id ?? batchId);
      const plannedRunCount = Number(result.planned_run_count ?? drawdownProtectionSets().length);
      setDrawdownProtectionProgressByCandidateId((current) => ({
        ...current,
        [trackingKey]: {
          batchId: createdBatchId,
          status: 'pending',
          runCount: 0,
          plannedRunCount,
        },
      }));
      const summaryText = `回撤保护实验已提交：${createdBatchId}${plannedRunCount ? `（${plannedRunCount} 个 run）` : ''}`;
      setLastActionResult(summaryText);
      message.success(`${summaryText}，完成后自动跳到参数结果`);
      let latestBatch: ParameterExperimentBatchSummary | undefined;
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline) {
        const batchPayload = await loadParameterExperimentBatches();
        applyPayloadMeta(batchPayload);
        setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
        latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId);
        if (latestBatch) {
          setDrawdownProtectionProgressByCandidateId((current) => ({
            ...current,
            [trackingKey]: {
              batchId: createdBatchId,
              status: latestBatch?.status ?? 'pending',
              runCount: Number(latestBatch?.run_count ?? 0),
              plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
            },
          }));
        }
        if (latestBatch?.status === 'success' || latestBatch?.status === 'failed') {
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      const [batchPayload, experimentsPayload, parameterPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
        loadParameters(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setParameterLab(parameterPayload.parameter_lab);
      setSelectedBatchId(createdBatchId || ALL_BATCHES);
      setSelectedBatchDetail(null);
      setSelectedExperimentId(ALL_EXPERIMENTS);
      setSelectedExperimentDetail(null);
      setActiveTab('parameters');
      setError(null);
      latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId) ?? latestBatch;
      const finalStatus = latestBatch?.status ?? 'unknown';
      setDrawdownProtectionProgressByCandidateId((current) => ({
        ...current,
        [trackingKey]: {
          batchId: createdBatchId,
          status: finalStatus,
          runCount: Number(latestBatch?.run_count ?? 0),
          plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
        },
      }));
      if (latestBatch?.status === 'success') {
        message.success(`回撤保护实验已完成：${createdBatchId}`);
      } else if (latestBatch?.status === 'failed') {
        message.error(`回撤保护实验失败：${createdBatchId}`);
      } else {
        message.info(`回撤保护实验仍在后台运行：${createdBatchId}，稍后刷新会更新结果`);
      }
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '回撤保护实验提交失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDrawdownProtectionRunId(null);
      setDrawdownProtectionCandidateId(null);
    }
  }

  async function handleParameterRowDrawdownProtectionExperiment(rowOrRunId: ParameterLabRow | string, progressKey?: string) {
    const runId = typeof rowOrRunId === 'string' ? rowOrRunId : rowOrRunId.run_id;
    const trackingKey = progressKey ?? runId;
    setDrawdownProtectionRunId(runId);
    setDrawdownProtectionCandidateId(trackingKey);
    try {
      const payload = await loadRunDetail(runId);
      applyPayloadMeta(payload);
      await handleRunDrawdownProtectionExperiment(payload.run, trackingKey);
    } catch (loadError: unknown) {
      const text = loadError instanceof Error ? loadError.message : '回撤保护实验提交失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDrawdownProtectionRunId(null);
      setDrawdownProtectionCandidateId(null);
    }
  }

  async function handleRunRiskMatrix(candidate: ResearchCandidateView) {
    setRiskMatrixCandidateId(candidate.candidate_id);
    try {
      const result = await postResearchCandidateRiskMatrix(candidate.candidate_id, {
        risk_pct_per_trade_candidates: [0.01, 0.03, 0.05, 0.10],
        cash_allocation_pct_candidates: [30, 50, 95],
        leverage_candidates: [1, 3, 5, 10],
        oos_ratio: 0.3,
        warmup_bars: 0,
      });
      const createdBatchId = String(result.batch_id ?? '');
      const plannedRunCount = Number(result.planned_run_count ?? 0);
      setRiskMatrixProgressByCandidateId((current) => ({
        ...current,
        [candidate.candidate_id]: {
          batchId: createdBatchId,
          status: 'pending',
          runCount: 0,
          plannedRunCount,
        },
      }));
      const summaryText = `风险矩阵已提交：${createdBatchId}${plannedRunCount ? `（${plannedRunCount} 个 run）` : ''}，完成后会自动刷新`;
      setLastActionResult(summaryText);
      message.success(summaryText);
      let latestBatch: ParameterExperimentBatchSummary | undefined;
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline) {
        const batchPayload = await loadParameterExperimentBatches();
        applyPayloadMeta(batchPayload);
        setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
        latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId);
        if (latestBatch) {
          setRiskMatrixProgressByCandidateId((current) => ({
            ...current,
            [candidate.candidate_id]: {
              batchId: createdBatchId,
              status: latestBatch?.status ?? 'pending',
              runCount: Number(latestBatch?.run_count ?? 0),
              plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
            },
          }));
          if (latestBatch.status === 'success' || latestBatch.status === 'failed') {
            break;
          }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      const [batchPayload, experimentsPayload, parameterPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
        loadParameters(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setParameterLab(parameterPayload.parameter_lab);
      setSelectedBatchId(createdBatchId || ALL_BATCHES);
      setSelectedBatchDetail(null);
      setSelectedExperimentId(ALL_EXPERIMENTS);
      setSelectedExperimentDetail(null);
      setActiveTab('parameters');
      setError(null);
      await refreshResearchWorkflow();
      latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId) ?? latestBatch;
      const finalStatus = latestBatch?.status ?? 'unknown';
      setRiskMatrixProgressByCandidateId((current) => ({
        ...current,
        [candidate.candidate_id]: {
          batchId: createdBatchId,
          status: finalStatus,
          runCount: Number(latestBatch?.run_count ?? 0),
          plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
        },
      }));
      if (finalStatus === 'success') {
        message.success(`风险矩阵已完成：${createdBatchId}，可点击“看风险矩阵”查看`);
      } else if (finalStatus === 'failed') {
        message.error(`风险矩阵失败：${createdBatchId}`);
      } else {
        message.info(`风险矩阵仍在后台运行：${createdBatchId}，稍后刷新会更新状态`);
      }
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '风险矩阵提交失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setRiskMatrixCandidateId(null);
    }
  }

  async function handleRunFilterExperiment(candidate: ResearchCandidateView, profile: FilterExperimentProfile = 'early_fail_proxy') {
    setFilterExperimentCandidateId(candidate.candidate_id);
    try {
      const filterTypes = profile === 'early_fail_proxy' ? EARLY_FAIL_PROXY_FILTER_TYPES : GENERAL_FILTER_TYPES;
      const mode = profile === 'early_fail_proxy' ? 'single' : 'stacked';
      const payload: Record<string, unknown> = {
        mode,
        oos_ratio: 0.3,
        warmup_bars: 0,
      };
      if (profile === 'early_fail_proxy') {
        payload.signal_filter_sets = EARLY_FAIL_PROXY_SIGNAL_FILTER_SETS;
      } else {
        payload.filter_types = [...filterTypes];
      }
      const result = await postResearchCandidateFilterExperiment(candidate.candidate_id, payload);
      const createdBatchId = String(result.batch_id ?? '');
      const plannedRunCount = Number(result.planned_run_count ?? 0);
      setFilterExperimentProgressByCandidateId((current) => ({
        ...current,
        [candidate.candidate_id]: {
          batchId: createdBatchId,
          status: 'pending',
          runCount: 0,
          plannedRunCount,
        },
      }));
      const modeLabel = profile === 'early_fail_proxy' ? '早败代理过滤实验' : '通用过滤实验';
      const summaryText = `${modeLabel}已提交：${createdBatchId}${plannedRunCount ? `（${plannedRunCount} 个 run）` : ''}，完成后会自动刷新`;
      setLastActionResult(summaryText);
      message.success(summaryText);
      let latestBatch: ParameterExperimentBatchSummary | undefined;
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline) {
        const batchPayload = await loadParameterExperimentBatches();
        applyPayloadMeta(batchPayload);
        setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
        latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId);
        if (latestBatch) {
          setFilterExperimentProgressByCandidateId((current) => ({
            ...current,
            [candidate.candidate_id]: {
              batchId: createdBatchId,
              status: latestBatch?.status ?? 'pending',
              runCount: Number(latestBatch?.run_count ?? 0),
              plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
            },
          }));
          if (latestBatch.status === 'success' || latestBatch.status === 'failed') {
            break;
          }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      const [batchPayload, experimentsPayload, parameterPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
        loadParameters(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setParameterLab(parameterPayload.parameter_lab);
      setSelectedBatchId(createdBatchId || ALL_BATCHES);
      setSelectedBatchDetail(null);
      setSelectedExperimentId(ALL_EXPERIMENTS);
      setSelectedExperimentDetail(null);
      setActiveTab('parameters');
      setError(null);
      await refreshResearchWorkflow();
      latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId) ?? latestBatch;
      const finalStatus = latestBatch?.status ?? 'unknown';
      setFilterExperimentProgressByCandidateId((current) => ({
        ...current,
        [candidate.candidate_id]: {
          batchId: createdBatchId,
          status: finalStatus,
          runCount: Number(latestBatch?.run_count ?? 0),
          plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
        },
      }));
      if (finalStatus === 'success') {
        message.success(`过滤器实验已完成：${createdBatchId}`);
      } else if (finalStatus === 'failed') {
        message.error(`过滤器实验失败：${createdBatchId}`);
      } else {
        message.info(`过滤器实验仍在后台运行：${createdBatchId}，稍后刷新会更新状态`);
      }
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '过滤器实验提交失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setFilterExperimentCandidateId(null);
    }
  }

  async function handleRunExecutionFilterExperiment(candidate: StableCandidateView): Promise<string | null> {
    const sourceRunId = candidate.execution_verification.latest_run_id;
    if (!sourceRunId) {
      message.warning('需要先跑 5m 执行验证');
      return null;
    }
    setFilterExperimentCandidateId(candidate.stable_candidate_id);
    try {
      const result = await postStableCandidateExecutionFilterExperiment(candidate.stable_candidate_id, {
        source_run_id: sourceRunId,
        signal_filter_sets: EARLY_FAIL_PROXY_SIGNAL_FILTER_SETS,
      });
      const createdBatchId = String(result.batch_id ?? '');
      const plannedRunCount = Number(result.planned_run_count ?? 0);
      setFilterExperimentProgressByCandidateId((current) => ({
        ...current,
        [candidate.stable_candidate_id]: {
          batchId: createdBatchId,
          status: 'pending',
          runCount: 0,
          plannedRunCount,
        },
      }));
      const summaryText = `5m过滤实验已提交：${createdBatchId}${plannedRunCount ? `（${plannedRunCount} 个 run）` : ''}，完成后会自动刷新`;
      setLastActionResult(summaryText);
      message.success(summaryText);
      let latestBatch: ParameterExperimentBatchSummary | undefined;
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline) {
        const batchPayload = await loadParameterExperimentBatches();
        applyPayloadMeta(batchPayload);
        setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
        latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId);
        if (latestBatch) {
          setFilterExperimentProgressByCandidateId((current) => ({
            ...current,
            [candidate.stable_candidate_id]: {
              batchId: createdBatchId,
              status: latestBatch?.status ?? 'pending',
              runCount: Number(latestBatch?.run_count ?? 0),
              plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
            },
          }));
          if (latestBatch.status === 'success' || latestBatch.status === 'failed') {
            break;
          }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      const [batchPayload, experimentsPayload, parameterPayload] = await Promise.all([
        loadParameterExperimentBatches(),
        loadParameterExperiments(),
        loadParameters(),
      ]);
      applyPayloadMeta(batchPayload);
      setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
      setParameterExperiments(experimentsPayload.parameter_experiments);
      setParameterLab(parameterPayload.parameter_lab);
      setSelectedBatchId(createdBatchId || ALL_BATCHES);
      setSelectedBatchDetail(null);
      setSelectedExperimentId(ALL_EXPERIMENTS);
      setSelectedExperimentDetail(null);
      setActiveTab('parameters');
      setError(null);
      await refreshResearchWorkflow();
      latestBatch = batchPayload.parameter_experiment_batches.find((batch) => batch.batch_id === createdBatchId) ?? latestBatch;
      const finalStatus = latestBatch?.status ?? 'unknown';
      setFilterExperimentProgressByCandidateId((current) => ({
        ...current,
        [candidate.stable_candidate_id]: {
          batchId: createdBatchId,
          status: finalStatus,
          runCount: Number(latestBatch?.run_count ?? 0),
          plannedRunCount: Number(latestBatch?.planned_run_count ?? plannedRunCount),
        },
      }));
      if (finalStatus === 'success') {
        message.success(`5m过滤实验已完成：${createdBatchId}`);
      } else if (finalStatus === 'failed') {
        message.error(`5m过滤实验失败：${createdBatchId}`);
      } else {
        message.info(`5m过滤实验仍在后台运行：${createdBatchId}，稍后刷新会更新状态`);
      }
      return createdBatchId || null;
    } catch (submitError: unknown) {
      const text = submitError instanceof Error ? submitError.message : '5m过滤实验提交失败';
      setLastActionResult(text);
      message.error(text);
      return null;
    } finally {
      setFilterExperimentCandidateId(null);
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
      const payload: Record<string, unknown> = {
        target_type: targetType,
        target_id: targetId,
        author: String(values.author ?? 'local').trim() || 'local',
        content: String(values.content ?? '').trim(),
        labels: Array.isArray(values.labels) ? values.labels : [],
        decision_status: String(values.decision_status ?? 'candidate').trim() || 'candidate',
      };
      const decisionReason = String(values.decision_reason ?? '').trim();
      if (decisionReason) {
        payload.decision_reason = decisionReason;
      }
      if (values.confidence_score !== null && values.confidence_score !== undefined && values.confidence_score !== '') {
        payload.confidence_score = Number(values.confidence_score);
      }
      const linkedBatchId = String(values.linked_batch_id ?? '').trim();
      if (linkedBatchId) {
        payload.linked_batch_id = linkedBatchId;
      }
      const linkedParameterGroup = String(values.linked_parameter_group ?? '').trim();
      if (linkedParameterGroup) {
        payload.linked_parameter_group = linkedParameterGroup;
      }
      await postResearchNote(payload);
      const notesPayload = await loadResearchNotes(targetType, targetId);
      setResearchNotes((current) => {
        const retained = current.filter((note) => !(note.target_type === targetType && note.target_id === targetId));
        return [...notesPayload.research_notes, ...retained];
      });
      setLastActionResult(`研究备注已保存：${targetId}`);
      setError(null);
      message.success('研究备注已保存');
      await refreshResearchWorkflow();
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
  }

  async function handleDeleteResearchNote(note: ResearchNote) {
    setDeletingResearchNoteId(note.note_id);
    try {
      await deleteResearchNote(note.note_id);
      const notesPayload = await loadResearchNotes(note.target_type, note.target_id);
      setResearchNotes((current) => {
        const retained = current.filter((item) => !(item.target_type === note.target_type && item.target_id === note.target_id));
        return [...notesPayload.research_notes, ...retained];
      });
      if (note.target_type === 'run' && selectedRun?.run_id === note.target_id) {
        const payload = await loadRunDetail(note.target_id);
        applyPayloadMeta(payload);
        setSelectedRun(payload.run);
      }
      await refreshResearchWorkflow();
      setLastActionResult(`研究备注已删除：${note.note_id}`);
      setError(null);
      message.success('研究备注已删除');
    } catch (deleteError: unknown) {
      const text = deleteError instanceof Error ? deleteError.message : '研究备注删除失败';
      setLastActionResult(text);
      message.error(text);
    } finally {
      setDeletingResearchNoteId(null);
    }
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
              setSelectedRun={setSelectedRun}
              setSelectedRunId={setSelectedRunId}
              deletingRunId={deletingRunId}
              onDeleteRun={handleDeleteRun}
              onSaveResearchNote={handleSaveResearchNote}
              onDeleteResearchNote={handleDeleteResearchNote}
              savingResearchNote={savingResearchNote}
              deletingResearchNoteId={deletingResearchNoteId}
              onRunDrawdownProtectionExperiment={handleRunDrawdownProtectionExperiment}
              drawdownProtectionRunId={drawdownProtectionRunId}
            />
          )}
          {activeTab === 'parameters' && (parameterResearch || parameterLab) && (
            <ParametersView
              datasets={datasets}
              rows={filteredParameterRows}
              allRows={parameterLab?.rows ?? []}
              parameterResearch={parameterResearch}
              researchWorkflow={researchWorkflow}
              researchNotes={researchNotes}
              manualLabelsByRunId={manualLabelsByRunId}
              fastRows={parameterLab?.fast_period_total_return ?? []}
              slowRows={parameterLab?.slow_period_total_return ?? []}
              parameterLabLoaded={parameterLab !== null}
              onEnsureParameterLab={ensureParameterLabLoaded}
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
              neighborhoodRunId={neighborhoodRunId}
              onSubmitExperiment={handleSubmitParameterExperiment}
              onRunTrendNeighborhood={handleRunTrendNeighborhood}
              onRunDrawdownProtectionExperiment={handleParameterRowDrawdownProtectionExperiment}
              onRunRiskMatrix={handleRunRiskMatrix}
              onRunFilterExperiment={handleRunFilterExperiment}
              onRunExecutionFilterExperiment={handleRunExecutionFilterExperiment}
              drawdownProtectionRunId={drawdownProtectionRunId}
              drawdownProtectionCandidateId={drawdownProtectionCandidateId}
              drawdownProtectionProgressByCandidateId={drawdownProtectionProgressByCandidateId}
              riskMatrixCandidateId={riskMatrixCandidateId}
              riskMatrixProgressByCandidateId={riskMatrixProgressByCandidateId}
              filterExperimentCandidateId={filterExperimentCandidateId}
              filterExperimentProgressByCandidateId={filterExperimentProgressByCandidateId}
              onLoadParameterRows={async () => {
                const parameterPayload = await loadParameters();
                applyPayloadMeta(parameterPayload);
                setParameterLab(parameterPayload.parameter_lab);
                return parameterPayload.parameter_lab.rows;
              }}
              onOpenRun={(runId) => {
                setSelectedRun(null);
                setSelectedRunId(runId);
                setActiveTab('analysis');
              }}
              onDeleteRun={handleDeleteRun}
              onDeleteExperiment={handleDeleteParameterExperiment}
              onDeleteBatch={handleDeleteParameterExperimentBatch}
              onSaveResearchNote={handleSaveTargetResearchNote}
              savingResearchNote={savingResearchNote}
              onResearchWorkflowOptimisticChange={(updater) => setResearchWorkflow((current) => updater(current))}
              onRefreshResearchWorkflow={refreshResearchWorkflow}
              onRefreshShell={refreshShell}
              onRefreshExperiments={async () => {
                const [experimentPayload, batchPayload, researchPayload, workflowPayload] = await Promise.all([
                  loadParameterExperiments(),
                  loadParameterExperimentBatches(),
                  loadParameterResearch(),
                  loadResearchWorkflow(),
                ]);
                applyPayloadMeta(experimentPayload);
                setParameterExperiments(experimentPayload.parameter_experiments);
                setParameterExperimentBatches(batchPayload.parameter_experiment_batches);
                setParameterResearch(researchPayload.parameter_research);
                setResearchWorkflow(workflowPayload.research_workflow);
                if (parameterLab !== null) {
                  const parameterPayload = await loadParameters();
                  applyPayloadMeta(parameterPayload);
                  setParameterLab(parameterPayload.parameter_lab);
                }
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
          {activeTab === 'paper' && (
            <PaperTradingView
              sessions={paperSessions}
              stableCandidates={researchWorkflow?.stable_pool.candidates ?? []}
              runs={runs}
              form={paperForm}
              submitting={paperSubmitting}
              onCreate={handleCreatePaperSession}
              onTick={handleTickPaperSession}
              onRefresh={refreshPaperSessions}
            />
          )}
        </Spin>
      </Content>
    </Layout>
  );
}

function PaperTradingView({
  sessions,
  stableCandidates,
  runs,
  form,
  submitting,
  onCreate,
  onTick,
  onRefresh,
}: {
  sessions: PaperSessionView[];
  stableCandidates: StableCandidateView[];
  runs: RunSummaryView[];
  form: ReturnType<typeof Form.useForm>[0];
  submitting: 'create' | 'tick' | null;
  onCreate: (values: Record<string, unknown>) => Promise<void>;
  onTick: (sessionId: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const selectedStableCandidateId = Form.useWatch('stable_candidate_id', form) as string | undefined;
  const selectedStableCandidate = stableCandidates.find((candidate) => candidate.stable_candidate_id === selectedStableCandidateId);
  const [recordSession, setRecordSession] = useState<PaperSessionView | null>(null);
  const [recordLoading, setRecordLoading] = useState(false);
  const [selectedSnapshotSessionId, setSelectedSnapshotSessionId] = useState<string>('');
  const [signalSnapshot, setSignalSnapshot] = useState<PaperSignalSnapshotView | null>(null);
  const [signalSnapshotLoading, setSignalSnapshotLoading] = useState(false);
  const [signalSnapshotError, setSignalSnapshotError] = useState<string | null>(null);
  const snapshotSessionId = selectedSnapshotSessionId || sessions[0]?.session_id || '';
  const sourceRunOptions = useMemo(() => {
    const evidenceRunIds = selectedStableCandidate?.evidence_run_ids ?? [];
    const representativeRunId = selectedStableCandidate?.representative_run_id;
    const orderedRunIds = [
      ...(representativeRunId ? [representativeRunId] : []),
      ...evidenceRunIds.filter((runId) => runId !== representativeRunId),
    ];
    const candidateRunIds = orderedRunIds.length ? orderedRunIds : runs.map((run) => run.run_id);
    return candidateRunIds.map((runId) => {
      const run = runs.find((entry) => entry.run_id === runId);
      return {
        label: `${shortRunId(runId)} · ${run?.symbol ?? selectedStableCandidate?.symbol ?? '未知标的'} · ${(run?.timeframe ?? selectedStableCandidate?.timeframe ?? '').toUpperCase()}`,
        value: runId,
      };
    });
  }, [runs, selectedStableCandidate]);
  async function openPaperRecords(sessionId: string) {
    setRecordLoading(true);
    try {
      const payload = await loadPaperSession(sessionId);
      setRecordSession(payload.paper_session);
    } finally {
      setRecordLoading(false);
    }
  }

  useEffect(() => {
    if (!sessions.length) {
      setSelectedSnapshotSessionId('');
      setSignalSnapshot(null);
      return;
    }
    if (selectedSnapshotSessionId && sessions.some((session) => session.session_id === selectedSnapshotSessionId)) {
      return;
    }
    setSelectedSnapshotSessionId(sessions[0].session_id);
  }, [selectedSnapshotSessionId, sessions]);

  async function refreshSignalSnapshot(options?: { backfill?: boolean }) {
    if (!snapshotSessionId) {
      return;
    }
    setSignalSnapshotLoading(true);
    setSignalSnapshotError(null);
    try {
      const payload = await loadPaperSignalSnapshot(snapshotSessionId, options);
      setSignalSnapshot(payload.paper_signal_snapshot);
    } catch (loadError: unknown) {
      setSignalSnapshotError(loadError instanceof Error ? loadError.message : '信号快照加载失败');
    } finally {
      setSignalSnapshotLoading(false);
    }
  }

  useEffect(() => {
    if (!snapshotSessionId) {
      return;
    }
    void refreshSignalSnapshot();
  }, [snapshotSessionId]);

  const columns = useMemo<ColumnDef<PaperSessionView>[]>(() => [
    {
      id: 'session',
      header: 'Session',
      size: 220,
      minSize: 220,
      accessorFn: (row) => row.session_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={2} className="cbw-paper-session-cell">
          <Tooltip title={row.original.session_id}>
            <Text strong className="cbw-paper-session-title">{paperSessionLabel(row.original)}</Text>
          </Tooltip>
          <Tooltip title={row.original.stable_candidate_id}>
            <Text type="secondary" className="cbw-paper-session-sub">{paperCandidateLabel(row.original.stable_candidate_id)}</Text>
          </Tooltip>
        </Space>
      ),
    },
    { header: '标的', accessorKey: 'symbol', size: 130, minSize: 130 },
    {
      id: 'timeframes',
      header: '周期',
      size: 80,
      minSize: 80,
      cell: ({ row }) => `${row.original.strategy_timeframe.toUpperCase()} / ${row.original.execution_timeframe.toUpperCase()}`,
    },
    {
      id: 'status',
      header: '状态',
      size: 90,
      minSize: 90,
      accessorFn: (row) => row.status,
      cell: ({ row }) => <Tag color={row.original.status === 'active' ? 'green' : 'default'}>{row.original.status}</Tag>,
    },
    { id: 'equity', header: '权益', size: 110, minSize: 110, accessorFn: (row) => row.account.equity, cell: ({ row }) => formatNumber(row.original.account.equity, 2) },
    { id: 'cash', header: '可用资金', size: 110, minSize: 110, accessorFn: (row) => row.account.available_cash, cell: ({ row }) => formatNumber(row.original.account.available_cash, 2) },
    { id: 'unrealized', header: '浮盈亏', size: 100, minSize: 100, accessorFn: (row) => row.account.unrealized_pnl, cell: ({ row }) => formatNumber(row.original.account.unrealized_pnl, 2) },
    {
      id: 'position',
      header: '持仓',
      size: 130,
      minSize: 130,
      cell: ({ row }) => {
        const position = row.original.position;
        if (!position) {
          return <Text type="secondary">空仓</Text>;
        }
        return (
          <Space direction="vertical" size={0}>
            <Text>{position.trade.side.toUpperCase()} · qty {formatNumber(position.trade.qty, 4)}</Text>
            <Text type="secondary">入场 {formatNumber(position.trade.entry_price, 2)}</Text>
          </Space>
        );
      },
    },
    {
      id: 'checkpoint',
      header: '最新 5m',
      size: 180,
      minSize: 180,
      cell: ({ row }) => {
        const executionStream = row.original.live_streams?.find((stream) => stream.timeframe === row.original.execution_timeframe);
        return (
          <Space direction="vertical" size={0}>
            <Text>{row.original.checkpoint.last_execution_bar_time ? formatDateTime(row.original.checkpoint.last_execution_bar_time) : '--'}</Text>
            <Text type="secondary">bars {row.original.checkpoint.execution_bar_count}</Text>
            {executionStream ? (
              <Space size={4} wrap>
                <Tag color={executionStream.status === 'connected' ? 'processing' : executionStream.status === 'error' ? 'red' : 'default'}>
                  WS {executionStream.status}
                </Tag>
                {executionStream.auto_tick_status ? (
                  <Tag color={executionStream.auto_tick_status === 'success' ? 'green' : executionStream.auto_tick_status === 'error' ? 'red' : 'default'}>
                    auto {executionStream.auto_tick_status}
                  </Tag>
                ) : null}
                <Text type="secondary">
                  {executionStream.auto_tick_at
                    ? `tick ${formatDateTime(executionStream.auto_tick_at)}`
                    : executionStream.last_closed_bar_time
                      ? formatDateTime(executionStream.last_closed_bar_time)
                      : executionStream.last_message_at
                        ? formatDateTime(executionStream.last_message_at)
                        : '--'}
                </Text>
                {executionStream.auto_tick_error ? (
                  <Tooltip title={executionStream.auto_tick_error}>
                    <Text type="danger">error</Text>
                  </Tooltip>
                ) : null}
              </Space>
            ) : null}
          </Space>
        );
      },
    },
    {
      id: 'actions',
      header: '操作',
      size: 110,
      minSize: 110,
      enableSorting: false,
      cell: ({ row }) => (
        <Space size={8} wrap>
          <Button
            size="small"
            onClick={() => void openPaperRecords(row.original.session_id)}
          >
            交易记录
          </Button>
          <Button
            size="small"
            type="primary"
            loading={submitting === 'tick'}
            onClick={() => void onTick(row.original.session_id)}
          >
            tick
          </Button>
        </Space>
      ),
    },
  ], [onTick, submitting]);
  const activeSessions = sessions.filter((session) => session.status === 'active');
  const openPositions = sessions.filter((session) => session.position !== null);

  return (
    <>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card><Statistic title="模拟盘 Session" value={sessions.length} /></Card>
        </Col>
        <Col xs={24} md={8}>
          <Card><Statistic title="运行中" value={activeSessions.length} /></Card>
        </Col>
        <Col xs={24} md={8}>
          <Card><Statistic title="持仓中" value={openPositions.length} /></Card>
        </Col>

      <Col xs={24} xl={7} xxl={6}>
        <Card title="创建模拟盘" extra={<Tag color="blue">1h 信号 / 5m 执行</Tag>}>
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              stable_candidate_id: stableCandidates[0]?.stable_candidate_id,
              source_run_id: stableCandidates[0]?.representative_run_id,
              initial_cash: 10000,
              execution_timeframe: '5m',
            }}
            onFinish={(values) => void onCreate(values as Record<string, unknown>)}
          >
            <Form.Item name="stable_candidate_id" label="稳定候选" rules={[{ required: true }]}>
              <Select
                showSearch
                optionFilterProp="label"
                options={stableCandidates.map((candidate) => ({
                  label: `${candidate.symbol} · ${candidate.timeframe.toUpperCase()} · ${candidate.stable_candidate_id}`,
                  value: candidate.stable_candidate_id,
                }))}
                onChange={(value) => {
                  const candidate = stableCandidates.find((entry) => entry.stable_candidate_id === value);
                  form.setFieldValue('source_run_id', candidate?.representative_run_id ?? candidate?.evidence_run_ids[0]);
                }}
              />
            </Form.Item>
            <Form.Item name="source_run_id" label="代表 Run" rules={[{ required: true }]}>
              <Select showSearch optionFilterProp="label" options={sourceRunOptions} />
            </Form.Item>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="initial_cash" label="初始资金">
                  <InputNumber min={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="execution_timeframe" label="执行周期" rules={[{ required: true }]}>
                  <Select options={[{ label: '5m', value: '5m' }]} />
                </Form.Item>
              </Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={submitting === 'create'} disabled={!stableCandidates.length}>
              创建模拟盘
            </Button>
          </Form>
          {!stableCandidates.length ? (
            <Alert style={{ marginTop: 16 }} type="info" showIcon message="稳定池还没有候选" description="先在参数实验页把候选加入稳定池，再创建模拟盘。" />
          ) : null}
        </Card>
      </Col>

      <Col xs={24} xl={17} xxl={18}>
        <Card
          title="模拟盘运行表"
          extra={<Button onClick={() => void onRefresh()}>刷新</Button>}
        >
          {sessions.length ? (
            <DataTable
              columns={columns}
              data={sessions}
              initialPageSize={8}
              pageSizeOptions={[8, 16, 32]}
              initialSorting={[{ id: 'session', desc: true }]}
              tableClassName="cbw-paper-table"
            />
          ) : (
            <Alert type="info" showIcon message="暂无模拟盘 session" description="创建后会在这里显示权益、持仓和最近 tick 位置。" />
          )}
        </Card>
      </Col>
      <Col xs={24}>
        <PaperSignalSnapshotPanel
          sessions={sessions}
          selectedSessionId={snapshotSessionId}
          snapshot={signalSnapshot}
          loading={signalSnapshotLoading}
          error={signalSnapshotError}
          onSelectSession={setSelectedSnapshotSessionId}
          onRefresh={() => void refreshSignalSnapshot()}
          onBackfill={() => void refreshSignalSnapshot({ backfill: true })}
        />
      </Col>
      </Row>
      <PaperRecordsModal
        session={recordSession}
        loading={recordLoading}
        onClose={() => setRecordSession(null)}
      />
    </>
  );
}

function paperSessionLabel(session: PaperSessionView): string {
  const created = session.created_at ? dayjs(session.created_at).format('MM/DD HH:mm') : '';
  return `${session.strategy_name} · ${session.symbol} · ${created}`;
}

function paperCandidateLabel(candidateId: string): string {
  const parts = candidateId.split('|');
  if (parts.length >= 4) {
    return `${parts[0]} · ${parts[1]} · ${parts[2]}`;
  }
  return candidateId;
}

function PaperSignalSnapshotPanel({
  sessions,
  selectedSessionId,
  snapshot,
  loading,
  error,
  onSelectSession,
  onRefresh,
  onBackfill,
}: {
  sessions: PaperSessionView[];
  selectedSessionId: string;
  snapshot: PaperSignalSnapshotView | null;
  loading: boolean;
  error: string | null;
  onSelectSession: (sessionId: string) => void;
  onRefresh: () => void;
  onBackfill: () => void;
}) {
  const triggerColor = snapshot?.trigger.status === 'triggered_on_latest_strategy_bar' ? 'green' : 'blue';
  const backfillColor = snapshot?.backfill.status === 'success' || snapshot?.backfill.status === 'up_to_date'
    ? 'green'
    : snapshot?.backfill.status === 'error'
      ? 'red'
      : 'default';
  return (
    <Card
      title="信号快照"
      extra={(
        <Space wrap>
          <Select
            style={{ minWidth: 280 }}
            value={selectedSessionId || undefined}
            placeholder="选择模拟盘"
            options={sessions.map((session) => ({
              label: paperSessionLabel(session),
              value: session.session_id,
            }))}
            onChange={onSelectSession}
          />
          <Button onClick={onRefresh} loading={loading}>刷新快照</Button>
          <Button onClick={onBackfill} loading={loading}>补齐缺口</Button>
        </Space>
      )}
    >
      <Spin spinning={loading}>
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        {snapshot ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={12} md={6} xl={3}><Statistic title={`EMA${formatCompactPeriod(snapshot.indicators.ema_fast_period)}`} value={snapshot.indicators.ema_fast ?? '--'} precision={2} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title={`EMA${formatCompactPeriod(snapshot.indicators.ema_slow_period)}`} value={snapshot.indicators.ema_slow ?? '--'} precision={2} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title="EMA21" value={snapshot.indicators.ema21 ?? '--'} precision={2} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title="ATR14" value={snapshot.indicators.atr ?? '--'} precision={2} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title="触发价" value={snapshot.trigger.trigger_price ?? '--'} precision={2} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title="预计成交" value={snapshot.estimate.entry_price ?? '--'} precision={2} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title="预计仓位" value={snapshot.estimate.qty ?? '--'} precision={4} /></Col>
              <Col xs={12} md={6} xl={3}><Statistic title="占用保证金" value={snapshot.estimate.margin ?? '--'} precision={2} /></Col>
            </Row>
            <Row gutter={[12, 12]}>
              <Col xs={24} lg={12}>
                <Descriptions size="small" column={2} bordered>
                  <Descriptions.Item label="方向"><Tag color={snapshot.trigger.side === 'long' ? 'green' : snapshot.trigger.side === 'short' ? 'red' : 'default'}>{snapshot.trigger.side ?? '--'}</Tag></Descriptions.Item>
                  <Descriptions.Item label="状态"><Tag color={triggerColor}>{snapshot.trigger.status}</Tag></Descriptions.Item>
                  <Descriptions.Item label="距触发">{formatOptionalNumber(snapshot.trigger.distance_to_trigger, 2)}</Descriptions.Item>
                  <Descriptions.Item label="最新收盘">{formatOptionalNumber(snapshot.trigger.last_close, 2)}</Descriptions.Item>
                  <Descriptions.Item label="止损">{formatOptionalNumber(snapshot.estimate.stop_loss, 2)}</Descriptions.Item>
                  <Descriptions.Item label="止盈">{formatOptionalNumber(snapshot.estimate.take_profit, 2)}</Descriptions.Item>
                </Descriptions>
              </Col>
              <Col xs={24} lg={12}>
                <Descriptions size="small" column={2} bordered>
                  <Descriptions.Item label="1H 数据">{formatOptionalDateTime(snapshot.data.last_strategy_bar_time)}</Descriptions.Item>
                  <Descriptions.Item label="执行数据">{formatOptionalDateTime(snapshot.data.last_execution_bar_time)}</Descriptions.Item>
                  <Descriptions.Item label="执行 bars">{snapshot.data.execution_bar_count}</Descriptions.Item>
                  <Descriptions.Item label="缺口数">{snapshot.data.execution_gap_count}</Descriptions.Item>
                  <Descriptions.Item label="补齐状态"><Tag color={backfillColor}>{snapshot.backfill.status}</Tag></Descriptions.Item>
                  <Descriptions.Item label="补齐 bars">{snapshot.backfill.fetched_bars}</Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
            {snapshot.data.execution_gap_count > 0 ? (
              <Alert
                type="warning"
                showIcon
                message="执行 K 线存在历史缺口"
                description={`${formatOptionalDateTime(snapshot.data.latest_gap_start)} 到 ${formatOptionalDateTime(snapshot.data.latest_gap_end)}。可点“补齐缺口”做一次限频 REST 补齐。`}
              />
            ) : null}
            {snapshot.backfill.error ? <Alert type="error" showIcon message={snapshot.backfill.error} /> : null}
          </Space>
        ) : (
          <Alert type="info" showIcon message="选择一个模拟盘后查看 EMA / ATR / 触发价 / 预计风控。" />
        )}
      </Spin>
    </Card>
  );
}

function formatOptionalNumber(value: number | null | undefined, precision = 2): string {
  return value === null || value === undefined ? '--' : formatNumber(value, precision);
}

function formatOptionalDateTime(value: string | null | undefined): string {
  return value ? formatDateTime(value) : '--';
}

function formatCompactPeriod(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '';
  }
  return Number.isInteger(value) ? String(value) : formatNumber(value, 0);
}

function PaperRecordsModal({
  session,
  loading,
  onClose,
}: {
  session: PaperSessionView | null;
  loading: boolean;
  onClose: () => void;
}) {
  const tradeColumns = useMemo<ColumnDef<PaperTradeView>[]>(() => [
    { header: '开仓', accessorFn: (row) => row.entry_time, cell: ({ row }) => formatDateTime(row.original.entry_time), size: 140, minSize: 140 },
    { header: '平仓', accessorFn: (row) => row.exit_time ?? '', cell: ({ row }) => row.original.exit_time ? formatDateTime(row.original.exit_time) : '--', size: 140, minSize: 140 },
    { header: '方向', accessorKey: 'side', size: 70, minSize: 70 },
    { header: '数量', accessorFn: (row) => Number(row.qty), cell: ({ row }) => formatNumber(Number(row.original.qty), 4), size: 90, minSize: 90 },
    { header: '开仓价', accessorFn: (row) => Number(row.entry_price), cell: ({ row }) => formatNumber(Number(row.original.entry_price), 2), size: 100, minSize: 100 },
    { header: '平仓价', accessorFn: (row) => Number(row.exit_price ?? 0), cell: ({ row }) => row.original.exit_price === null ? '--' : formatNumber(Number(row.original.exit_price), 2), size: 100, minSize: 100 },
    { header: '净盈亏', accessorFn: (row) => Number(row.net_pnl), cell: ({ row }) => <Text type={Number(row.original.net_pnl) >= 0 ? 'success' : 'danger'}>{formatNumber(Number(row.original.net_pnl), 2)}</Text>, size: 100, minSize: 100 },
    { header: '收益率', accessorFn: (row) => Number(row.return_pct), cell: ({ row }) => formatPct(Number(row.original.return_pct)), size: 90, minSize: 90 },
    { header: '原因', accessorKey: 'exit_reason', size: 150, minSize: 150 },
  ], []);
  const fillColumns = useMemo<ColumnDef<PaperFillView>[]>(() => [
    { header: '时间', accessorFn: (row) => row.fill_time, cell: ({ row }) => formatDateTime(row.original.fill_time), size: 140, minSize: 140 },
    { header: '成交价', accessorFn: (row) => Number(row.fill_price), cell: ({ row }) => formatNumber(Number(row.original.fill_price), 2), size: 100, minSize: 100 },
    { header: '数量', accessorFn: (row) => Number(row.qty), cell: ({ row }) => formatNumber(Number(row.original.qty), 4), size: 90, minSize: 90 },
    { header: '手续费', accessorFn: (row) => Number(row.fee), cell: ({ row }) => formatNumber(Number(row.original.fee), 2), size: 90, minSize: 90 },
    { header: '滑点', accessorFn: (row) => Number(row.slippage_cost), cell: ({ row }) => formatNumber(Number(row.original.slippage_cost), 2), size: 90, minSize: 90 },
    { header: '订单', accessorKey: 'order_id', size: 150, minSize: 150 },
  ], []);
  const orderColumns = useMemo<ColumnDef<PaperOrderView>[]>(() => [
    { header: '时间', accessorFn: (row) => row.request_time, cell: ({ row }) => formatDateTime(row.original.request_time), size: 140, minSize: 140 },
    { header: '状态', accessorKey: 'status', size: 80, minSize: 80 },
    { header: '方向', accessorKey: 'side', size: 70, minSize: 70 },
    { header: '数量', accessorFn: (row) => Number(row.qty), cell: ({ row }) => formatNumber(Number(row.original.qty), 4), size: 90, minSize: 90 },
    { header: '请求价', accessorFn: (row) => Number(row.request_price ?? 0), cell: ({ row }) => row.original.request_price === null || row.original.request_price === '' ? '--' : formatNumber(Number(row.original.request_price), 2), size: 100, minSize: 100 },
    { header: '订单ID', accessorKey: 'order_id', size: 150, minSize: 150 },
  ], []);
  const warningColumns = useMemo<ColumnDef<PaperWarningView>[]>(() => [
    { header: '级别', accessorKey: 'severity', size: 80, minSize: 80 },
    { header: '代码', accessorKey: 'warning_code', size: 140, minSize: 140 },
    { header: '消息', accessorKey: 'message', size: 360, minSize: 360 },
  ], []);

  return (
    <Modal
      title={session ? `交易记录 · ${paperSessionLabel(session)}` : '交易记录'}
      open={Boolean(session) || loading}
      onCancel={onClose}
      footer={null}
      width={1080}
      destroyOnClose
    >
      <Spin spinning={loading}>
        {session ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={12} md={6}><Statistic title="成交" value={session.fills?.length ?? 0} /></Col>
              <Col xs={12} md={6}><Statistic title="平仓" value={session.trades?.length ?? 0} /></Col>
              <Col xs={12} md={6}><Statistic title="权益" value={session.account.equity} precision={2} /></Col>
              <Col xs={12} md={6}><Statistic title="最新 5m" value={session.checkpoint.execution_bar_count} /></Col>
            </Row>
            <section>
              <Title level={5}>平仓交易</Title>
              <DataTable columns={tradeColumns} data={session.trades ?? []} initialPageSize={6} tableClassName="cbw-paper-record-table" />
            </section>
            <section>
              <Title level={5}>成交明细</Title>
              <DataTable columns={fillColumns} data={session.fills ?? []} initialPageSize={6} tableClassName="cbw-paper-record-table" />
            </section>
            <section>
              <Title level={5}>订单</Title>
              <DataTable columns={orderColumns} data={session.orders ?? []} initialPageSize={6} tableClassName="cbw-paper-record-table" />
            </section>
            {session.warnings?.length ? (
              <section>
                <Title level={5}>警告</Title>
                <DataTable columns={warningColumns} data={session.warnings} initialPageSize={6} tableClassName="cbw-paper-record-table" />
              </section>
            ) : null}
          </Space>
        ) : null}
      </Spin>
    </Modal>
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
              strategy_name: 'ema_crossover',
              fast_period: 2,
              slow_period: 3,
              trend_fast_period: 8,
              trend_slow_period: 34,
              atr_entry_tolerance: 0.5,
              atr_stop_mult: 1.5,
              risk_reward_ratio: 2,
              qty_policy_ref: 'percent_of_cash',
              cash_allocation_pct: 95,
              risk_pct_per_trade: 0.01,
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
            <Form.Item name="strategy_name" label="策略" rules={[{ required: true }]}>
              <Segmented block options={STRATEGY_OPTIONS} />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, current) => prev.strategy_name !== current.strategy_name || prev.qty_policy_ref !== current.qty_policy_ref}
            >
              {({ getFieldValue }) => (getFieldValue('strategy_name') === 'ema_pullback_atr_v2' ? (
                <Row gutter={12}>
                  <Col span={24}>
                    <Form.Item name="qty_policy_ref" label="仓位模式" rules={[{ required: true }]}>
                      <Segmented block options={QTY_POLICY_OPTIONS} />
                    </Form.Item>
                  </Col>
                </Row>
              ) : null)}
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(prev, current) => prev.strategy_name !== current.strategy_name}>
              {({ getFieldValue }) => (getFieldValue('strategy_name') === 'ema_pullback_atr_v2' ? (
                <>
                  <Row gutter={12}>
                    <Col span={8}>
                      <Form.Item name="trend_fast_period" label="趋势快线" rules={[{ required: true }]}>
                        <InputNumber min={1} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="trend_slow_period" label="趋势慢线" rules={[{ required: true }]}>
                        <InputNumber min={1} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="atr_entry_tolerance" label="ATR 回踩容差" rules={[{ required: true }]}>
                        <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Row gutter={12}>
                    <Col span={8}>
                      <Form.Item name="atr_stop_mult" label="ATR 止损倍数" rules={[{ required: true }]}>
                        <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="risk_reward_ratio" label="风险收益比" rules={[{ required: true }]}>
                        <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="固定参数">Entry EMA 21 · ATR 14 · min ATR/price 0.2% · min stop 0.3%</Descriptions.Item>
                      </Descriptions>
                    </Col>
                  </Row>
                </>
              ) : (
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
                </Row>
              ))}
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(prev, current) => prev.qty_policy_ref !== current.qty_policy_ref || prev.strategy_name !== current.strategy_name}>
              {({ getFieldValue }) => {
                const isV2 = getFieldValue('strategy_name') === 'ema_pullback_atr_v2';
                const qtyPolicyRef = String(getFieldValue('qty_policy_ref') ?? 'percent_of_cash');
                const showRiskPct = isV2 && usesRiskPct(qtyPolicyRef);
                const showCashAllocation = !isV2 || usesCashAllocation(qtyPolicyRef);
                return (
                  <Row gutter={12}>
                    {showRiskPct ? (
                      <Col span={showCashAllocation ? 12 : 24}>
                        <Form.Item name="risk_pct_per_trade" label="单笔风险比例" rules={[{ required: true }]}>
                          <InputNumber min={0.001} max={0.99} step={0.001} style={{ width: '100%' }} />
                        </Form.Item>
                      </Col>
                    ) : null}
                    {showCashAllocation ? (
                      <Col span={showRiskPct ? 12 : 24}>
                        <Form.Item
                          name="cash_allocation_pct"
                          label={qtyPolicyRef === 'risk_pct_of_cash_allocation' ? '最多动用资金 (%)' : '资金使用比例 (%)'}
                          rules={[{ required: true }]}
                        >
                          <InputNumber min={0.01} max={100} step={1} style={{ width: '100%' }} />
                        </Form.Item>
                      </Col>
                    ) : null}
                  </Row>
                );
              }}
            </Form.Item>
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
    { header: '参数摘要', accessorKey: 'parameter_summary', cell: ({ row }) => row.original.parameter_summary || `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}` },
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
  selectedRun: shellSelectedRun,
  selectedRunId,
  setSelectedRun,
  setSelectedRunId,
  deletingRunId,
  onDeleteRun,
  onSaveResearchNote,
  onDeleteResearchNote,
  savingResearchNote,
  deletingResearchNoteId,
  onRunDrawdownProtectionExperiment,
  drawdownProtectionRunId,
}: {
  runs: RunSummaryView[];
  selectedRun: RunAnalysisView | null;
  selectedRunId: string;
  setSelectedRun: (value: RunAnalysisView | null) => void;
  setSelectedRunId: (value: string) => void;
  deletingRunId: string | null;
  onDeleteRun: (runId: string) => Promise<void>;
  onSaveResearchNote: (runId: string, values: Record<string, unknown>) => Promise<void>;
  onDeleteResearchNote: (note: ResearchNote) => Promise<void>;
  savingResearchNote: boolean;
  deletingResearchNoteId: string | null;
  onRunDrawdownProtectionExperiment: (run: RunAnalysisView) => Promise<void>;
  drawdownProtectionRunId: string | null;
}) {
  const [tradeSideFilter, setTradeSideFilter] = useState<string>('all');
  const [tradeOutcomeFilter, setTradeOutcomeFilter] = useState<'all' | 'win' | 'loss' | 'open'>('all');
  const [tradeReasonQuery, setTradeReasonQuery] = useState('');
  const [freshSelectedRun, setFreshSelectedRun] = useState<RunAnalysisView | null>(null);
  const [researchNoteForm] = Form.useForm();
  const selectedRun = freshSelectedRun?.run_id === selectedRunId
    ? freshSelectedRun
    : shellSelectedRun?.run_id === selectedRunId
      ? shellSelectedRun
      : null;

  useEffect(() => {
    if (!selectedRunId) {
      setFreshSelectedRun(null);
      return;
    }
    let cancelled = false;
    async function refreshRunDetail() {
      try {
        const payload = await loadRunDetail(selectedRunId);
        if (!cancelled) {
          setFreshSelectedRun(payload.run);
          setSelectedRun(payload.run);
        }
      } catch {
        if (!cancelled) {
          setFreshSelectedRun(null);
        }
      }
    }
    void refreshRunDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId, setSelectedRun]);

  const tradeColumns = useMemo<ColumnDef<RunAnalysisView['trade_rows'][number]>[]>(() => [
    {
      id: 'trade_id',
      header: '#',
      size: 72,
      minSize: 64,
      enableSorting: false,
      cell: ({ row }) => (
        <Tooltip title={row.original.trade_id}>
          <Space direction="vertical" size={0}>
            <Text strong>{`#${row.index + 1}`}</Text>
            <Text type="secondary">{row.original.symbol.split('/')[0]}</Text>
          </Space>
        </Tooltip>
      ),
    },
    { header: '方向', accessorKey: 'side', size: 72, minSize: 64 },
    { id: 'entry_time', header: '开仓', size: 120, minSize: 112, accessorFn: (row) => row.entry_time, cell: ({ row }) => formatDateTime(row.original.entry_time) },
    { id: 'exit_time', header: '平仓', size: 120, minSize: 112, accessorFn: (row) => row.exit_time ?? '', cell: ({ row }) => row.original.exit_time ? formatDateTime(row.original.exit_time) : '--' },
    { id: 'entry_price', header: '开仓价', accessorFn: (row) => row.entry_price, cell: ({ row }) => formatNumber(row.original.entry_price) },
    { id: 'exit_price', header: '平仓价', accessorFn: (row) => row.exit_price ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.exit_price === null ? '--' : formatNumber(row.original.exit_price) },
    { id: 'planned_stop_loss_price', header: '计划止损', accessorFn: (row) => row.planned_stop_loss_price ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.planned_stop_loss_price === null ? '--' : formatNumber(row.original.planned_stop_loss_price) },
    { id: 'planned_take_profit_price', header: '计划止盈', accessorFn: (row) => row.planned_take_profit_price ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.planned_take_profit_price === null ? '--' : formatNumber(row.original.planned_take_profit_price) },
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
  const drawdownAttributionColumns = useMemo<ColumnDef<RunDrawdownAttributionBucket>[]>(() => [
    {
      id: 'dimension',
      header: '维度',
      size: 150,
      minSize: 130,
      accessorFn: (row) => row.dimension,
      cell: ({ row }) => tradeAttributionDimensionLabel(row.original.dimension),
    },
    {
      id: 'label',
      header: '分桶',
      size: 150,
      minSize: 130,
      accessorFn: (row) => row.label,
      cell: ({ row }) => <Tag color={row.original.loss_share >= 0.25 ? 'red' : 'blue'}>{row.original.label}</Tag>,
    },
    { id: 'trade_count', header: '区间交易', size: 92, minSize: 84, accessorFn: (row) => row.trade_count },
    { id: 'loss_count', header: '亏损笔', size: 82, minSize: 74, accessorFn: (row) => row.loss_count },
    {
      id: 'loss_pnl',
      header: '亏损额',
      size: 112,
      minSize: 100,
      accessorFn: (row) => row.loss_pnl,
      cell: ({ row }) => <Text type="danger">{formatNumber(row.original.loss_pnl, 2)}</Text>,
    },
    {
      id: 'loss_share',
      header: '亏损占比',
      size: 100,
      minSize: 90,
      accessorFn: (row) => row.loss_share,
      cell: ({ row }) => <Text type={row.original.loss_share >= 0.25 ? 'danger' : undefined}>{formatPct(row.original.loss_share)}</Text>,
    },
    {
      id: 'net_pnl',
      header: '净收益',
      size: 112,
      minSize: 100,
      accessorFn: (row) => row.net_pnl,
      cell: ({ row }) => <Text type={row.original.net_pnl < 0 ? 'danger' : 'success'}>{formatNumber(row.original.net_pnl, 2)}</Text>,
    },
    {
      id: 'avg_return_pct',
      header: '均收益',
      size: 94,
      minSize: 84,
      accessorFn: (row) => row.avg_return_pct,
      cell: ({ row }) => formatPct(row.original.avg_return_pct),
    },
    {
      id: 'stop_loss_rate',
      header: '止损率',
      size: 94,
      minSize: 84,
      accessorFn: (row) => row.stop_loss_rate,
      cell: ({ row }) => formatPct(row.original.stop_loss_rate),
    },
    { id: 'early_exit_count', header: '<=3根', size: 82, minSize: 74, accessorFn: (row) => row.early_exit_count },
  ], []);
  const entryFeatureAttributionColumns = useMemo<ColumnDef<RunEntryFeatureAttributionBucket>[]>(() => [
    {
      id: 'judgement',
      header: '判断',
      size: 92,
      minSize: 82,
      accessorFn: (row) => row.judgement,
      cell: ({ row }) => {
        const judgement = runEntryFeatureJudgement(row.original);
        return <Tag color={judgement.color}>{judgement.text}</Tag>;
      },
    },
    {
      id: 'dimension',
      header: '入场前维度',
      size: 170,
      minSize: 150,
      accessorFn: (row) => row.dimension,
      cell: ({ row }) => (
        <Tooltip title={tradeAttributionDimensionHelp(row.original.dimension)}>
          <Text strong>{tradeAttributionDimensionLabel(row.original.dimension)}</Text>
        </Tooltip>
      ),
    },
    {
      id: 'label',
      header: '分桶',
      size: 150,
      minSize: 130,
      accessorFn: (row) => row.label,
      cell: ({ row }) => <Tag color={row.original.judgement === 'candidate' ? 'red' : 'blue'}>{row.original.label}</Tag>,
    },
    { id: 'drawdown_trade_count', header: '回撤段交易', size: 112, minSize: 100, accessorFn: (row) => row.drawdown_trade_count },
    { id: 'drawdown_loss_count', header: '回撤段亏损', size: 112, minSize: 100, accessorFn: (row) => row.drawdown_loss_count },
    {
      id: 'drawdown_loss_rate',
      header: '回撤段亏损率',
      size: 124,
      minSize: 112,
      accessorFn: (row) => row.drawdown_loss_rate,
      cell: ({ row }) => <Text type={row.original.drawdown_loss_rate >= 0.7 ? 'danger' : undefined}>{formatPct(row.original.drawdown_loss_rate)}</Text>,
    },
    {
      id: 'baseline_loss_rate',
      header: '非回撤亏损率',
      size: 124,
      minSize: 112,
      accessorFn: (row) => row.baseline_loss_rate ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => formatPct(row.original.baseline_loss_rate),
    },
    {
      id: 'loss_rate_delta',
      header: '亏损率差',
      size: 108,
      minSize: 98,
      accessorFn: (row) => row.loss_rate_delta ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => <Text type={(row.original.loss_rate_delta ?? 0) > 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.loss_rate_delta)}</Text>,
    },
    {
      id: 'drawdown_loss_share',
      header: '回撤亏损占比',
      size: 124,
      minSize: 112,
      accessorFn: (row) => row.drawdown_loss_share,
      cell: ({ row }) => <Text type={row.original.drawdown_loss_share >= 0.15 ? 'danger' : undefined}>{formatPct(row.original.drawdown_loss_share)}</Text>,
    },
    {
      id: 'drawdown_avg_return_pct',
      header: '回撤均收益',
      size: 112,
      minSize: 100,
      accessorFn: (row) => row.drawdown_avg_return_pct,
      cell: ({ row }) => formatPct(row.original.drawdown_avg_return_pct),
    },
    {
      id: 'baseline_avg_return_pct',
      header: '非回撤均收益',
      size: 124,
      minSize: 112,
      accessorFn: (row) => row.baseline_avg_return_pct ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => formatPct(row.original.baseline_avg_return_pct),
    },
    {
      id: 'avg_return_delta',
      header: '均收益差',
      size: 108,
      minSize: 98,
      accessorFn: (row) => row.avg_return_delta ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => <Text type={(row.original.avg_return_delta ?? 0) < 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.avg_return_delta)}</Text>,
    },
    { id: 'baseline_trade_count', header: '非回撤样本', size: 108, minSize: 96, accessorFn: (row) => row.baseline_trade_count },
  ], []);

  const tradeRows = selectedRun?.trade_rows ?? [];
  const researchNotes = selectedRun?.research_notes ?? [];
  const equityChartRows = useMemo(
    () => pickChartSamples(selectedRun?.equity_rows ?? [], 1500),
    [selectedRun],
  );
  const drawdownWindow = useMemo(
    () => findRunMaxDrawdownWindow(selectedRun?.equity_rows ?? []),
    [selectedRun],
  );
  const drawdownTrades = useMemo(() => {
    if (!drawdownWindow) {
      return [];
    }
    const peakTs = dayjs(drawdownWindow.peakTime).valueOf();
    const troughTs = dayjs(drawdownWindow.troughTime).valueOf();
    return tradeRows.filter((trade) => {
      if (!trade.exit_time) {
        return false;
      }
      const exitTs = dayjs(trade.exit_time).valueOf();
      return exitTs >= peakTs && exitTs <= troughTs;
    });
  }, [drawdownWindow, tradeRows]);
  const drawdownLossTrades = useMemo(
    () => drawdownTrades.filter((trade) => trade.net_pnl < 0),
    [drawdownTrades],
  );
  const nonDrawdownTrades = useMemo(() => {
    if (!drawdownWindow) {
      return tradeRows;
    }
    const peakTs = dayjs(drawdownWindow.peakTime).valueOf();
    const troughTs = dayjs(drawdownWindow.troughTime).valueOf();
    return tradeRows.filter((trade) => {
      if (!trade.exit_time) {
        return false;
      }
      const exitTs = dayjs(trade.exit_time).valueOf();
      return exitTs < peakTs || exitTs > troughTs;
    });
  }, [drawdownWindow, tradeRows]);
  const drawdownAttributionBuckets = useMemo(
    () => buildRunDrawdownAttributionBuckets(drawdownLossTrades, [
      'side',
      'exit_reason',
      'holding_bars',
      'pre_entry_momentum_3_pct',
      'pre_entry_momentum_5_pct',
      'pre_entry_consecutive_move',
      'trend_gap_atr',
      'entry_distance_atr',
      'local_range_position_20',
      'breakout_wick_atr',
      'range_chop_score_20',
      'path_no_favorable_3',
    ]),
    [drawdownLossTrades],
  );
  const entryFeatureAttributionBuckets = useMemo(
    () => buildRunEntryFeatureAttributionBuckets(drawdownTrades, nonDrawdownTrades, [
      'side',
      'pre_entry_momentum_3_pct',
      'pre_entry_momentum_5_pct',
      'pre_entry_consecutive_move',
      'trend_gap_atr',
      'entry_distance_atr',
      'local_range_position_20',
      'breakout_wick_atr',
      'range_chop_score_20',
    ]),
    [drawdownTrades, nonDrawdownTrades],
  );
  const drawdownLossTotal = useMemo(
    () => drawdownLossTrades.reduce((sum, trade) => sum + Math.abs(trade.net_pnl), 0),
    [drawdownLossTrades],
  );
  const drawdownFeatureCoverage = useMemo(() => {
    const featureKeys = [
      'pre_entry_momentum_3_pct',
      'pre_entry_momentum_5_pct',
      'pre_entry_consecutive_move',
      'trend_gap_atr',
      'entry_distance_atr',
      'local_range_position_20',
      'breakout_wick_atr',
      'range_chop_score_20',
    ];
    return featureKeys.map((key) => ({
      key,
      label: tradeAttributionDimensionLabel(key),
      count: drawdownLossTrades.filter((trade) => numericTradeMeta(trade, key) !== null).length,
    }));
  }, [drawdownLossTrades]);
  const drawdownFeatureCoverageText = drawdownFeatureCoverage
    .map((item) => `${item.label} ${item.count}/${drawdownLossTrades.length}`)
    .join('；');
  const drawdownFeatureCoverageTotal = drawdownFeatureCoverage.reduce((sum, item) => sum + item.count, 0);
  useEffect(() => {
    if (!selectedRun || selectedRun.run_id !== selectedRunId || drawdownLossTrades.length === 0 || drawdownFeatureCoverageTotal > 0) {
      return;
    }
    let cancelled = false;
    async function refreshRunDetail() {
      try {
        const payload = await loadRunDetail(selectedRunId);
        if (!cancelled) {
          setSelectedRun(payload.run);
        }
      } catch {
        // Keep the visible stale run; the outer shell will show API errors on regular loads.
      }
    }
    void refreshRunDetail();
    return () => {
      cancelled = true;
    };
  }, [drawdownFeatureCoverageTotal, drawdownLossTrades.length, selectedRun, selectedRunId, setSelectedRun]);
  const drawdownNetPnl = useMemo(
    () => drawdownTrades.reduce((sum, trade) => sum + trade.net_pnl, 0),
    [drawdownTrades],
  );
  const topDrawdownBucket = drawdownAttributionBuckets[0] ?? null;
  const entryFeatureConclusion = buildRunEntryFeatureConclusion(entryFeatureAttributionBuckets);
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
  const runType = String(selectedRun.manifest.resolved_config_json.run_type ?? '');
  const parentRunId = String(selectedRun.manifest.resolved_config_json.parent_run_id ?? '');
  const strategyTimeframe = String(selectedRun.manifest.resolved_config_json.strategy_timeframe ?? '');
  const executionTimeframe = String(selectedRun.manifest.resolved_config_json.execution_timeframe ?? '');
  const validationSummary = selectedRun.validation;
  const latestResearchNote = researchNotes[0] ?? null;
  const aggregatedLabels = Array.from(new Set(researchNotes.flatMap((note) => note.labels ?? [])));
  const selectedRunSummary = runs.find((run) => run.run_id === selectedRun.run_id);
  const selectedRunIsTracked = researchNotes.some((note) => (
    note.labels.includes('tracking')
    && note.labels.includes('frozen_run')
    && note.decision_status !== 'rejected'
    && note.decision_status !== 'archived'
  ));
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
              <Button
                loading={savingResearchNote}
                disabled={selectedRunIsTracked}
                onClick={() => void onSaveResearchNote(selectedRun.run_id, buildFrozenAnalysisNoteValues(selectedRun, selectedRunSummary))}
              >
                {selectedRunIsTracked ? '已追踪' : '冻结追踪'}
              </Button>
              <Button
                loading={drawdownProtectionRunId === selectedRun.run_id}
                onClick={() => void onRunDrawdownProtectionExperiment(selectedRun)}
              >
                回撤保护实验
              </Button>
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

      <Col span={24}>
        <Card title="最大回撤归因（单 Run）">
          {drawdownWindow ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Alert
                type={topDrawdownBucket && topDrawdownBucket.loss_share >= 0.25 ? 'warning' : 'info'}
                showIcon
                message={topDrawdownBucket
                  ? `${tradeAttributionDimensionLabel(topDrawdownBucket.dimension)} ${topDrawdownBucket.label} 是本次最大回撤段的主要亏损来源`
                  : '最大回撤段没有匹配到已平仓亏损交易'}
                description={topDrawdownBucket
                  ? `峰值到谷值期间，该分桶贡献 ${formatPct(topDrawdownBucket.loss_share)} 的区间亏损，止损率 ${formatPct(topDrawdownBucket.stop_loss_rate)}。这是单 run 路径归因，只说明这次回撤怎么形成。`
                  : '可能是浮亏、未平仓仓位或权益曲线点位与交易平仓时间错位导致。'}
              />
              <Alert
                type={drawdownFeatureCoverage.every((item) => item.count > 0) ? 'success' : 'warning'}
                showIcon
                message="回撤段入场特征覆盖率"
                description={drawdownFeatureCoverageText || '当前回撤段没有亏损交易可检查。'}
              />
              <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                <Descriptions.Item label="峰值时间">{formatDateTime(drawdownWindow.peakTime)}</Descriptions.Item>
                <Descriptions.Item label="谷值时间">{formatDateTime(drawdownWindow.troughTime)}</Descriptions.Item>
                <Descriptions.Item label="最大回撤">{formatPct(drawdownWindow.maxDrawdown)}</Descriptions.Item>
                <Descriptions.Item label="峰值权益">{formatNumber(drawdownWindow.peakEquity, 2)}</Descriptions.Item>
                <Descriptions.Item label="谷值权益">{formatNumber(drawdownWindow.troughEquity, 2)}</Descriptions.Item>
                <Descriptions.Item label="回撤金额">{formatNumber(drawdownWindow.drawdownAmount, 2)}</Descriptions.Item>
                <Descriptions.Item label="区间交易">{drawdownTrades.length}</Descriptions.Item>
                <Descriptions.Item label="区间亏损交易">{drawdownLossTrades.length}</Descriptions.Item>
                <Descriptions.Item label="区间净收益">
                  <Text type={drawdownNetPnl < 0 ? 'danger' : 'success'}>{formatNumber(drawdownNetPnl, 2)}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="区间亏损额">{formatNumber(drawdownLossTotal, 2)}</Descriptions.Item>
                <Descriptions.Item label="恢复时间">
                  {drawdownWindow.recoveryTime ? formatDateTime(drawdownWindow.recoveryTime) : '未恢复'}
                </Descriptions.Item>
                <Descriptions.Item label="谷值后恢复K数">
                  {drawdownWindow.recoveryBars === null ? '--' : drawdownWindow.recoveryBars}
                </Descriptions.Item>
              </Descriptions>
              {drawdownAttributionBuckets.length ? (
                <DataTable
                  columns={drawdownAttributionColumns}
                  data={drawdownAttributionBuckets}
                  tableClassName="cbw-parameter-group-table"
                  initialPageSize={8}
                  pageSizeOptions={[8, 12, 24]}
                  initialSorting={[{ id: 'loss_share', desc: true }]}
                />
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message="没有可分桶的区间亏损交易"
                  description="如果权益回撤主要来自未平仓浮亏，需要后续补充持仓级浮亏归因。"
                />
              )}
            </Space>
          ) : (
            <Alert type="info" showIcon message="当前权益曲线没有形成有效回撤窗口" />
          )}
        </Card>
      </Col>

      <Col span={24}>
        <Card title="入场前特征归因（最大回撤段）">
          {drawdownWindow ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Alert
                type={entryFeatureConclusion.type}
                showIcon
                message={entryFeatureConclusion.message}
                description={entryFeatureConclusion.description}
              />
              <Alert
                type="info"
                showIcon
                message="这张表只看入场前可见特征"
                description={`对比峰值到谷值期间的交易与非回撤段交易。回撤段样本 ${drawdownTrades.length} 笔，非回撤段样本 ${nonDrawdownTrades.length} 笔；候选行适合转成过滤实验。`}
              />
              {entryFeatureAttributionBuckets.length ? (
                <DataTable
                  columns={entryFeatureAttributionColumns}
                  data={entryFeatureAttributionBuckets}
                  tableClassName="cbw-parameter-group-table"
                  initialPageSize={8}
                  pageSizeOptions={[8, 12, 24]}
                  initialSorting={[{ id: 'drawdown_loss_share', desc: true }]}
                />
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message="没有形成可对比的入场前分桶"
                  description="通常是交易样本太少，或当前 run 的交易没有记录足够的 entry_signal_meta_json。"
                />
              )}
            </Space>
          ) : (
            <Alert type="info" showIcon message="当前权益曲线没有形成有效回撤窗口" />
          )}
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title="运行上下文">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="标的 / 周期">{`${selectedRun.symbol} · ${selectedRun.timeframe.toUpperCase()}`}</Descriptions.Item>
            <Descriptions.Item label="数据快照">{selectedRun.dataset_snapshot_id}</Descriptions.Item>
            {runType ? <Descriptions.Item label="Run 类型">{runType}</Descriptions.Item> : null}
            {parentRunId ? <Descriptions.Item label="父 Run">{parentRunId}</Descriptions.Item> : null}
            {strategyTimeframe ? <Descriptions.Item label="信号周期">{strategyTimeframe.toUpperCase()}</Descriptions.Item> : null}
            {executionTimeframe ? <Descriptions.Item label="执行周期">{executionTimeframe.toUpperCase()}</Descriptions.Item> : null}
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
        <Card
          title="研究记录"
          extra={latestResearchNote ? (
            <Tag color={decisionStatusColor(latestResearchNote.decision_status)}>
              {decisionStatusText(latestResearchNote.decision_status)}
            </Tag>
          ) : null}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
              <Space wrap size={[8, 8]}>
                <Tag>备注 {researchNotes.length}</Tag>
                {aggregatedLabels.length ? aggregatedLabels.map((label) => (
                  <Tag color={label === 'excluded' ? 'red' : label === 'baseline' ? 'gold' : 'blue'} key={label}>
                    {researchLabelText(label)}
                  </Tag>
                )) : <Text type="secondary">无标签</Text>}
              </Space>
              <Text type="secondary">
                {latestResearchNote ? `最近更新 ${formatDateTime(latestResearchNote.created_at)}` : '暂无记录'}
              </Text>
            </Flex>
            <Collapse
              ghost
              items={[{
                key: 'research-note-form',
                label: '备注与标记',
                children: (
                  <Row gutter={[16, 16]}>
                    <Col span={24}>
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
                                  <Popconfirm
                                    title="删除这条研究备注？"
                                    description="删除后，这条备注带来的标签和状态会一起移除。"
                                    okText="删除"
                                    cancelText="取消"
                                    okButtonProps={{ danger: true, loading: deletingResearchNoteId === note.note_id }}
                                    onConfirm={() => void onDeleteResearchNote(note)}
                                  >
                                    <Button size="small" danger loading={deletingResearchNoteId === note.note_id}>
                                      删除
                                    </Button>
                                  </Popconfirm>
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
                ),
              }]}
            />
          </Space>
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
                placeholder="搜索原因 / 标的 / ID"
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
  parameterResearch,
  researchWorkflow,
  researchNotes,
  manualLabelsByRunId,
  fastRows,
  slowRows,
  parameterLabLoaded,
  onEnsureParameterLab,
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
  neighborhoodRunId,
  onSubmitExperiment,
  onRunTrendNeighborhood,
  onRunDrawdownProtectionExperiment,
  onRunRiskMatrix,
  onRunFilterExperiment,
  onRunExecutionFilterExperiment,
  drawdownProtectionRunId,
  drawdownProtectionCandidateId,
  drawdownProtectionProgressByCandidateId,
  riskMatrixCandidateId,
  riskMatrixProgressByCandidateId,
  filterExperimentCandidateId,
  filterExperimentProgressByCandidateId,
  onLoadParameterRows,
  onOpenRun,
  onDeleteRun,
  onDeleteExperiment,
  onDeleteBatch,
  onSaveResearchNote,
  savingResearchNote,
  onResearchWorkflowOptimisticChange,
  onRefreshResearchWorkflow,
  onRefreshShell,
  onRefreshExperiments,
}: {
  datasets: DatasetSnapshotView[];
  rows: ParameterLabRow[];
  allRows: ParameterLabRow[];
  parameterResearch: ParameterResearchWorkspace | null;
  researchWorkflow: ResearchWorkflow | null;
  researchNotes: ResearchNote[];
  manualLabelsByRunId: Map<string, string[]>;
  fastRows: SensitivityRow[];
  slowRows: SensitivityRow[];
  parameterLabLoaded: boolean;
  onEnsureParameterLab: () => Promise<void>;
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
  neighborhoodRunId: string | null;
  onSubmitExperiment: (values: Record<string, unknown>) => Promise<void>;
  onRunTrendNeighborhood: (row: ParameterLabRow) => Promise<void>;
  onRunDrawdownProtectionExperiment: (rowOrRunId: ParameterLabRow | string, progressKey?: string) => Promise<void>;
  onRunRiskMatrix: (candidate: ResearchCandidateView) => Promise<void>;
  onRunFilterExperiment: (candidate: ResearchCandidateView, profile?: FilterExperimentProfile) => Promise<void>;
  onRunExecutionFilterExperiment: (candidate: StableCandidateView) => Promise<string | null>;
  drawdownProtectionRunId: string | null;
  drawdownProtectionCandidateId: string | null;
  drawdownProtectionProgressByCandidateId: Record<string, FilterExperimentProgress>;
  riskMatrixCandidateId: string | null;
  riskMatrixProgressByCandidateId: Record<string, RiskMatrixProgress>;
  filterExperimentCandidateId: string | null;
  filterExperimentProgressByCandidateId: Record<string, FilterExperimentProgress>;
  onLoadParameterRows: () => Promise<ParameterLabRow[]>;
  onOpenRun: (runId: string) => void;
  onDeleteRun: (runId: string) => Promise<void>;
  onDeleteExperiment: (experimentId: string) => Promise<void>;
  onDeleteBatch: (batchId: string) => Promise<void>;
  onSaveResearchNote: (targetType: string, targetId: string, values: Record<string, unknown>) => Promise<void>;
  savingResearchNote: boolean;
  onResearchWorkflowOptimisticChange: (updater: (current: ResearchWorkflow | null) => ResearchWorkflow | null) => void;
  onRefreshResearchWorkflow: () => Promise<void>;
  onRefreshShell: () => Promise<void>;
  onRefreshExperiments: () => Promise<void>;
  }) {
  const { message } = AntdApp.useApp();
  const experimentSearchType = Form.useWatch('search_type', experimentForm) as string | undefined;
  const experimentStrategyName = (Form.useWatch('strategy_name', experimentForm) as string | undefined) ?? 'ema_crossover';
  const validationSplitMode = Form.useWatch('validation_split_mode', experimentForm) as string | undefined;
  const initialScreeningViewState = useMemo(() => loadScreeningViewState(), []);
  const [workspaceMode, setWorkspaceMode] = useState<ParameterWorkspaceMode>('screening');
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
  const [autoLabelFilter, setAutoLabelFilter] = useState<string[]>([]);
  const [minScoreFilter, setMinScoreFilter] = useState<number | null>(null);
  const [minConfidenceFilter, setMinConfidenceFilter] = useState<number | null>(null);
  const [maxDrawdownFilter, setMaxDrawdownFilter] = useState<number | null>(null);
  const [minReturnDrawdownFilter, setMinReturnDrawdownFilter] = useState<number | null>(null);
  const [topNFilter, setTopNFilter] = useState<number | null>(null);
  const [screeningLabelFilter, setScreeningLabelFilter] = useState<string[]>(initialScreeningViewState.labelFilter);
  const [screeningStrategyFilter, setScreeningStrategyFilter] = useState<string | null>(initialScreeningViewState.strategyFilter);
  const [screeningSymbolFilter, setScreeningSymbolFilter] = useState<string | null>(initialScreeningViewState.symbolFilter);
  const [screeningMinScoreFilter, setScreeningMinScoreFilter] = useState<number | null>(initialScreeningViewState.minScoreFilter);
  const [screeningMinOosReturnFilter, setScreeningMinOosReturnFilter] = useState<number | null>(initialScreeningViewState.minOosReturnFilter);
  const [screeningMinIsExcessReturnFilter, setScreeningMinIsExcessReturnFilter] = useState<number | null>(initialScreeningViewState.minIsExcessReturnFilter);
  const [screeningMaxGapFilter, setScreeningMaxGapFilter] = useState<number | null>(initialScreeningViewState.maxGapFilter);
  const [screeningMaxDrawdownFilter, setScreeningMaxDrawdownFilter] = useState<number | null>(initialScreeningViewState.maxDrawdownFilter);
  const [screeningMinProfitFactorFilter, setScreeningMinProfitFactorFilter] = useState<number | null>(initialScreeningViewState.minProfitFactorFilter);
  const [screeningMinTradeCountFilter, setScreeningMinTradeCountFilter] = useState<number | null>(initialScreeningViewState.minTradeCountFilter);
  const [screeningSorting, setScreeningSorting] = useState<SortingState>(initialScreeningViewState.sorting);
  const [experimentMinResearchScoreFilter, setExperimentMinResearchScoreFilter] = useState<number | null>(null);
  const [experimentMinOosReturnFilter, setExperimentMinOosReturnFilter] = useState<number | null>(null);
  const [experimentMinTotalReturnFilter, setExperimentMinTotalReturnFilter] = useState<number | null>(null);
  const [experimentMinProfitFactorFilter, setExperimentMinProfitFactorFilter] = useState<number | null>(null);
  const [experimentMaxDrawdownFilter, setExperimentMaxDrawdownFilter] = useState<number | null>(null);
  const [experimentMinTradeCountFilter, setExperimentMinTradeCountFilter] = useState<number | null>(null);
  const [selectedResearchSubjectKey, setSelectedResearchSubjectKey] = useState<string | null>(null);
  const [researchClassificationFilter, setResearchClassificationFilter] = useState<string[]>([]);
  const [researchQtyPolicyFilter, setResearchQtyPolicyFilter] = useState<string | null>(null);
  const [selectedParameterGroupKey, setSelectedParameterGroupKey] = useState<string | null>(null);
  const [selectedParameterGroupDetail, setSelectedParameterGroupDetail] = useState<ParameterGroupDetail | null>(null);
  const [parameterGroupDetailLoading, setParameterGroupDetailLoading] = useState(false);
  const [riskCompareGroupKey, setRiskCompareGroupKey] = useState<string | null>(null);
  const [executionVerificationCandidateId, setExecutionVerificationCandidateId] = useState<string | null>(null);
  const [filterResultsCandidateId, setFilterResultsCandidateId] = useState<string | null>(null);
  const [filterResults, setFilterResults] = useState<ResearchCandidateFilterResults | null>(null);
  const [filterResultsLoading, setFilterResultsLoading] = useState(false);
  const [tradeAttributionCandidateId, setTradeAttributionCandidateId] = useState<string | null>(null);
  const [tradeAttribution, setTradeAttribution] = useState<TradeAttributionView | null>(null);
  const [tradeAttributionLoading, setTradeAttributionLoading] = useState(false);
  const [decisionTarget, setDecisionTarget] = useState<{ targetType: string; targetId: string; title: string } | null>(null);
  const [neighborhoodSourceRunId, setNeighborhoodSourceRunId] = useState<string | null>(null);
  const [decisionForm] = Form.useForm();
  useEffect(() => {
    const state: ScreeningViewState = {
      labelFilter: screeningLabelFilter,
      strategyFilter: screeningStrategyFilter,
      symbolFilter: screeningSymbolFilter,
      minScoreFilter: screeningMinScoreFilter,
      minOosReturnFilter: screeningMinOosReturnFilter,
      minIsExcessReturnFilter: screeningMinIsExcessReturnFilter,
      maxGapFilter: screeningMaxGapFilter,
      maxDrawdownFilter: screeningMaxDrawdownFilter,
      minProfitFactorFilter: screeningMinProfitFactorFilter,
      minTradeCountFilter: screeningMinTradeCountFilter,
      sorting: screeningSorting,
    };
    window.localStorage.setItem(SCREENING_VIEW_STATE_STORAGE_KEY, JSON.stringify(state));
  }, [
    screeningLabelFilter,
    screeningMaxDrawdownFilter,
    screeningMaxGapFilter,
    screeningMinOosReturnFilter,
    screeningMinIsExcessReturnFilter,
    screeningMinProfitFactorFilter,
    screeningMinScoreFilter,
    screeningMinTradeCountFilter,
    screeningSorting,
    screeningStrategyFilter,
    screeningSymbolFilter,
  ]);
  useEffect(() => {
    if (workspaceMode === 'launch' || workspaceMode === 'screening' || workspaceMode === 'research' || workspaceMode === 'stable' || parameterLabLoaded) {
      return;
    }
    void onEnsureParameterLab();
  }, [onEnsureParameterLab, parameterLabLoaded, workspaceMode]);
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
    if (!experimentForm.getFieldValue('search_type')) {
      experimentForm.setFieldValue('search_type', 'grid');
    }
    if (!experimentForm.getFieldValue('strategy_name')) {
      experimentForm.setFieldValue('strategy_name', 'ema_crossover');
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
    if (!experimentForm.getFieldValue('trend_fast_periods')) {
      experimentForm.setFieldValue('trend_fast_periods', '2,3,5,8');
    }
    if (!experimentForm.getFieldValue('trend_slow_periods')) {
      experimentForm.setFieldValue('trend_slow_periods', '13,21,34');
    }
    if (!experimentForm.getFieldValue('atr_entry_tolerances')) {
      experimentForm.setFieldValue('atr_entry_tolerances', '0.5,1.0');
    }
    if (!experimentForm.getFieldValue('atr_stop_mults')) {
      experimentForm.setFieldValue('atr_stop_mults', '1.5,2.0');
    }
    if (!experimentForm.getFieldValue('risk_reward_ratios')) {
      experimentForm.setFieldValue('risk_reward_ratios', '1.5,2.0');
    }
    if (experimentForm.getFieldValue('cash_allocation_pct') === undefined) {
      experimentForm.setFieldValue('cash_allocation_pct', 95);
    }
    if (experimentForm.getFieldValue('risk_pct_per_trade') === undefined) {
      experimentForm.setFieldValue('risk_pct_per_trade', 0.01);
    }
    if (!experimentForm.getFieldValue('qty_policy_ref')) {
      experimentForm.setFieldValue('qty_policy_ref', 'percent_of_cash');
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
  const recentBatches = useMemo(
    () => [...batches]
      .sort((left, right) => dayjs(right.created_at).valueOf() - dayjs(left.created_at).valueOf())
      .slice(0, 5),
    [batches],
  );
  const researchSubjects = parameterResearch?.subjects ?? [];
  const researchParameterGroups = parameterResearch?.parameter_groups ?? [];
  const screeningPoolRuns = researchWorkflow?.screening_pool.runs ?? [];
  const researchPoolCandidates = researchWorkflow?.research_pool.candidates ?? [];
  const stablePoolCandidates = researchWorkflow?.stable_pool.candidates ?? [];
  const screeningLabelOptions = useMemo(
    () => Array.from(new Set(screeningPoolRuns.flatMap((run) => [...run.auto_labels, ...run.manual_labels]))).sort(),
    [screeningPoolRuns],
  );
  const screeningStrategyOptions = useMemo(
    () => Array.from(new Set(screeningPoolRuns.map((run) => run.strategy_name))).sort(),
    [screeningPoolRuns],
  );
  const screeningSymbolOptions = useMemo(
    () => Array.from(new Set(screeningPoolRuns.map((run) => run.symbol))).sort(),
    [screeningPoolRuns],
  );

  useEffect(() => {
    if (!researchSubjects.length) {
      if (selectedResearchSubjectKey !== null) {
        setSelectedResearchSubjectKey(null);
      }
      return;
    }
    if (!selectedResearchSubjectKey || !researchSubjects.some((subject) => subject.subject_key === selectedResearchSubjectKey)) {
      setSelectedResearchSubjectKey(researchSubjects[0].subject_key);
    }
  }, [researchSubjects, selectedResearchSubjectKey]);

  const selectedResearchSubject = useMemo(
    () => researchSubjects.find((subject) => subject.subject_key === selectedResearchSubjectKey) ?? null,
    [researchSubjects, selectedResearchSubjectKey],
  );
  const filteredResearchGroups = useMemo(() => {
    const query = parameterQuery.trim().toLowerCase();
    return researchParameterGroups
      .filter((group) => (
        (!selectedResearchSubjectKey || group.subject_key === selectedResearchSubjectKey)
        && (!researchClassificationFilter.length || researchClassificationFilter.includes(group.classification))
        && (!researchQtyPolicyFilter || group.qty_policy_ref === researchQtyPolicyFilter)
        && (!query || [
          group.group_key,
          group.parameter_summary,
          group.strategy_name,
          group.symbol,
          group.timeframe,
          group.classification,
        ].join(' ').toLowerCase().includes(query))
      ))
      .sort((left, right) => {
        if (right.research_score !== left.research_score) {
          return right.research_score - left.research_score;
        }
        return (right.avg_oos_total_return ?? -10000) - (left.avg_oos_total_return ?? -10000);
      });
  }, [parameterQuery, researchClassificationFilter, researchParameterGroups, researchQtyPolicyFilter, selectedResearchSubjectKey]);
  const filteredScreeningRuns = useMemo(() => {
    const query = parameterQuery.trim().toLowerCase();
    return screeningPoolRuns.filter((run) => (
      (!query || [
        run.run_id,
        run.dataset_snapshot_id,
        run.symbol,
        run.strategy_name,
        run.timeframe,
        run.parameter_summary,
        ...run.auto_labels,
        ...run.manual_labels,
      ].join(' ').toLowerCase().includes(query))
      && run.pool_status !== 'excluded'
      && run.pool_status !== 'research_pool'
      && run.pool_status !== 'stable_pool'
      && (!screeningLabelFilter.length || screeningLabelFilter.every((label) => [...run.auto_labels, ...run.manual_labels].includes(label)))
      && (!screeningStrategyFilter || run.strategy_name === screeningStrategyFilter)
      && (!screeningSymbolFilter || run.symbol === screeningSymbolFilter)
      && (screeningMinScoreFilter === null || run.score >= screeningMinScoreFilter)
      && (screeningMinOosReturnFilter === null || (run.oos_total_return !== null && run.oos_total_return >= screeningMinOosReturnFilter / 100))
      && (screeningMinIsExcessReturnFilter === null || (run.is_excess_return !== null && run.is_excess_return >= screeningMinIsExcessReturnFilter / 100))
      && (screeningMaxGapFilter === null || (run.is_oos_gap !== null && Math.abs(run.is_oos_gap) <= screeningMaxGapFilter / 100))
      && (screeningMaxDrawdownFilter === null || Math.abs(run.max_drawdown) <= screeningMaxDrawdownFilter / 100)
      && (screeningMinProfitFactorFilter === null || (run.profit_factor !== null && run.profit_factor >= screeningMinProfitFactorFilter))
      && (screeningMinTradeCountFilter === null || run.trade_count >= screeningMinTradeCountFilter)
    ));
  }, [
    parameterQuery,
    screeningLabelFilter,
    screeningMaxDrawdownFilter,
    screeningMaxGapFilter,
    screeningMinOosReturnFilter,
    screeningMinIsExcessReturnFilter,
    screeningMinProfitFactorFilter,
    screeningMinScoreFilter,
    screeningMinTradeCountFilter,
    screeningPoolRuns,
    screeningStrategyFilter,
    screeningSymbolFilter,
  ]);
  const screeningRiskProfile = useMemo(
    () => buildScreeningRiskProfile(screeningPoolRuns.filter((run) => run.pool_status !== 'excluded')),
    [screeningPoolRuns],
  );
  const filteredResearchPoolCandidates = useMemo(() => {
    const query = parameterQuery.trim().toLowerCase();
    return researchPoolCandidates.filter((candidate) => (
      !query || [
        candidate.candidate_id,
        candidate.strategy_name,
        candidate.symbol,
        candidate.timeframe,
        candidate.status,
        candidate.recommendation,
      ].join(' ').toLowerCase().includes(query)
    ));
  }, [parameterQuery, researchPoolCandidates]);
  const filteredStablePoolCandidates = useMemo(() => {
    const query = parameterQuery.trim().toLowerCase();
    return stablePoolCandidates.filter((candidate) => (
      !query || [
        candidate.stable_candidate_id,
        candidate.strategy_name,
        candidate.symbol,
        candidate.timeframe,
        candidate.status,
        candidate.final_recommendation,
      ].join(' ').toLowerCase().includes(query)
    ));
  }, [parameterQuery, stablePoolCandidates]);
  const researchGroupCommonKeys = useMemo(
    () => commonParameterPointKeys(filteredResearchGroups),
    [filteredResearchGroups],
  );
  const researchGroupCommonPoints = useMemo(() => {
    if (!filteredResearchGroups.length) {
      return [];
    }
    return parameterGroupPoints(filteredResearchGroups[0])
      .filter((point) => researchGroupCommonKeys.has(point.key));
  }, [filteredResearchGroups, researchGroupCommonKeys]);
  const researchGroupTitle = useMemo(() => {
    if (!selectedResearchSubject) {
      return {
        title: '参数组排行榜',
        common: '共同条件：--',
      };
    }
    const base = [
      selectedResearchSubject.strategy_name,
      selectedResearchSubject.symbol,
      selectedResearchSubject.timeframe.toUpperCase(),
      selectedResearchSubject.validation_split_id,
    ].join(' · ');
    const common = researchGroupCommonPoints.length
      ? researchGroupCommonPoints.map((point) => `${point.label}${point.value}`).join(' · ')
      : '无共同固定参数';
    return {
      title: `参数组排行榜 · ${base}`,
      common: `共同条件：${common}`,
    };
  }, [researchGroupCommonPoints, selectedResearchSubject]);
  const recommendedResearchGroups = useMemo(() => {
    return filteredResearchGroups
      .filter((group) => (
        group.classification !== 'excluded'
        && (group.avg_oos_total_return ?? -1) > 0
        && (group.oos_positive_ratio ?? 0) >= 0.6
        && group.min_trade_count >= 200
        && (group.avg_profit_factor ?? 0) >= 1.05
        && group.worst_max_drawdown <= 0.5
        && (group.neighbor_stability_score ?? 0) >= 0.5
      ))
      .sort((left, right) => {
        if (right.research_score !== left.research_score) {
          return right.research_score - left.research_score;
        }
        const leftEfficiency = (left.avg_oos_total_return ?? left.avg_total_return) / Math.max(left.worst_max_drawdown, 0.01);
        const rightEfficiency = (right.avg_oos_total_return ?? right.avg_total_return) / Math.max(right.worst_max_drawdown, 0.01);
        if (rightEfficiency !== leftEfficiency) {
          return rightEfficiency - leftEfficiency;
        }
        if ((left.avg_gap ?? Number.POSITIVE_INFINITY) !== (right.avg_gap ?? Number.POSITIVE_INFINITY)) {
          return (left.avg_gap ?? Number.POSITIVE_INFINITY) - (right.avg_gap ?? Number.POSITIVE_INFINITY);
        }
        return (right.avg_profit_factor ?? 0) - (left.avg_profit_factor ?? 0);
      })
      .slice(0, 3);
  }, [filteredResearchGroups]);
  const researchConclusionBuckets = useMemo(
    () => buildResearchConclusionBuckets(researchParameterGroups),
    [researchParameterGroups],
  );
  const riskCompareSourceGroup = useMemo(
    () => researchParameterGroups.find((group) => group.group_key === riskCompareGroupKey) ?? null,
    [researchParameterGroups, riskCompareGroupKey],
  );
  const riskCompareGroups = useMemo(() => {
    if (!riskCompareSourceGroup) {
      return [];
    }
    const compareKey = parameterGroupEntryCompareKey(riskCompareSourceGroup);
    return researchParameterGroups
      .filter((group) => parameterGroupEntryCompareKey(group) === compareKey)
      .sort((left, right) => {
        const leftScore = (left.avg_oos_total_return ?? left.avg_total_return) / Math.max(left.worst_max_drawdown, 0.01);
        const rightScore = (right.avg_oos_total_return ?? right.avg_total_return) / Math.max(right.worst_max_drawdown, 0.01);
        if (rightScore !== leftScore) {
          return rightScore - leftScore;
        }
        return (right.avg_oos_total_return ?? -10_000) - (left.avg_oos_total_return ?? -10_000);
      });
  }, [researchParameterGroups, riskCompareSourceGroup]);
  const riskCompareEntryText = useMemo(() => {
    if (!riskCompareSourceGroup) {
      return '--';
    }
    return parameterGroupEntryPoints(riskCompareSourceGroup)
      .map((point) => `${point.label}${point.value}`)
      .join(' · ');
  }, [riskCompareSourceGroup]);

  useEffect(() => {
    if (selectedExperimentId === ALL_EXPERIMENTS) {
      return;
    }
    if (!visibleExperiments.some((experiment) => experiment.experiment_id === selectedExperimentId)) {
      setSelectedExperimentId(ALL_EXPERIMENTS);
    }
  }, [selectedExperimentId, setSelectedExperimentId, visibleExperiments]);
  useEffect(() => {
    if (!selectedParameterGroupKey) {
      setSelectedParameterGroupDetail(null);
      return;
    }
    let cancelled = false;
    setParameterGroupDetailLoading(true);
    void loadParameterGroupDetail(selectedParameterGroupKey)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setSelectedParameterGroupDetail(payload.parameter_group);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          message.error(loadError instanceof Error ? loadError.message : '参数组详情加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setParameterGroupDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [message, selectedParameterGroupKey]);
  useEffect(() => {
    if (!filterResultsCandidateId) {
      setFilterResults(null);
      return;
    }
    let cancelled = false;
    setFilterResultsLoading(true);
    void loadResearchCandidateFilterResults(filterResultsCandidateId)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setFilterResults(payload.filter_results);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          const localResults = buildLocalResearchCandidateFilterResults(
            filterResultsCandidateId,
            researchParameterGroups,
            allRows,
          );
          if (localResults) {
            setFilterResults(localResults);
            return;
          }
          message.error(loadError instanceof Error ? loadError.message : '过滤结果加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setFilterResultsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [allRows, filterResultsCandidateId, message, researchParameterGroups]);
  useEffect(() => {
    if (!tradeAttributionCandidateId) {
      setTradeAttribution(null);
      return;
    }
    let cancelled = false;
    setTradeAttributionLoading(true);
    void loadResearchCandidateTradeAttribution(tradeAttributionCandidateId)
      .then((payload) => {
        if (!cancelled) {
          setTradeAttribution(payload.trade_attribution);
        }
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          message.error(loadError instanceof Error ? loadError.message : '交易归因加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTradeAttributionLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [message, tradeAttributionCandidateId]);
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
  useEffect(() => {
    if (selectedBatchId === ALL_BATCHES) {
      return;
    }
    if (batchDecisionLabelFilter.length) {
      setBatchDecisionLabelFilter([]);
    }
    if (batchDecisionStatusFilter.length) {
      setBatchDecisionStatusFilter([]);
    }
  }, [batchDecisionLabelFilter.length, batchDecisionStatusFilter.length, selectedBatchId]);
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
  const availableBatchStatuses = useMemo(
    () => Array.from(new Set(batches.map((batch) => batch.status).filter(Boolean))),
    [batches],
  );
  const filteredBatches = useMemo(() => {
    if (!batchDecisionLabelFilter.length && !batchDecisionStatusFilter.length) {
      return batches;
    }
    return batches.filter((batch) => {
      const notes = batchDecisionNotesByBatchId.get(batch.batch_id) ?? [];
      const labels = Array.from(new Set(notes.flatMap((note) => note.labels ?? [])));
      return (
        (!batchDecisionLabelFilter.length || batchDecisionLabelFilter.some((label) => labels.includes(label)))
        && (!batchDecisionStatusFilter.length || batchDecisionStatusFilter.includes(batch.status))
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
  const batchGroupLabelsByKey = useMemo(() => {
    const labelMap = new Map<string, AutoLabelInfo[]>();
    if (!selectedBatchDetail) {
      return labelMap;
    }
    const applyLabel = (
      groups: Array<{ strategy_name?: string; parameter_summary?: string; signal_filter_summary?: string | null; fast_period?: number | null; slow_period?: number | null; leverage?: number | null; reason: string }>,
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
    () => RESEARCH_LABEL_OPTIONS.map((option) => option.value),
    [],
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
    const manualStatuses = manualNotes.length
      ? Array.from(new Set(manualNotes.map((note) => note.decision_status ?? 'candidate')))
      : ['candidate'];
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

  async function addRunToResearchPool(run: ScreeningRunView | ParameterLabRow) {
    await postResearchPool({
      source_run_id: run.run_id,
      note: `加入研究池：${run.parameter_summary}`,
    });
    onResearchWorkflowOptimisticChange((current) => markRunAddedToResearchPool(current, run));
    void onRefreshResearchWorkflow();
    message.success('已加入研究池');
  }

  async function addCandidateToStablePool(candidate: ResearchCandidateView) {
    await postStablePool({
      research_candidate_id: candidate.candidate_id,
      chosen_run_id: candidate.representative_run_id,
      decision_reason: candidate.recommendation,
    });
    await onRefreshResearchWorkflow();
    message.success('已加入稳定池');
  }

  async function runStableCandidateExecutionVerification(candidate: StableCandidateView) {
    const parentRunId = candidate.representative_run_id ?? candidate.evidence_run_ids[0] ?? '';
    if (!parentRunId) {
      message.error('稳定组合缺少代表 Run，不能发起执行验证');
      return;
    }
    const executionSnapshot = [...datasets]
      .filter((snapshot) => snapshot.symbol === candidate.symbol && snapshot.timeframe === '5m')
      .sort((left, right) => right.time_range_end.localeCompare(left.time_range_end))[0];
    if (!executionSnapshot) {
      message.error(`请先导入 ${candidate.symbol} 的 5m 数据集，再运行执行验证`);
      return;
    }
    setExecutionVerificationCandidateId(candidate.stable_candidate_id);
    try {
      const result = await postStableCandidateExecutionVerification(candidate.stable_candidate_id, {
        source_run_id: parentRunId,
        execution_timeframe: '5m',
        execution_snapshot_id: executionSnapshot.dataset_snapshot_id,
      });
      const verificationRunId = String(result.verification_run_id ?? '');
      await onRefreshShell();
      await onRefreshResearchWorkflow();
      message.success(verificationRunId ? `执行验证已完成：${verificationRunId}` : '执行验证已完成');
    } catch (submitError: unknown) {
      message.error(submitError instanceof Error ? submitError.message : '执行验证失败');
    } finally {
      setExecutionVerificationCandidateId(null);
    }
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
  const isDrawdownProtectionBatch = selectedBatchId !== ALL_BATCHES && selectedBatchId.startsWith('drawdown-guard-');
  const drawdownProtectionComparisonRows = useMemo(
    () => (isDrawdownProtectionBatch ? buildDrawdownProtectionComparisonRows(selectedBatchRows) : []),
    [isDrawdownProtectionBatch, selectedBatchRows],
  );
  const recommendedResearchRuns = useMemo<ResearchRunCandidate[]>(() => {
    if (selectedBatchId === ALL_BATCHES) {
      return [];
    }
    const candidates = filteredBatchRunRows
      .filter((row) => row.oos_total_return !== null || row.total_return > 0)
      .map((row) => scoreResearchRun(row))
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score;
        }
        return (right.row.oos_total_return ?? right.row.total_return) - (left.row.oos_total_return ?? left.row.total_return);
      });
    const selected: ResearchRunCandidate[] = [];
    const seenCategories = new Set<string>();
    const categoryFor = (candidate: ResearchRunCandidate) => {
      if (candidate.tags.includes('Gap 小') && (candidate.row.oos_total_return ?? 0) > 0) {
        return 'consistent';
      }
      if ((candidate.row.oos_total_return ?? 0) >= 1) {
        return 'oos';
      }
      if (candidate.tags.includes('PF 高')) {
        return 'quality';
      }
      return 'general';
    };
    for (const candidate of candidates) {
      const category = categoryFor(candidate);
      if (!seenCategories.has(category) || selected.length >= 3) {
        selected.push(candidate);
        seenCategories.add(category);
      }
      if (selected.length >= 8) {
        break;
      }
    }
    return selected;
  }, [filteredBatchRunRows, selectedBatchId]);
  const neighborhoodSourceRun = useMemo(
    () => allRows.find((row) => row.run_id === neighborhoodSourceRunId) ?? null,
    [allRows, neighborhoodSourceRunId],
  );
  const trendNeighborhoodMatches = useMemo(
    () => buildTrendNeighborhoodMatches(neighborhoodSourceRun, allRows),
    [allRows, neighborhoodSourceRun],
  );
  const trendNeighborhoodStats = useMemo(
    () => buildNeighborhoodStabilityStats(trendNeighborhoodMatches),
    [trendNeighborhoodMatches],
  );
  const filteredExperimentRunRows = useMemo(
    () => selectedExperimentRows.filter((row) => (
      matchesRunLabelFilters(row.run_id, { applyAutoLabelFilters: false, applyBatchScoreFilters: false })
      && (experimentMinResearchScoreFilter === null || scoreResearchRun(row).score >= experimentMinResearchScoreFilter)
      && (experimentMinOosReturnFilter === null || (row.oos_total_return ?? Number.NEGATIVE_INFINITY) >= experimentMinOosReturnFilter / 100)
      && (experimentMinTotalReturnFilter === null || row.total_return >= experimentMinTotalReturnFilter / 100)
      && (experimentMinProfitFactorFilter === null || (row.profit_factor ?? Number.NEGATIVE_INFINITY) >= experimentMinProfitFactorFilter)
      && (experimentMaxDrawdownFilter === null || row.max_drawdown <= experimentMaxDrawdownFilter / 100)
      && (experimentMinTradeCountFilter === null || row.trade_count >= experimentMinTradeCountFilter)
    )),
    [
      runManualLabelFilter,
      selectedExperimentRows,
      autoLabelsByRunId,
      manualLabelsByRunId,
      experimentMaxDrawdownFilter,
      experimentMinOosReturnFilter,
      experimentMinProfitFactorFilter,
      experimentMinResearchScoreFilter,
      experimentMinTotalReturnFilter,
      experimentMinTradeCountFilter,
    ],
  );
  const activeTrackingNotes = useMemo(
    () => researchNotes
      .filter((note) => (
        note.target_type === 'run'
        && note.labels.includes('tracking')
        && note.labels.includes('frozen_run')
      ))
      .sort((left, right) => dayjs(right.created_at).valueOf() - dayjs(left.created_at).valueOf()),
    [researchNotes],
  );
  const trackedRunNotesByRunId = useMemo(() => {
    const noteMap = new Map<string, ResearchNote>();
    const seenRunIds = new Set<string>();
    for (const note of activeTrackingNotes) {
      if (seenRunIds.has(note.target_id)) {
        continue;
      }
      seenRunIds.add(note.target_id);
      if (note.decision_status !== 'rejected' && note.decision_status !== 'archived') {
        noteMap.set(note.target_id, note);
      }
    }
    return noteMap;
  }, [activeTrackingNotes]);
  const trackedRunRows = useMemo(
    () => allRows.filter((row) => trackedRunNotesByRunId.has(row.run_id)),
    [allRows, trackedRunNotesByRunId],
  );
  const filteredTrackedRunRows = useMemo(
    () => trackedRunRows.filter((row) => matchesRunLabelFilters(row.run_id, { applyAutoLabelFilters: false, applyBatchScoreFilters: false })),
    [trackedRunRows, runManualLabelFilter, manualLabelsByRunId],
  );
  const trackedMissingNotes = useMemo(
    () => Array.from(trackedRunNotesByRunId.values()).filter((note) => !allRows.some((row) => row.run_id === note.target_id)),
    [allRows, trackedRunNotesByRunId],
  );
  const freezeRunForTracking = useCallback(async (row: ParameterLabRow) => {
    await onSaveResearchNote('run', row.run_id, buildFrozenRunNoteValues(row));
  }, [onSaveResearchNote]);
  const rowsByRunId = useMemo(
    () => new Map(allRows.map((row) => [row.run_id, row] as const)),
    [allRows],
  );
  const latestDrawdownProtectionBatchForKey = useCallback((key: string) => {
    const prefix = `drawdown-guard-${safeBatchKeyPart(key)}-`;
    return [...batches]
      .filter((batch) => batch.batch_id.startsWith(prefix))
      .sort((left, right) => dayjs(right.created_at).valueOf() - dayjs(left.created_at).valueOf())[0];
  }, [batches]);
  const [runCompareIds, setRunCompareIds] = useState<string[]>([]);
  const [runCompareOpen, setRunCompareOpen] = useState(false);
  const runCompareRows = useMemo(
    () => runCompareIds.map((runId) => rowsByRunId.get(runId)).filter((row): row is ParameterLabRow => Boolean(row)),
    [rowsByRunId, runCompareIds],
  );
  const runCompareModel = useMemo(
    () => (runCompareRows.length === 2 ? buildRunCompareModel(runCompareRows[0], runCompareRows[1]) : null),
    [runCompareRows],
  );
  const addRunToCompare = useCallback(async (runId: string) => {
    if (!rowsByRunId.has(runId)) {
      const loadedRows = await onLoadParameterRows();
      if (!loadedRows.some((row) => row.run_id === runId)) {
        message.warning('没有找到这条 Run 的完整参数，可能对应结果还未落盘。');
        return;
      }
    }
    setRunCompareIds((current) => {
      if (current.includes(runId)) {
        message.info('这条 Run 已经在对比栏里。');
        return current;
      }
      const next = current.length >= 2 ? [current[1], runId] : [...current, runId];
      if (next.length === 2) {
        setRunCompareOpen(true);
      }
      return next;
    });
  }, [message, onLoadParameterRows, rowsByRunId]);
  const clearRunCompare = useCallback(() => {
    setRunCompareIds([]);
    setRunCompareOpen(false);
  }, []);
  const runCompareSelectionText = runCompareRows.length
    ? runCompareRows.map((row, index) => `${index === 0 ? 'A' : 'B'}: ${shortRunId(row.run_id)}`).join(' / ')
    : '';
  const researchParameterGroupColumns = useMemo<ColumnDef<ParameterGroupView>[]>(() => [
    {
      id: 'parameter_summary',
      header: '组合内容',
      size: 260,
      minSize: 240,
      accessorFn: (row) => row.parameter_summary,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.original.parameter_summary}</Text>
          {row.original.signal_filter_summary ? <Tag color="blue">{row.original.signal_filter_summary}</Tag> : null}
          <Text type="secondary">{row.original.symbol} · {row.original.timeframe.toUpperCase()}</Text>
        </Space>
      ),
    },
    {
      id: 'different_points',
      header: '差异点',
      size: 260,
      minSize: 220,
      enableSorting: false,
      cell: ({ row }) => renderParameterPoints(
        parameterGroupPoints(row.original).filter((point) => !researchGroupCommonKeys.has(point.key)),
        'blue',
      ),
    },
    {
      id: 'classification',
      header: '分类',
      size: 110,
      minSize: 100,
      accessorFn: (row) => row.classification,
      cell: ({ row }) => <Tag color={parameterGroupClassificationColor(row.original.classification)}>{parameterGroupClassificationText(row.original.classification)}</Tag>,
    },
    { id: 'research_score', header: '研究分', size: 76, minSize: 68, accessorFn: (row) => row.research_score, cell: ({ row }) => formatNumber(row.original.research_score, 1) },
    { id: 'run_count', header: 'Run', size: 58, minSize: 54, accessorFn: (row) => row.run_count, cell: ({ row }) => row.original.run_count },
    { id: 'snapshot_count', header: '快照', size: 58, minSize: 54, accessorFn: (row) => row.snapshot_count, cell: ({ row }) => row.original.snapshot_count },
    { id: 'avg_oos_total_return', header: '平均 OOS', size: 96, minSize: 88, accessorFn: (row) => row.avg_oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.avg_oos_total_return) },
    { id: 'oos_positive_ratio', header: 'OOS 正比', size: 92, minSize: 84, accessorFn: (row) => row.oos_positive_ratio ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_positive_ratio) },
    { id: 'avg_gap', header: '平均 Gap', size: 92, minSize: 84, accessorFn: (row) => row.avg_gap ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(row.original.avg_gap) },
    { id: 'avg_max_drawdown', header: '平均回撤', size: 92, minSize: 84, accessorFn: (row) => row.avg_max_drawdown, cell: ({ row }) => formatPct(row.original.avg_max_drawdown) },
    { id: 'worst_max_drawdown', header: '最差回撤', size: 92, minSize: 84, accessorFn: (row) => row.worst_max_drawdown, cell: ({ row }) => formatPct(row.original.worst_max_drawdown) },
    { id: 'avg_profit_factor', header: '平均 PF', size: 78, minSize: 72, accessorFn: (row) => row.avg_profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.avg_profit_factor, 2) },
    { id: 'min_trade_count', header: '最少交易', size: 76, minSize: 70, accessorFn: (row) => row.min_trade_count, cell: ({ row }) => row.original.min_trade_count },
    { id: 'neighbor_stability_score', header: '邻域稳定', size: 86, minSize: 78, accessorFn: (row) => row.neighbor_stability_score ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.neighbor_stability_score) },
    {
      id: 'filter_experiment',
      header: '过滤实验',
      size: 170,
      minSize: 150,
      enableSorting: false,
      cell: ({ row }) => {
        const progress = filterExperimentProgressByCandidateId[row.original.group_key];
        const running = Boolean(progress && progress.status !== 'success' && progress.status !== 'failed');
        const candidateLike = {
          candidate_id: row.original.group_key,
          source_run_ids: row.original.run_ids,
          strategy_name: row.original.strategy_name,
          symbol: row.original.symbol,
          timeframe: row.original.timeframe,
          validation_split_id: row.original.validation_split_id,
          entry_structure: {},
          risk_profile: {},
          representative_run_id: row.original.representative_run_id,
          representative_run_score: row.original.research_score,
          status: row.original.classification,
          recommendation: '',
          neighborhood_summary: {},
          risk_matrix_summary: {},
          latest_note: null,
          updated_at: null,
        } as ResearchCandidateView;
        return (
          <Space size={[4, 4]} wrap>
            <Tooltip title={progress ? `${progress.batchId} ${progress.runCount}/${progress.plannedRunCount || '--'}` : '固定当前参数，只跑早败代理阈值扫描：MOM3 与局部位置'}>
              <Button
                size="small"
                loading={filterExperimentCandidateId === row.original.group_key || running}
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2'}
                onClick={() => void onRunFilterExperiment(candidateLike, 'early_fail_proxy')}
              >早败</Button>
            </Tooltip>
            <Tooltip title="固定当前参数，只跑通用过滤：HTF、ATR 分位、ADX">
              <Button
                size="small"
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2'}
                onClick={() => void onRunFilterExperiment(candidateLike, 'general')}
              >通用</Button>
            </Tooltip>
          </Space>
        );
      },
    },
    {
      id: 'actions',
      header: '操作',
      size: 320,
      minSize: 300,
      enableSorting: false,
      cell: ({ row }) => {
        const representativeRun = row.original.representative_run_id ? rowsByRunId.get(row.original.representative_run_id) : undefined;
        const canRunNeighborhood = representativeRun?.strategy_name === 'ema_pullback_atr_v2'
          && Boolean(representativeRun.trend_fast_period && representativeRun.trend_slow_period);
        return (
          <Space size={6}>
            <Button size="small" onClick={() => setSelectedParameterGroupKey(row.original.group_key)}>详情</Button>
            <Button size="small" onClick={() => setRiskCompareGroupKey(row.original.group_key)}>风险对比</Button>
            {row.original.representative_run_id ? (
              <Button size="small" onClick={() => onOpenRun(row.original.representative_run_id as string)}>代表 Run</Button>
            ) : null}
            {row.original.representative_run_id ? (
              <Button size="small" onClick={() => void addRunToCompare(row.original.representative_run_id as string)}>对比</Button>
            ) : null}
            <Button
              size="small"
              disabled={!representativeRun}
              onClick={() => representativeRun ? setNeighborhoodSourceRunId(representativeRun.run_id) : undefined}
            >
              看邻域
            </Button>
            <Tooltip title={canRunNeighborhood ? '固定当前参数组的 tol/sl/rr/仓位/杠杆，只扩展趋势快慢周期邻域' : '需要 v2 代表 Run 才能跑趋势周期邻域'}>
              <Button
                size="small"
                disabled={!canRunNeighborhood || !representativeRun}
                loading={representativeRun ? neighborhoodRunId === representativeRun.run_id : false}
                onClick={() => representativeRun ? void onRunTrendNeighborhood(representativeRun) : undefined}
              >
                跑邻域
              </Button>
            </Tooltip>
          </Space>
        );
      },
    },
  ], [addRunToCompare, filterExperimentCandidateId, filterExperimentProgressByCandidateId, neighborhoodRunId, onOpenRun, onRunFilterExperiment, onRunTrendNeighborhood, researchGroupCommonKeys, rowsByRunId]);
  const screeningRunColumns = useMemo<ColumnDef<ScreeningRunView>[]>(() => [
    {
      id: 'run',
      header: 'Run',
      size: 230,
      minSize: 210,
      accessorFn: (row) => row.run_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{row.original.symbol} · {row.original.timeframe.toUpperCase()}</Text>
        </Space>
      ),
    },
    {
      id: 'parameter_summary',
      header: '参数摘要',
      size: 260,
      minSize: 220,
      accessorFn: (row) => row.parameter_summary,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text>{row.original.parameter_summary}</Text>
          {row.original.signal_filter_summary ? <Tag color="blue">{row.original.signal_filter_summary}</Tag> : null}
        </Space>
      ),
    },
    { id: 'score', header: '评分', size: 82, minSize: 76, accessorFn: (row) => row.score, cell: ({ row }) => formatNumber(row.original.score, 1) },
    {
      id: 'labels',
      header: '标签',
      size: 260,
      minSize: 220,
      enableSorting: false,
      cell: ({ row }) => (
        <Space size={[4, 4]} wrap>
          {row.original.auto_labels.map((label) => (
            <Tag key={`${row.original.run_id}-${label}`} color={label === '建议排除' || label === '回撤过大' ? 'red' : label === '值得研究' || label === 'OOS 强' || label === 'Gap 小' ? 'green' : 'default'}>
              {label}
            </Tag>
          ))}
          {row.original.manual_labels.map((label) => (
            <Tag key={`${row.original.run_id}-manual-${label}`} color="blue">{researchLabelText(label)}</Tag>
          ))}
        </Space>
      ),
    },
    {
      id: 'oos_total_return',
      header: () => <Tooltip title="样本外 OOS 区间收益率。">OOS</Tooltip>,
      size: 92,
      minSize: 86,
      accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => formatPct(row.original.oos_total_return),
    },
    {
      id: 'oos_excess_return',
      header: () => <Tooltip title="样本外 OOS 收益率减去同期基准收益率。">OOS超额</Tooltip>,
      size: 104,
      minSize: 96,
      accessorFn: (row) => row.oos_excess_return ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => formatPct(row.original.oos_excess_return),
    },
    {
      id: 'is_excess_return',
      header: () => <Tooltip title="样本内 IS 收益率减去同期基准收益率。">IS超额</Tooltip>,
      size: 104,
      minSize: 96,
      accessorFn: (row) => row.is_excess_return ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => formatPct(row.original.is_excess_return),
    },
    {
      id: 'gap',
      header: () => <Tooltip title="样本内收益率减样本外收益率，越小通常表示 IS/OOS 落差越小。">Gap</Tooltip>,
      size: 92,
      minSize: 86,
      accessorFn: (row) => row.is_oos_gap ?? Number.POSITIVE_INFINITY,
      cell: ({ row }) => formatPct(row.original.is_oos_gap),
    },
    { id: 'max_drawdown', header: '回撤', size: 92, minSize: 86, accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    { id: 'profit_factor', header: 'PF', size: 72, minSize: 68, accessorFn: (row) => row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.profit_factor, 2) },
    { id: 'trade_count', header: '交易数', size: 76, minSize: 70, accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    { id: 'oos_trade_count', header: 'OOS 交易', size: 86, minSize: 78, accessorFn: (row) => row.oos_trade_count ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.oos_trade_count ?? '--' },
    { id: 'leverage', header: '杠杆', size: 70, minSize: 66, accessorFn: (row) => row.leverage ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.leverage ?? '--' },
    { id: 'risk_pct_per_trade', header: 'risk', size: 78, minSize: 72, accessorFn: (row) => row.risk_pct_per_trade ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => compactPct(row.original.risk_pct_per_trade) ?? '--' },
    {
      id: 'filter_experiment',
      header: '过滤实验',
      size: 190,
      minSize: 170,
      enableSorting: false,
      cell: ({ row }) => {
        const group = researchParameterGroups.find((item) => item.run_ids.includes(row.original.run_id));
        const candidateId = group?.group_key;
        const progress = candidateId ? filterExperimentProgressByCandidateId[candidateId] : undefined;
        const running = Boolean(progress && progress.status !== 'success' && progress.status !== 'failed');
        const candidateLike = candidateId ? {
          candidate_id: candidateId,
          source_run_ids: group?.run_ids ?? [row.original.run_id],
          strategy_name: group?.strategy_name ?? row.original.strategy_name,
          symbol: group?.symbol ?? row.original.symbol,
          timeframe: group?.timeframe ?? row.original.timeframe,
          validation_split_id: group?.validation_split_id ?? row.original.validation_split_id,
          entry_structure: {},
          risk_profile: {},
          representative_run_id: group?.representative_run_id ?? row.original.run_id,
          representative_run_score: group?.research_score ?? row.original.score,
          status: group?.classification ?? row.original.pool_status,
          recommendation: '',
          neighborhood_summary: {},
          risk_matrix_summary: {},
          latest_note: null,
          updated_at: null,
        } as ResearchCandidateView : null;
        return (
          <Space size={[4, 4]} wrap>
            <Tooltip title={progress ? `${progress.batchId} ${progress.runCount}/${progress.plannedRunCount || '--'}` : '固定当前参数，只跑早败代理阈值扫描：MOM3 与局部位置'}>
              <Button
                size="small"
                loading={Boolean(candidateId && filterExperimentCandidateId === candidateId) || running}
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2' || !candidateLike}
                onClick={() => candidateLike ? void onRunFilterExperiment(candidateLike, 'early_fail_proxy') : undefined}
              >早败</Button>
            </Tooltip>
            <Tooltip title="固定当前参数，只跑通用过滤：HTF、ATR 分位、ADX">
              <Button
                size="small"
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2' || !candidateLike}
                onClick={() => candidateLike ? void onRunFilterExperiment(candidateLike, 'general') : undefined}
              >通用</Button>
            </Tooltip>
            <Button size="small" disabled={!candidateId} onClick={() => candidateId ? setFilterResultsCandidateId(candidateId) : undefined}>
              看结果
            </Button>
          </Space>
        );
      },
    },
    {
      id: 'actions',
      header: '操作',
      size: 330,
      minSize: 300,
      enableSorting: false,
      cell: ({ row }) => {
        const run = rowsByRunId.get(row.original.run_id);
        const canRunNeighborhood = row.original.strategy_name === 'ema_pullback_atr_v2' && Boolean(row.original.trend_fast_period && row.original.trend_slow_period);
        const inResearchPool = row.original.pool_status === 'research_pool' || row.original.manual_labels.includes('research_pool');
        return (
          <Space size={6}>
            <Button size="small" disabled={inResearchPool} loading={savingResearchNote} onClick={() => void addRunToResearchPool(row.original)}>
              {inResearchPool ? '已加入' : '加入研究池'}
            </Button>
            <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开分析</Button>
            <Button size="small" onClick={() => void addRunToCompare(row.original.run_id)}>对比</Button>
            <Button size="small" disabled={!canRunNeighborhood} onClick={() => setNeighborhoodSourceRunId(row.original.run_id)}>看邻域</Button>
            <Button
              size="small"
              disabled={!canRunNeighborhood || !run}
              loading={neighborhoodRunId === row.original.run_id}
              onClick={() => run ? void onRunTrendNeighborhood(run) : undefined}
            >
              跑邻域
            </Button>
            <Button
              size="small"
              danger
              onClick={() => openDecisionModal('run', row.original.run_id, `排除 Run ${shortRunId(row.original.run_id)}`, { decision_status: 'rejected', labels: ['screening_pool_excluded'] })}
            >
              排除
            </Button>
          </Space>
        );
      },
    },
  ], [addRunToCompare, filterExperimentCandidateId, filterExperimentProgressByCandidateId, neighborhoodRunId, onOpenRun, onRunFilterExperiment, onRunTrendNeighborhood, researchParameterGroups, rowsByRunId, savingResearchNote]);
  const researchPoolColumns = useMemo<ColumnDef<ResearchCandidateView>[]>(() => [
    {
      id: 'candidate',
      header: '研究对象',
      size: 220,
      minSize: 190,
      accessorFn: (row) => row.candidate_id,
      cell: ({ row }) => (
        <div className="cbw-research-target">
          <Text strong className="cbw-research-target-main">
            {row.original.symbol} · {row.original.timeframe.toUpperCase()}
          </Text>
          <Tooltip title={`${row.original.strategy_name} · ${row.original.validation_split_id}`}>
            <Text type="secondary" className="cbw-research-target-sub">
              {compactStrategyName(row.original.strategy_name)} · {shortRunId(row.original.validation_split_id)}
            </Text>
          </Tooltip>
        </div>
      ),
    },
    { id: 'status', header: '状态', size: 110, minSize: 100, accessorFn: (row) => row.status, cell: ({ row }) => <Tag color={row.original.status === '可入稳定池' ? 'green' : row.original.status === '拒绝' ? 'red' : 'blue'}>{row.original.status}</Tag> },
    { id: 'representative_run_score', header: '代表分', size: 82, minSize: 76, accessorFn: (row) => row.representative_run_score, cell: ({ row }) => formatNumber(row.original.representative_run_score, 1) },
    { id: 'source_run_ids', header: '证据 Run', size: 88, minSize: 80, accessorFn: (row) => row.source_run_ids.length, cell: ({ row }) => row.original.source_run_ids.length },
    { id: 'neighborhood', header: '邻域', size: 150, minSize: 130, accessorFn: (row) => String(row.neighborhood_summary.verdict ?? ''), cell: ({ row }) => `${row.original.neighborhood_summary.status ?? '--'} · ${row.original.neighborhood_summary.verdict ?? '--'}` },
    {
      id: 'filter_experiment',
      header: '过滤实验',
      size: 170,
      minSize: 150,
      enableSorting: false,
      cell: ({ row }) => {
        const progress = filterExperimentProgressByCandidateId[row.original.candidate_id];
        const running = Boolean(progress && progress.status !== 'success' && progress.status !== 'failed');
        return (
          <Space size={[4, 4]} wrap>
            <Tooltip title={progress ? `${progress.batchId} ${progress.runCount}/${progress.plannedRunCount || '--'}` : '固定当前参数，只跑早败代理阈值扫描：MOM3 与局部位置'}>
              <Button
                size="small"
                loading={filterExperimentCandidateId === row.original.candidate_id || running}
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2'}
                onClick={() => void onRunFilterExperiment(row.original, 'early_fail_proxy')}
              >早败</Button>
            </Tooltip>
            <Tooltip title="固定当前参数，只跑通用过滤：HTF、ATR 分位、ADX">
              <Button
                size="small"
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2'}
                onClick={() => void onRunFilterExperiment(row.original, 'general')}
              >通用</Button>
            </Tooltip>
            <Button size="small" onClick={() => setFilterResultsCandidateId(row.original.candidate_id)}>
              看结果
            </Button>
          </Space>
        );
      },
    },
    {
      id: 'drawdown_protection',
      header: '回撤保护',
      size: 180,
      minSize: 160,
      enableSorting: false,
      cell: ({ row }) => {
        const representativeRunId = row.original.representative_run_id ?? null;
        const progress = drawdownProtectionProgressByCandidateId[row.original.candidate_id];
        const latestBatch = latestDrawdownProtectionBatchForKey(row.original.candidate_id);
        const resultBatchId = progress?.batchId || latestBatch?.batch_id;
        const running = Boolean(progress && progress.status !== 'success' && progress.status !== 'failed')
          || latestBatch?.status === 'pending'
          || latestBatch?.status === 'running';
        return (
          <Space size={[4, 4]} wrap>
            <Tooltip title={progress ? `${progress.batchId} ${progress.runCount}/${progress.plannedRunCount || '--'}` : '固定代表 Run 原始参数，只展开 DD 停开与连续短止冷却保护'}>
              <Button
                size="small"
                loading={drawdownProtectionCandidateId === row.original.candidate_id || drawdownProtectionRunId === representativeRunId || running}
                disabled={!representativeRunId || running}
                onClick={() => representativeRunId ? void onRunDrawdownProtectionExperiment(representativeRunId, row.original.candidate_id) : undefined}
              >
                跑保护
              </Button>
            </Tooltip>
            <Button
              size="small"
              disabled={!resultBatchId}
              onClick={() => {
                if (!resultBatchId) {
                  return;
                }
                setSelectedBatchId(resultBatchId);
                setWorkspaceMode('batch');
              }}
            >
              看结果
            </Button>
          </Space>
        );
      },
    },
    {
      id: 'risk_matrix',
      header: '风险矩阵',
      size: 140,
      minSize: 120,
      accessorFn: (row) => String(row.risk_matrix_summary.status ?? ''),
      cell: ({ row }) => {
        const progress = riskMatrixProgressByCandidateId[row.original.candidate_id];
        const summary = row.original.risk_matrix_summary;
        if (progress && progress.status !== 'success' && progress.status !== 'failed') {
          return <Tag color="processing">运行中 {progress.runCount}/{progress.plannedRunCount || '--'}</Tag>;
        }
        if (progress?.status === 'failed') {
          return <Tag color="red">失败</Tag>;
        }
        if (summary.status === '已跑' || progress?.status === 'success') {
          const groupCount = Number(summary.group_count ?? 0);
          return <Tag color="green">已跑{groupCount ? ` ${groupCount}组` : ''}</Tag>;
        }
        return <Tag>{String(summary.status ?? '--')}</Tag>;
      },
    },
    { id: 'recommendation', header: '综合结论', size: 160, minSize: 140, accessorFn: (row) => row.recommendation, cell: ({ row }) => row.original.recommendation },
    { id: 'updated_at', header: '最近更新', size: 150, minSize: 130, accessorFn: (row) => row.updated_at ?? '', cell: ({ row }) => row.original.updated_at ? formatDateTime(row.original.updated_at) : '--' },
    {
      id: 'actions',
      header: '操作',
      size: 420,
      minSize: 360,
      enableSorting: false,
      cell: ({ row }) => {
        const representativeRun = row.original.representative_run_id ? rowsByRunId.get(row.original.representative_run_id) : undefined;
        const canRunNeighborhood = representativeRun?.strategy_name === 'ema_pullback_atr_v2' && Boolean(representativeRun.trend_fast_period && representativeRun.trend_slow_period);
        const riskMatrixProgress = riskMatrixProgressByCandidateId[row.original.candidate_id];
        const riskMatrixRunning = Boolean(riskMatrixProgress && riskMatrixProgress.status !== 'success' && riskMatrixProgress.status !== 'failed');
        const riskMatrixReady = row.original.risk_matrix_summary.status === '已跑' || riskMatrixProgress?.status === 'success';
        return (
          <Space size={6}>
            <Button size="small" onClick={() => setSelectedParameterGroupKey(row.original.candidate_id)}>打开研究</Button>
            {row.original.representative_run_id ? <Button size="small" onClick={() => onOpenRun(row.original.representative_run_id as string)}>代表 Run</Button> : null}
            {row.original.representative_run_id ? (
              <Button size="small" onClick={() => void addRunToCompare(row.original.representative_run_id as string)}>对比</Button>
            ) : null}
            <Button size="small" disabled={!representativeRun} onClick={() => representativeRun ? setNeighborhoodSourceRunId(representativeRun.run_id) : undefined}>看邻域</Button>
            <Button size="small" disabled={!canRunNeighborhood || !representativeRun} loading={representativeRun ? neighborhoodRunId === representativeRun.run_id : false} onClick={() => representativeRun ? void onRunTrendNeighborhood(representativeRun) : undefined}>跑邻域</Button>
            <Button size="small" onClick={() => setTradeAttributionCandidateId(row.original.candidate_id)}>交易归因</Button>
            {riskMatrixReady ? (
              <Button size="small" onClick={() => setRiskCompareGroupKey(row.original.candidate_id)}>看风险矩阵</Button>
            ) : (
              <Button
                size="small"
                loading={riskMatrixCandidateId === row.original.candidate_id || riskMatrixRunning}
                disabled={riskMatrixRunning}
                onClick={() => void onRunRiskMatrix(row.original)}
              >
                {riskMatrixRunning ? '运行中' : '跑风险矩阵'}
              </Button>
            )}
            <Button size="small" onClick={() => openDecisionModal('research_candidate', row.original.candidate_id, `研究候选 ${row.original.symbol}`, { decision_status: 'observing', labels: ['research_pool'] })}>记录结论</Button>
            <Button size="small" type="primary" onClick={() => void addCandidateToStablePool(row.original)}>加入稳定池</Button>
          </Space>
        );
      },
    },
  ], [addRunToCompare, drawdownProtectionCandidateId, drawdownProtectionProgressByCandidateId, drawdownProtectionRunId, filterExperimentCandidateId, filterExperimentProgressByCandidateId, latestDrawdownProtectionBatchForKey, neighborhoodRunId, onOpenRun, onRunDrawdownProtectionExperiment, onRunFilterExperiment, onRunRiskMatrix, onRunTrendNeighborhood, riskMatrixCandidateId, riskMatrixProgressByCandidateId, rowsByRunId, setSelectedBatchId]);
  const stablePoolColumns = useMemo<ColumnDef<StableCandidateView>[]>(() => [
    {
      id: 'candidate',
      header: '稳定组合',
      size: 260,
      minSize: 220,
      accessorFn: (row) => row.stable_candidate_id,
      cell: ({ row }) => (
        <div className="cbw-research-target">
          <Text strong className="cbw-research-target-main">{row.original.symbol} · {row.original.timeframe.toUpperCase()}</Text>
          <Tooltip title={`${row.original.strategy_name} · ${row.original.validation_split_id}`}>
            <Text type="secondary" className="cbw-research-target-sub">
              {compactStrategyName(row.original.strategy_name)} · {shortRunId(row.original.validation_split_id)}
            </Text>
          </Tooltip>
        </div>
      ),
    },
    { id: 'status', header: '状态', size: 90, minSize: 80, accessorFn: (row) => row.status, cell: ({ row }) => <Tag color="green">{decisionStatusText(row.original.status)}</Tag> },
    { id: 'score', header: '评分', size: 80, minSize: 74, accessorFn: (row) => Number(row.validation_summary.score ?? 0), cell: ({ row }) => formatNumber(Number(row.original.validation_summary.score ?? 0), 1) },
    { id: 'avg_oos_total_return', header: 'OOS', size: 92, minSize: 86, accessorFn: (row) => Number(row.validation_summary.avg_oos_total_return ?? Number.NEGATIVE_INFINITY), cell: ({ row }) => formatPct(Number(row.original.validation_summary.avg_oos_total_return ?? NaN)) },
    { id: 'worst_max_drawdown', header: '最大回撤', size: 96, minSize: 88, accessorFn: (row) => Number(row.validation_summary.worst_max_drawdown ?? 0), cell: ({ row }) => formatPct(Number(row.original.validation_summary.worst_max_drawdown ?? NaN)) },
    { id: 'avg_profit_factor', header: 'PF', size: 72, minSize: 68, accessorFn: (row) => Number(row.validation_summary.avg_profit_factor ?? Number.NEGATIVE_INFINITY), cell: ({ row }) => formatNumber(Number(row.original.validation_summary.avg_profit_factor ?? NaN), 2) },
    { id: 'neighborhood', header: '邻域结论', size: 130, minSize: 112, accessorFn: (row) => String(row.neighborhood_summary.verdict ?? ''), cell: ({ row }) => String(row.original.neighborhood_summary.verdict ?? '--') },
    {
      id: 'execution_verification',
      header: '执行验证',
      size: 190,
      minSize: 170,
      accessorFn: (row) => row.execution_verification.status,
      cell: ({ row }) => {
        const verification = row.original.execution_verification;
        const summary = verification.summary ?? {};
        const validation = verification.validation ?? null;
        const latestRunId = verification.latest_run_id;
        return (
          <Space direction="vertical" size={4}>
            <Space size={4} wrap>
              <Tag color={executionVerificationStatusColor(verification.status)}>
                {executionVerificationStatusText(verification.status)}
              </Tag>
              {verification.execution_timeframe ? <Tag>{verification.execution_timeframe}</Tag> : null}
            </Space>
            {latestRunId ? (
              <Space direction="vertical" size={0}>
                <Text type="secondary">
                  5m {formatPct(Number(summary.total_return ?? NaN))} / DD {formatPct(Number(summary.max_drawdown ?? NaN))}
                </Text>
                {validation ? (
                  <Text type="secondary">
                    IS {formatPct(Number(validation.is_total_return ?? NaN))} / OOS {formatPct(Number(validation.oos_total_return ?? NaN))}
                  </Text>
                ) : null}
              </Space>
            ) : (
              <Text type="secondary">需要 5m 数据</Text>
            )}
            <Space size={4} wrap>
              <Button
                size="small"
                loading={executionVerificationCandidateId === row.original.stable_candidate_id}
                onClick={() => void runStableCandidateExecutionVerification(row.original)}
              >
                跑 5m
              </Button>
              <Button size="small" disabled={!latestRunId} onClick={() => latestRunId ? onOpenRun(latestRunId) : undefined}>
                5m研究
              </Button>
            </Space>
          </Space>
        );
      },
    },
    {
      id: 'filter_experiment',
      header: '过滤实验',
      size: 190,
      minSize: 170,
      enableSorting: false,
      cell: ({ row }) => {
        const progress = filterExperimentProgressByCandidateId[row.original.stable_candidate_id];
        const running = Boolean(progress && progress.status !== 'success' && progress.status !== 'failed');
        const latestExecutionRunId = row.original.execution_verification.latest_run_id;
        const candidateLike = {
          candidate_id: row.original.stable_candidate_id,
          source_run_ids: row.original.evidence_run_ids,
          strategy_name: row.original.strategy_name,
          symbol: row.original.symbol,
          timeframe: row.original.timeframe,
          validation_split_id: row.original.validation_split_id,
          entry_structure: row.original.entry_structure,
          risk_profile: row.original.chosen_risk_profile,
          representative_run_id: row.original.representative_run_id,
          representative_run_score: Number(row.original.validation_summary.score ?? 0),
          status: row.original.status,
          recommendation: row.original.final_recommendation,
          neighborhood_summary: row.original.neighborhood_summary,
          risk_matrix_summary: row.original.risk_matrix_summary,
          latest_note: row.original.latest_note,
          updated_at: null,
        } as ResearchCandidateView;
        return (
          <Space size={[4, 4]} wrap>
            <Tooltip title={progress ? `${progress.batchId} ${progress.runCount}/${progress.plannedRunCount || '--'}` : '基于最新 5m 执行验证 run，重放 1h 信号过滤后再映射到 5m 执行'}>
              <Button
                size="small"
                loading={filterExperimentCandidateId === row.original.stable_candidate_id || running}
                disabled={running || !latestExecutionRunId || row.original.strategy_name !== 'ema_pullback_atr_v2'}
                onClick={() => {
                  void onRunExecutionFilterExperiment(row.original).then((batchId) => {
                    if (!batchId) {
                      return;
                    }
                    setSelectedBatchId(batchId);
                    setWorkspaceMode('batch');
                  });
                }}
              >5m过滤</Button>
            </Tooltip>
            <Tooltip title="固定当前稳定组合，只跑通用过滤：HTF、ATR 分位、ADX">
              <Button
                size="small"
                disabled={running || row.original.strategy_name !== 'ema_pullback_atr_v2'}
                onClick={() => void onRunFilterExperiment(candidateLike, 'general')}
              >通用</Button>
            </Tooltip>
            <Button size="small" onClick={() => setFilterResultsCandidateId(row.original.stable_candidate_id)}>
              看结果
            </Button>
          </Space>
        );
      },
    },
    {
      id: 'drawdown_protection',
      header: '回撤保护',
      size: 180,
      minSize: 160,
      enableSorting: false,
      cell: ({ row }) => {
        const representativeRunId = row.original.representative_run_id ?? null;
        const progress = drawdownProtectionProgressByCandidateId[row.original.stable_candidate_id];
        const latestBatch = latestDrawdownProtectionBatchForKey(row.original.stable_candidate_id);
        const resultBatchId = progress?.batchId || latestBatch?.batch_id;
        const running = Boolean(progress && progress.status !== 'success' && progress.status !== 'failed')
          || latestBatch?.status === 'pending'
          || latestBatch?.status === 'running';
        return (
          <Space size={[4, 4]} wrap>
            <Tooltip title={progress ? `${progress.batchId} ${progress.runCount}/${progress.plannedRunCount || '--'}` : '固定稳定组合代表 Run 原始参数，只展开 DD 停开与连续短止冷却保护'}>
              <Button
                size="small"
                loading={drawdownProtectionCandidateId === row.original.stable_candidate_id || drawdownProtectionRunId === representativeRunId || running}
                disabled={!representativeRunId || running}
                onClick={() => representativeRunId ? void onRunDrawdownProtectionExperiment(representativeRunId, row.original.stable_candidate_id) : undefined}
              >
                跑保护
              </Button>
            </Tooltip>
            <Button
              size="small"
              disabled={!resultBatchId}
              onClick={() => {
                if (!resultBatchId) {
                  return;
                }
                setSelectedBatchId(resultBatchId);
                setWorkspaceMode('batch');
              }}
            >
              看结果
            </Button>
          </Space>
        );
      },
    },
    { id: 'final_recommendation', header: '最终建议', size: 220, minSize: 180, accessorFn: (row) => row.final_recommendation, cell: ({ row }) => row.original.final_recommendation },
    {
      id: 'actions',
      header: '操作',
      size: 320,
      minSize: 280,
      enableSorting: false,
      cell: ({ row }) => (
          <Space size={6}>
            <Button size="small" onClick={() => setSelectedParameterGroupKey(row.original.stable_candidate_id)}>打开详情</Button>
            {row.original.representative_run_id ? <Button size="small" onClick={() => onOpenRun(row.original.representative_run_id as string)}>查看证据</Button> : null}
            {row.original.representative_run_id ? (
              <Button size="small" onClick={() => void addRunToCompare(row.original.representative_run_id as string)}>对比</Button>
            ) : null}
            <Button size="small" onClick={() => setTradeAttributionCandidateId(row.original.stable_candidate_id)}>交易归因</Button>
            <Button size="small" onClick={() => openDecisionModal('stable_candidate', row.original.stable_candidate_id, `稳定组合 ${row.original.symbol}`, { decision_status: 'archived', labels: ['stable_pool'] })}>归档</Button>
          </Space>
      ),
    },
  ], [addRunToCompare, drawdownProtectionCandidateId, drawdownProtectionProgressByCandidateId, drawdownProtectionRunId, executionVerificationCandidateId, filterExperimentCandidateId, filterExperimentProgressByCandidateId, latestDrawdownProtectionBatchForKey, onOpenRun, onRunDrawdownProtectionExperiment, onRunExecutionFilterExperiment, onRunFilterExperiment, rowsByRunId, runStableCandidateExecutionVerification, setSelectedBatchId]);
  const filterResultGroupColumns = useMemo<ColumnDef<FilterResultGroup>[]>(() => [
    {
      id: 'filter_summary',
      header: '过滤器',
      size: 210,
      minSize: 180,
      accessorFn: (row) => row.filter_summary,
      cell: ({ row }) => <Tag color="blue">{row.original.filter_summary}</Tag>,
    },
    { id: 'run_count', header: 'Run', size: 62, minSize: 58, accessorFn: (row) => row.run_count, cell: ({ row }) => row.original.run_count },
    { id: 'snapshot_count', header: '快照', size: 68, minSize: 62, accessorFn: (row) => row.snapshot_count, cell: ({ row }) => row.original.snapshot_count },
    { id: 'avg_oos_total_return', header: '平均 OOS', size: 96, minSize: 88, accessorFn: (row) => row.avg_oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.avg_oos_total_return) },
    {
      id: 'avg_oos_delta',
      header: 'OOS 变化',
      size: 96,
      minSize: 88,
      accessorFn: (row) => row.avg_oos_delta ?? Number.NEGATIVE_INFINITY,
      cell: ({ row }) => <Text type={Number(row.original.avg_oos_delta ?? 0) >= 0 ? 'success' : 'danger'}>{formatSignedPct(row.original.avg_oos_delta)}</Text>,
    },
    { id: 'avg_max_drawdown', header: '平均回撤', size: 96, minSize: 88, accessorFn: (row) => row.avg_max_drawdown ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(row.original.avg_max_drawdown) },
    {
      id: 'avg_drawdown_delta',
      header: '回撤变化',
      size: 96,
      minSize: 88,
      accessorFn: (row) => row.avg_drawdown_delta ?? Number.POSITIVE_INFINITY,
      cell: ({ row }) => <Text type={Number(row.original.avg_drawdown_delta ?? 0) <= 0 ? 'success' : 'danger'}>{formatSignedPct(row.original.avg_drawdown_delta)}</Text>,
    },
    { id: 'avg_profit_factor', header: '平均 PF', size: 82, minSize: 76, accessorFn: (row) => row.avg_profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.avg_profit_factor, 2) },
    { id: 'avg_profit_factor_delta', header: 'PF 变化', size: 82, minSize: 76, accessorFn: (row) => row.avg_profit_factor_delta ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatSignedNumber(row.original.avg_profit_factor_delta, 2) },
    { id: 'trade_retention', header: '交易保留', size: 92, minSize: 84, accessorFn: (row) => row.trade_retention ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.trade_retention) },
  ], []);
  const filterResultRunColumns = useMemo<ColumnDef<ParameterLabRow>[]>(() => [
    {
      id: 'run',
      header: 'Run',
      size: 210,
      minSize: 190,
      accessorFn: (row) => row.run_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{row.original.dataset_snapshot_id}</Text>
        </Space>
      ),
    },
    {
      id: 'filter',
      header: '过滤器',
      size: 200,
      minSize: 180,
      accessorFn: (row) => row.signal_filter_summary ?? '',
      cell: ({ row }) => row.original.signal_filter_summary ? <Tag color="blue">{row.original.signal_filter_summary}</Tag> : '--',
    },
    { id: 'total_return', header: '收益率', size: 92, minSize: 86, accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    { id: 'oos_total_return', header: 'OOS', size: 92, minSize: 86, accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_total_return) },
    { id: 'oos_excess_return', header: 'OOS超额', size: 100, minSize: 92, accessorFn: (row) => row.oos_excess_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_excess_return) },
    { id: 'max_drawdown', header: '回撤', size: 92, minSize: 86, accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    { id: 'profit_factor', header: 'PF', size: 72, minSize: 68, accessorFn: (row) => row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.profit_factor, 2) },
    { id: 'trade_count', header: '交易数', size: 76, minSize: 70, accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    { id: 'created_at', header: '时间', size: 140, minSize: 128, accessorFn: (row) => row.created_at, cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: 'actions',
      header: '操作',
      size: 126,
      minSize: 116,
      enableSorting: false,
      cell: ({ row }) => (
        <Space size={6}>
          <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开</Button>
          <Button size="small" onClick={() => void addRunToCompare(row.original.run_id)}>对比</Button>
        </Space>
      ),
    },
  ], [addRunToCompare, onOpenRun]);
  const primaryTradeAttributionBuckets = useMemo(() => {
    if (!tradeAttribution) {
      return [];
    }
    return (tradeAttribution.buckets ?? [])
      .filter((bucket) => isPrimaryTradeAttributionBucket(bucket, tradeAttribution.summary.trade_count))
      .sort((left, right) => tradeAttributionBucketIssueScore(right) - tradeAttributionBucketIssueScore(left))
      .slice(0, 12);
  }, [tradeAttribution]);
  const primaryEarlyFailAttributionBuckets = useMemo(() => {
    if (!tradeAttribution) {
      return [];
    }
    return (tradeAttribution.early_fail_buckets ?? [])
      .filter(isPrimaryEarlyFailAttributionBucket)
      .sort((left, right) => earlyFailAttributionScore(right) - earlyFailAttributionScore(left))
      .slice(0, 12);
  }, [tradeAttribution]);
  const fallbackEarlyFailAttributionBuckets = useMemo(() => {
    if (!tradeAttribution || primaryEarlyFailAttributionBuckets.length) {
      return [];
    }
    return (tradeAttribution.early_fail_buckets ?? [])
      .filter(isFallbackEarlyFailAttributionBucket)
      .sort((left, right) => earlyFailAttributionScore(right) - earlyFailAttributionScore(left))
      .slice(0, 12);
  }, [tradeAttribution, primaryEarlyFailAttributionBuckets.length]);
  const visibleEarlyFailAttributionBuckets = primaryEarlyFailAttributionBuckets.length
    ? primaryEarlyFailAttributionBuckets
    : fallbackEarlyFailAttributionBuckets;
  const primaryStopLossAttributionBuckets = useMemo(() => {
    if (!tradeAttribution) {
      return [];
    }
    return (tradeAttribution.stop_loss_buckets ?? [])
      .filter(isPrimaryStopLossAttributionBucket)
      .sort((left, right) => stopLossAttributionScore(right) - stopLossAttributionScore(left))
      .slice(0, 12);
  }, [tradeAttribution]);
  const pathStopLossAttributionBuckets = useMemo(() => {
    if (!tradeAttribution) {
      return [];
    }
    return (tradeAttribution.stop_loss_buckets ?? [])
      .filter(isPathStopLossAttributionBucket)
      .sort((left, right) => stopLossAttributionScore(right) - stopLossAttributionScore(left))
      .slice(0, 12);
  }, [tradeAttribution]);
  const stopLossAttributionConclusion = useMemo(
    () => buildStopLossAttributionConclusion(pathStopLossAttributionBuckets.length ? pathStopLossAttributionBuckets : primaryStopLossAttributionBuckets),
    [pathStopLossAttributionBuckets, primaryStopLossAttributionBuckets],
  );
  const earlyFailAttributionConclusion = useMemo(
    () => buildEarlyFailAttributionConclusion(visibleEarlyFailAttributionBuckets),
    [visibleEarlyFailAttributionBuckets],
  );
  const earlyFailBaselineText = useMemo(() => {
    if (!tradeAttribution) {
      return '总体早败率 --';
    }
    return `IS总体早败率 ${formatPct(tradeAttribution.summary.is_early_fail_rate)} / OOS总体早败率 ${formatPct(tradeAttribution.summary.oos_early_fail_rate)}；路径样本 IS ${formatNumber(tradeAttribution.summary.early_path_is_trade_count, 0)} / OOS ${formatNumber(tradeAttribution.summary.early_path_oos_trade_count, 0)}`;
  }, [tradeAttribution]);
  const earlyFailAttributionColumns = useMemo<ColumnDef<EarlyFailAttributionBucket>[]>(() => [
    {
      id: 'judgement',
      header: '判断',
      size: 100,
      minSize: 90,
      accessorFn: (row) => earlyFailAttributionScore(row),
      cell: ({ row }) => {
        const judgement = earlyFailAttributionJudgement(row.original);
        return <Tag color={judgement.color}>{judgement.text}</Tag>;
      },
    },
    {
      id: 'bucket_family',
      header: '类型',
      size: 70,
      minSize: 64,
      accessorFn: (row) => row.bucket_family,
      cell: ({ row }) => <Tag color={row.original.bucket_family === 'combo' ? 'purple' : 'blue'}>{row.original.bucket_family === 'combo' ? '组合' : '单项'}</Tag>,
    },
    {
      id: 'dimension',
      header: '入场前维度',
      size: 150,
      minSize: 130,
      accessorFn: (row) => tradeAttributionDimensionLabel(row.dimension),
      cell: ({ row }) => (
        <Tooltip title={tradeAttributionDimensionHelp(row.original.dimension)}>
          <Text strong>{tradeAttributionDimensionLabel(row.original.dimension)}</Text>
        </Tooltip>
      ),
    },
    {
      id: 'label',
      header: '分桶',
      size: 190,
      minSize: 170,
      accessorFn: (row) => tradeAttributionBucketLabel(row),
      cell: ({ row }) => <Tag color={row.original.is_early_fail_rate_delta >= 0.05 ? 'red' : row.original.is_early_fail_rate_delta <= -0.03 ? 'green' : 'blue'}>{tradeAttributionBucketLabel(row.original)}</Tag>,
    },
    { id: 'is_trade_count', header: 'IS交易', size: 82, minSize: 76, accessorFn: (row) => row.is_trade_count, cell: ({ row }) => row.original.is_trade_count },
    { id: 'is_early_fail_count', header: 'IS早败', size: 82, minSize: 76, accessorFn: (row) => row.is_early_fail_count, cell: ({ row }) => row.original.is_early_fail_count },
    { id: 'is_early_fail_rate', header: 'IS早败率', size: 96, minSize: 88, accessorFn: (row) => row.is_early_fail_rate, cell: ({ row }) => formatPct(row.original.is_early_fail_rate) },
    {
      id: 'is_early_fail_rate_delta',
      header: '高于总体',
      size: 96,
      minSize: 88,
      accessorFn: (row) => row.is_early_fail_rate_delta,
      cell: ({ row }) => <Text type={row.original.is_early_fail_rate_delta > 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.is_early_fail_rate_delta)}</Text>,
    },
    { id: 'is_first_bar_adverse_rate', header: '首根反向率', size: 112, minSize: 100, accessorFn: (row) => row.is_first_bar_adverse_rate, cell: ({ row }) => formatPct(row.original.is_first_bar_adverse_rate) },
    { id: 'is_early_fail_stop_loss_rate', header: '早败后止损率', size: 126, minSize: 114, accessorFn: (row) => row.is_early_fail_stop_loss_rate, cell: ({ row }) => <Text type="danger">{formatPct(row.original.is_early_fail_stop_loss_rate)}</Text> },
    { id: 'oos_trade_count', header: 'OOS交易', size: 88, minSize: 80, accessorFn: (row) => row.oos_trade_count, cell: ({ row }) => row.original.oos_trade_count },
    { id: 'oos_early_fail_count', header: 'OOS早败', size: 92, minSize: 84, accessorFn: (row) => row.oos_early_fail_count, cell: ({ row }) => row.original.oos_early_fail_count },
    { id: 'oos_early_fail_rate', header: 'OOS早败率', size: 108, minSize: 98, accessorFn: (row) => row.oos_early_fail_rate, cell: ({ row }) => formatPct(row.original.oos_early_fail_rate) },
    {
      id: 'oos_early_fail_rate_delta',
      header: 'OOS高于总体',
      size: 120,
      minSize: 108,
      accessorFn: (row) => row.oos_early_fail_rate_delta ?? 0,
      cell: ({ row }) => <Text type={Number(row.original.oos_early_fail_rate_delta ?? 0) > 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.oos_early_fail_rate_delta)}</Text>,
    },
    {
      id: 'oos_sample',
      header: 'OOS样本',
      size: 96,
      minSize: 88,
      accessorFn: (row) => row.oos_trade_count,
      cell: ({ row }) => (
        row.original.oos_trade_count >= 10
          ? <Tag color="green">可复验</Tag>
          : <Tag color="orange">不足10</Tag>
      ),
    },
  ], []);
  const stopLossAttributionColumns = useMemo<ColumnDef<StopLossAttributionBucket>[]>(() => [
    {
      id: 'judgement',
      header: '判断',
      size: 100,
      minSize: 90,
      accessorFn: (row) => stopLossAttributionScore(row),
      cell: ({ row }) => {
        const judgement = stopLossAttributionJudgement(row.original);
        return <Tag color={judgement.color}>{judgement.text}</Tag>;
      },
    },
    {
      id: 'bucket_family',
      header: '类型',
      size: 70,
      minSize: 64,
      accessorFn: (row) => row.bucket_family,
      cell: ({ row }) => <Tag color={row.original.bucket_family === 'combo' ? 'purple' : 'blue'}>{row.original.bucket_family === 'combo' ? '组合' : '单项'}</Tag>,
    },
    {
      id: 'dimension',
      header: '维度',
      size: 150,
      minSize: 130,
      accessorFn: (row) => tradeAttributionDimensionLabel(row.dimension),
      cell: ({ row }) => (
        <Tooltip title={tradeAttributionDimensionHelp(row.original.dimension)}>
          <Text strong>{tradeAttributionDimensionLabel(row.original.dimension)}</Text>
        </Tooltip>
      ),
    },
    {
      id: 'label',
      header: '分桶',
      size: 190,
      minSize: 170,
      accessorFn: (row) => tradeAttributionBucketLabel(row as unknown as TradeAttributionBucket),
      cell: ({ row }) => <Tag color={row.original.is_stop_loss_rate_delta >= 0.05 ? 'red' : row.original.is_stop_loss_rate_delta <= -0.03 ? 'green' : 'blue'}>{tradeAttributionBucketLabel(row.original as unknown as TradeAttributionBucket)}</Tag>,
    },
    { id: 'is_trade_count', header: 'IS交易', size: 82, minSize: 76, accessorFn: (row) => row.is_trade_count, cell: ({ row }) => row.original.is_trade_count },
    { id: 'is_stop_loss_count', header: 'IS止损', size: 82, minSize: 76, accessorFn: (row) => row.is_stop_loss_count, cell: ({ row }) => row.original.is_stop_loss_count },
    { id: 'is_stop_loss_rate', header: 'IS止损率', size: 96, minSize: 88, accessorFn: (row) => row.is_stop_loss_rate, cell: ({ row }) => formatPct(row.original.is_stop_loss_rate) },
    {
      id: 'is_stop_loss_net_pnl',
      header: 'IS止损亏损',
      size: 112,
      minSize: 102,
      accessorFn: (row) => row.is_stop_loss_net_pnl,
      cell: ({ row }) => <Text type="danger">{formatNumber(row.original.is_stop_loss_net_pnl, 2)}</Text>,
    },
    { id: 'is_stop_loss_loss_share', header: 'IS亏损占比', size: 104, minSize: 94, accessorFn: (row) => row.is_stop_loss_loss_share, cell: ({ row }) => formatPct(row.original.is_stop_loss_loss_share) },
    {
      id: 'is_stop_loss_rate_delta',
      header: '高于总体',
      size: 96,
      minSize: 88,
      accessorFn: (row) => row.is_stop_loss_rate_delta,
      cell: ({ row }) => <Text type={row.original.is_stop_loss_rate_delta > 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.is_stop_loss_rate_delta)}</Text>,
    },
    { id: 'is_avg_loss_return_pct', header: '止损均损', size: 96, minSize: 88, accessorFn: (row) => row.is_avg_loss_return_pct, cell: ({ row }) => <Text type="danger">{formatPct(row.original.is_avg_loss_return_pct)}</Text> },
    { id: 'oos_trade_count', header: 'OOS交易', size: 88, minSize: 80, accessorFn: (row) => row.oos_trade_count, cell: ({ row }) => row.original.oos_trade_count },
    { id: 'oos_stop_loss_count', header: 'OOS止损', size: 90, minSize: 82, accessorFn: (row) => row.oos_stop_loss_count, cell: ({ row }) => row.original.oos_stop_loss_count },
    { id: 'oos_stop_loss_rate', header: 'OOS止损率', size: 104, minSize: 94, accessorFn: (row) => row.oos_stop_loss_rate, cell: ({ row }) => formatPct(row.original.oos_stop_loss_rate) },
    {
      id: 'oos_stop_loss_net_pnl',
      header: 'OOS止损亏损',
      size: 126,
      minSize: 114,
      accessorFn: (row) => row.oos_stop_loss_net_pnl,
      cell: ({ row }) => <Text type="danger">{formatNumber(row.original.oos_stop_loss_net_pnl, 2)}</Text>,
    },
    { id: 'oos_stop_loss_loss_share', header: 'OOS亏损占比', size: 116, minSize: 104, accessorFn: (row) => row.oos_stop_loss_loss_share, cell: ({ row }) => formatPct(row.original.oos_stop_loss_loss_share) },
    {
      id: 'oos_stop_loss_rate_delta',
      header: 'OOS高于总体',
      size: 120,
      minSize: 108,
      accessorFn: (row) => row.oos_stop_loss_rate_delta ?? 0,
      cell: ({ row }) => <Text type={Number(row.original.oos_stop_loss_rate_delta ?? 0) > 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.oos_stop_loss_rate_delta)}</Text>,
    },
  ], []);
  const tradeAttributionBucketColumns = useMemo<ColumnDef<TradeAttributionBucket>[]>(() => [
    {
      id: 'judgement',
      header: '判断',
      size: 92,
      minSize: 82,
      accessorFn: (row) => tradeAttributionBucketIssueScore(row),
      cell: ({ row }) => {
        const judgement = tradeAttributionBucketJudgement(row.original);
        return <Tag color={judgement.color}>{judgement.text}</Tag>;
      },
    },
    {
      id: 'dimension',
      header: '维度',
      size: 150,
      minSize: 130,
      accessorFn: (row) => tradeAttributionDimensionLabel(row.dimension),
      cell: ({ row }) => (
        <Tooltip title={tradeAttributionDimensionHelp(row.original.dimension)}>
          <Text strong>{tradeAttributionDimensionLabel(row.original.dimension)}</Text>
        </Tooltip>
      ),
    },
    {
      id: 'label',
      header: '分桶',
      size: 220,
      minSize: 180,
      accessorFn: (row) => tradeAttributionBucketLabel(row),
      cell: ({ row }) => <Tag color={tradeAttributionBucketTagColor(row.original)}>{tradeAttributionBucketLabel(row.original)}</Tag>,
    },
    { id: 'is_trade_count', header: 'IS交易', size: 82, minSize: 76, accessorFn: (row) => row.is_trade_count, cell: ({ row }) => row.original.is_trade_count },
    { id: 'is_win_rate', header: 'IS胜率', size: 86, minSize: 78, accessorFn: (row) => row.is_win_rate, cell: ({ row }) => formatPct(row.original.is_win_rate) },
    {
      id: 'is_net_pnl',
      header: 'IS净贡献',
      size: 112,
      minSize: 102,
      accessorFn: (row) => row.is_net_pnl,
      cell: ({ row }) => <Text type={row.original.is_net_pnl < 0 ? 'danger' : 'success'}>{formatNumber(row.original.is_net_pnl, 2)}</Text>,
    },
    { id: 'is_profit_factor', header: 'IS PF', size: 76, minSize: 70, accessorFn: (row) => row.is_profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.is_profit_factor, 2) },
    {
      id: 'is_pf_delta',
      header: 'IS PF差',
      size: 86,
      minSize: 78,
      accessorFn: (row) => row.is_pf_delta ?? 0,
      cell: ({ row }) => <Text type={Number(row.original.is_pf_delta ?? 0) < 0 ? 'danger' : 'success'}>{formatSignedNumber(row.original.is_pf_delta, 2)}</Text>,
    },
    {
      id: 'is_avg_return_delta',
      header: 'IS均收益差',
      size: 112,
      minSize: 102,
      accessorFn: (row) => row.is_avg_return_delta,
      cell: ({ row }) => <Text type={row.original.is_avg_return_delta < 0 ? 'danger' : 'success'}>{formatSignedPct(row.original.is_avg_return_delta)}</Text>,
    },
    {
      id: 'is_loss_contribution',
      header: 'IS毛亏损占比',
      size: 122,
      minSize: 112,
      accessorFn: (row) => row.is_loss_contribution,
      cell: ({ row }) => (
        <Tooltip title="该桶内亏损交易的毛亏损，占全部 IS 毛亏损的比例；不扣除同桶盈利，所以不能单独代表这个桶不好。">
          <Text>{formatPct(row.original.is_loss_contribution)}</Text>
        </Tooltip>
      ),
    },
    { id: 'oos_trade_count', header: 'OOS交易', size: 88, minSize: 80, accessorFn: (row) => row.oos_trade_count, cell: ({ row }) => row.original.oos_trade_count },
    {
      id: 'oos_net_pnl',
      header: 'OOS净贡献',
      size: 116,
      minSize: 106,
      accessorFn: (row) => row.oos_net_pnl,
      cell: ({ row }) => <Text type={row.original.oos_net_pnl < 0 ? 'danger' : 'success'}>{formatNumber(row.original.oos_net_pnl, 2)}</Text>,
    },
    { id: 'oos_profit_factor', header: 'OOS PF', size: 86, minSize: 78, accessorFn: (row) => row.oos_profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.oos_profit_factor, 2) },
    {
      id: 'oos_pf_delta',
      header: 'OOS PF差',
      size: 94,
      minSize: 84,
      accessorFn: (row) => row.oos_pf_delta ?? 0,
      cell: ({ row }) => <Text type={Number(row.original.oos_pf_delta ?? 0) < 0 ? 'danger' : 'success'}>{formatSignedNumber(row.original.oos_pf_delta, 2)}</Text>,
    },
    {
      id: 'oos_loss_contribution',
      header: 'OOS毛亏损占比',
      size: 130,
      minSize: 118,
      accessorFn: (row) => row.oos_loss_contribution,
      cell: ({ row }) => (
        <Tooltip title="该桶内亏损交易的毛亏损，占全部 OOS 毛亏损的比例；只辅助定位亏损来源。">
          <Text>{formatPct(row.original.oos_loss_contribution)}</Text>
        </Tooltip>
      ),
    },
  ], []);
  const riskCompareColumns = useMemo<ColumnDef<ParameterGroupView>[]>(() => [
    {
      id: 'risk_points',
      header: '风险 / 杠杆',
      size: 240,
      minSize: 220,
      enableSorting: false,
      cell: ({ row }) => renderParameterPoints(parameterGroupRiskPoints(row.original), 'blue'),
    },
    { id: 'research_score', header: '研究分', accessorFn: (row) => row.research_score, cell: ({ row }) => formatNumber(row.original.research_score, 1) },
    { id: 'avg_oos_total_return', header: '平均 OOS', accessorFn: (row) => row.avg_oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.avg_oos_total_return) },
    { id: 'avg_gap', header: '平均 Gap', accessorFn: (row) => row.avg_gap ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(row.original.avg_gap) },
    { id: 'worst_max_drawdown', header: '最差回撤', accessorFn: (row) => row.worst_max_drawdown, cell: ({ row }) => formatPct(row.original.worst_max_drawdown) },
    {
      id: 'oos_drawdown_ratio',
      header: 'OOS/DD',
      accessorFn: (row) => (row.avg_oos_total_return ?? row.avg_total_return) / Math.max(row.worst_max_drawdown, 0.01),
      cell: ({ row }) => formatNumber((row.original.avg_oos_total_return ?? row.original.avg_total_return) / Math.max(row.original.worst_max_drawdown, 0.01), 2),
    },
    { id: 'avg_profit_factor', header: '平均 PF', accessorFn: (row) => row.avg_profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.avg_profit_factor, 2) },
    { id: 'min_trade_count', header: '最少交易', accessorFn: (row) => row.min_trade_count, cell: ({ row }) => row.original.min_trade_count },
    {
      id: 'classification',
      header: '分类',
      accessorFn: (row) => row.classification,
      cell: ({ row }) => <Tag color={parameterGroupClassificationColor(row.original.classification)}>{parameterGroupClassificationText(row.original.classification)}</Tag>,
    },
    {
      id: 'actions',
      header: '操作',
      enableSorting: false,
      cell: ({ row }) => (
        <Space>
          <Button size="small" onClick={() => setSelectedParameterGroupKey(row.original.group_key)}>详情</Button>
          {row.original.representative_run_id ? (
            <Button size="small" onClick={() => onOpenRun(row.original.representative_run_id as string)}>代表 Run</Button>
          ) : null}
        </Space>
      ),
    },
  ], [onOpenRun]);
  const parameterGroupRunColumns = useMemo<ColumnDef<ParameterGroupRunView>[]>(() => [
    {
      id: 'run_id',
      header: 'Run',
      size: 260,
      minSize: 220,
      accessorFn: (row) => row.run_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{row.original.batch_id ?? row.original.experiment_id ?? '--'}</Text>
        </Space>
      ),
    },
    { id: 'total_return', header: '总收益', accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    { id: 'oos_total_return', header: 'OOS', accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_total_return) },
    { id: 'gap', header: 'Gap', accessorFn: (row) => row.gap ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(row.original.gap) },
    { id: 'max_drawdown', header: '回撤', accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    { id: 'profit_factor', header: 'PF', accessorFn: (row) => row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.profit_factor, 2) },
    { id: 'trade_count', header: '交易数', accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    { id: 'created_at', header: '时间', accessorFn: (row) => row.created_at, cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: 'actions',
      header: '操作',
      enableSorting: false,
      cell: ({ row }) => (
        <Space size={6}>
          <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开分析</Button>
          <Button size="small" onClick={() => void addRunToCompare(row.original.run_id)}>对比</Button>
        </Space>
      ),
    },
  ], [addRunToCompare, onOpenRun]);
  const drawdownProtectionComparisonColumns = useMemo<ColumnDef<DrawdownProtectionComparisonRow>[]>(() => [
    {
      id: 'verdict',
      header: '判断',
      size: 92,
      minSize: 86,
      accessorFn: (row) => row.verdict,
      cell: ({ row }) => {
        if (row.original.verdict === 'baseline') {
          return <Tag>基准</Tag>;
        }
        if (row.original.verdict === 'improved') {
          return <Tag color="green">候选</Tag>;
        }
        if (row.original.verdict === 'worse') {
          return <Tag color="red">变差</Tag>;
        }
        return <Tag color="gold">权衡</Tag>;
      },
    },
    {
      id: 'protection',
      header: '保护方案',
      size: 220,
      minSize: 190,
      accessorFn: (row) => row.protection,
      cell: ({ row }) => <Tag color={row.original.verdict === 'baseline' ? 'default' : 'orange'}>{row.original.protection}</Tag>,
    },
    { id: 'oos_total_return', header: 'OOS', size: 96, minSize: 88, accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_total_return) },
    {
      id: 'oos_delta',
      header: 'OOS 变化',
      size: 96,
      minSize: 88,
      accessorFn: (row) => row.oos_delta ?? 0,
      cell: ({ row }) => <Text type={Number(row.original.oos_delta ?? 0) >= 0 ? 'success' : 'danger'}>{formatSignedPct(row.original.oos_delta)}</Text>,
    },
    { id: 'max_drawdown', header: '最大回撤', size: 104, minSize: 96, accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    {
      id: 'drawdown_delta',
      header: '回撤变化',
      size: 104,
      minSize: 96,
      accessorFn: (row) => row.drawdown_delta ?? 0,
      cell: ({ row }) => <Text type={Number(row.original.drawdown_delta ?? 0) <= 0 ? 'success' : 'danger'}>{formatSignedPct(row.original.drawdown_delta)}</Text>,
    },
    { id: 'profit_factor', header: 'PF', size: 74, minSize: 68, accessorFn: (row) => row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.profit_factor, 2) },
    { id: 'profit_factor_delta', header: 'PF 变化', size: 84, minSize: 78, accessorFn: (row) => row.profit_factor_delta ?? 0, cell: ({ row }) => formatSignedNumber(row.original.profit_factor_delta, 2) },
    { id: 'trade_count', header: '交易数', size: 82, minSize: 76, accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    { id: 'trade_retention', header: '交易保留', size: 96, minSize: 88, accessorFn: (row) => row.trade_retention ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.trade_retention) },
    { id: 'total_return', header: '总收益', size: 96, minSize: 88, accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    {
      id: 'actions',
      header: '操作',
      size: 92,
      minSize: 84,
      enableSorting: false,
      cell: ({ row }) => <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开</Button>,
    },
  ], [onOpenRun]);
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
      id: 'parameter_summary',
      header: '参数摘要',
      size: 88,
      minSize: 88,
      accessorFn: (row) => row.parameter_summary || `${row.fast_period ?? ''}/${row.slow_period ?? ''}`,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text>{row.original.parameter_summary || `${row.original.fast_period ?? '--'} / ${row.original.slow_period ?? '--'}`}</Text>
          {row.original.signal_filter_summary ? <Tag color="blue">{row.original.signal_filter_summary}</Tag> : null}
          {row.original.execution_protection_summary ? <Tag color="orange">{row.original.execution_protection_summary}</Tag> : null}
        </Space>
      ),
    },
    { id: 'leverage', header: '杠杆', size: 68, minSize: 68, accessorFn: (row) => row.leverage ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.leverage ?? '--' },
    { id: 'research_score', header: '评分', size: 76, minSize: 72, accessorFn: (row) => scoreResearchRun(row).score, cell: ({ row }) => formatNumber(scoreResearchRun(row.original).score, 1) },
    { id: 'total_return', header: '收益率', size: 104, minSize: 104, accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    { id: 'max_drawdown', header: '最大回撤', size: 104, minSize: 104, accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    { id: 'excess_return', header: '超额收益', size: 108, minSize: 108, accessorFn: (row) => row.excess_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.excess_return) },
    { id: 'oos_total_return', header: '样本外收益', size: 120, minSize: 120, accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_total_return) },
    { id: 'oos_excess_return', header: '样本外超额', size: 120, minSize: 120, accessorFn: (row) => row.oos_excess_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_excess_return) },
    { id: 'profit_factor', header: 'PF', size: 76, minSize: 72, accessorFn: (row) => row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.profit_factor, 2) },
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
      size: 220,
      minSize: 210,
      enableSorting: false,
      cell: ({ row }) => {
        const isTracked = trackedRunNotesByRunId.has(row.original.run_id);
        return (
          <Space>
            <Button size="small" onClick={() => onOpenRun(row.original.run_id)}>打开分析</Button>
            <Button size="small" disabled={isTracked} loading={savingResearchNote} onClick={() => void freezeRunForTracking(row.original)}>
              {isTracked ? '已追踪' : '冻结'}
            </Button>
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
        );
      },
    },
  ], [autoLabelsByRunId, batchManualDecisionStatusByRunId, batchManualLabelsByRunId, freezeRunForTracking, manualLabelsByRunId, onDeleteRun, onOpenRun, savingResearchNote, trackedRunNotesByRunId, workspaceMode]);
  const researchRunColumns = useMemo<ColumnDef<ResearchRunCandidate>[]>(() => [
    {
      id: 'run',
      header: 'Run',
      size: 220,
      minSize: 200,
      accessorFn: (candidate) => candidate.row.run_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.row.run_id)}</Text>
          <Text type="secondary">{row.original.row.symbol} · {row.original.row.timeframe.toUpperCase()}</Text>
        </Space>
      ),
    },
    {
      id: 'parameter_summary',
      header: '参数',
      size: 260,
      minSize: 220,
      accessorFn: (candidate) => candidate.row.parameter_summary,
      cell: ({ row }) => row.original.row.parameter_summary,
    },
    {
      id: 'tags',
      header: '判断',
      size: 220,
      minSize: 200,
      enableSorting: false,
      cell: ({ row }) => (
        <Space size={[4, 4]} wrap>
          {row.original.tags.map((tag) => (
            <Tag
              key={`${row.original.row.run_id}-${tag}`}
              color={tag === 'Gap 大' ? 'orange' : tag === 'OOS 强' ? 'blue' : tag === 'Gap 小' ? 'green' : 'default'}
            >
              {tag}
            </Tag>
          ))}
        </Space>
      ),
    },
    { id: 'score', header: '研究分', size: 92, minSize: 88, accessorFn: (candidate) => candidate.score, cell: ({ row }) => formatNumber(row.original.score, 2) },
    { id: 'oos_total_return', header: 'OOS', size: 96, minSize: 92, accessorFn: (candidate) => candidate.row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.row.oos_total_return) },
    { id: 'is_oos_gap', header: 'Gap', size: 96, minSize: 92, accessorFn: (candidate) => candidate.gap ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(row.original.gap) },
    { id: 'max_drawdown', header: '回撤', size: 96, minSize: 92, accessorFn: (candidate) => candidate.row.max_drawdown, cell: ({ row }) => formatPct(row.original.row.max_drawdown) },
    { id: 'oos_trade_count', header: 'OOS 交易', size: 92, minSize: 88, accessorFn: (candidate) => candidate.row.oos_trade_count ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.row.oos_trade_count ?? '--' },
    { id: 'profit_factor', header: 'PF', size: 80, minSize: 76, accessorFn: (candidate) => candidate.row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.row.profit_factor, 2) },
    { id: 'total_return', header: '总收益', size: 96, minSize: 92, accessorFn: (candidate) => candidate.row.total_return, cell: ({ row }) => formatPct(row.original.row.total_return) },
    {
      id: 'actions',
      header: '操作',
      size: 320,
      minSize: 300,
      enableSorting: false,
      cell: ({ row }) => {
        const run = row.original.row;
        const canRunNeighborhood = run.strategy_name === 'ema_pullback_atr_v2' && Boolean(run.trend_fast_period && run.trend_slow_period);
        const isTracked = trackedRunNotesByRunId.has(run.run_id);
        return (
          <Space size={6}>
            <Button size="small" onClick={() => onOpenRun(run.run_id)}>打开分析</Button>
            <Button size="small" disabled={isTracked} loading={savingResearchNote} onClick={() => void freezeRunForTracking(run)}>
              {isTracked ? '已追踪' : '冻结'}
            </Button>
            <Button size="small" disabled={!canRunNeighborhood} onClick={() => setNeighborhoodSourceRunId(run.run_id)}>看邻域</Button>
            <Tooltip title={canRunNeighborhood ? '固定 tol/sl/rr/杠杆，只扩展趋势快慢周期邻域' : '仅 v2 Run 可跑趋势周期邻域'}>
              <Button
                size="small"
                disabled={!canRunNeighborhood}
                loading={neighborhoodRunId === run.run_id}
                onClick={() => onRunTrendNeighborhood(run)}
              >
                跑邻域
              </Button>
            </Tooltip>
          </Space>
        );
      },
    },
  ], [freezeRunForTracking, neighborhoodRunId, onOpenRun, onRunTrendNeighborhood, savingResearchNote, trackedRunNotesByRunId]);
  const trackingRunColumns = useMemo<ColumnDef<ParameterLabRow>[]>(() => [
    {
      id: 'run',
      header: 'Run',
      size: 220,
      minSize: 200,
      accessorFn: (row) => row.run_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text strong>{shortRunId(row.original.run_id)}</Text>
          <Text type="secondary">{row.original.symbol} · {row.original.timeframe.toUpperCase()}</Text>
        </Space>
      ),
    },
    {
      id: 'parameter_summary',
      header: '冻结参数',
      size: 280,
      minSize: 240,
      accessorFn: (row) => row.parameter_summary,
      cell: ({ row }) => row.original.parameter_summary,
    },
    {
      id: 'decision',
      header: '追踪状态',
      size: 160,
      minSize: 140,
      enableSorting: false,
      cell: ({ row }) => {
        const note = trackedRunNotesByRunId.get(row.original.run_id);
        return (
          <Space size={[4, 4]} wrap>
            <Tag color={decisionStatusColor(note?.decision_status)}>{decisionStatusText(note?.decision_status)}</Tag>
            {note?.labels.map((label) => (
              <Tag key={`${note.note_id}-${label}`} color={label === 'tracking' ? 'purple' : 'blue'}>
                {researchLabelText(label)}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    { id: 'research_score', header: '评分', size: 76, minSize: 72, accessorFn: (row) => scoreResearchRun(row).score, cell: ({ row }) => formatNumber(scoreResearchRun(row.original).score, 1) },
    { id: 'total_return', header: '收益率', size: 96, minSize: 92, accessorFn: (row) => row.total_return, cell: ({ row }) => formatPct(row.original.total_return) },
    { id: 'oos_total_return', header: 'OOS', size: 96, minSize: 92, accessorFn: (row) => row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.oos_total_return) },
    { id: 'gap', header: 'Gap', size: 92, minSize: 88, accessorFn: (row) => runIsoosGap(row) ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(runIsoosGap(row.original)) },
    { id: 'max_drawdown', header: '回撤', size: 92, minSize: 88, accessorFn: (row) => row.max_drawdown, cell: ({ row }) => formatPct(row.original.max_drawdown) },
    { id: 'profit_factor', header: 'PF', size: 72, minSize: 68, accessorFn: (row) => row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.profit_factor, 2) },
    { id: 'trade_count', header: '交易数', size: 76, minSize: 72, accessorFn: (row) => row.trade_count, cell: ({ row }) => row.original.trade_count },
    {
      id: 'tracked_at',
      header: '冻结时间',
      size: 150,
      minSize: 140,
      accessorFn: (row) => trackedRunNotesByRunId.get(row.run_id)?.created_at ?? '',
      cell: ({ row }) => {
        const note = trackedRunNotesByRunId.get(row.original.run_id);
        return note ? formatDateTime(note.created_at) : '--';
      },
    },
    {
      id: 'actions',
      header: '操作',
      size: 300,
      minSize: 280,
      enableSorting: false,
      cell: ({ row }) => {
        const run = row.original;
        const canRunNeighborhood = run.strategy_name === 'ema_pullback_atr_v2' && Boolean(run.trend_fast_period && run.trend_slow_period);
        return (
          <Space size={6}>
            <Button size="small" onClick={() => onOpenRun(run.run_id)}>打开分析</Button>
            <Button
              size="small"
              disabled={!canRunNeighborhood}
              onClick={() => setNeighborhoodSourceRunId(run.run_id)}
            >
              看邻域
            </Button>
            <Tooltip title={canRunNeighborhood ? '基于冻结 Run 固定 tol/sl/rr/仓位/杠杆，只扩展趋势快慢周期邻域' : '仅 v2 Run 可跑趋势周期邻域'}>
              <Button
                size="small"
                disabled={!canRunNeighborhood}
                loading={neighborhoodRunId === run.run_id}
                onClick={() => void onRunTrendNeighborhood(run)}
              >
                跑邻域
              </Button>
            </Tooltip>
            <Button
              size="small"
              onClick={() => openDecisionModal(
                'run',
                run.run_id,
                `追踪 Run ${shortRunId(run.run_id)}`,
                { decision_status: 'observing', labels: ['frozen_run', 'tracking'] },
              )}
            >
              记录
            </Button>
          </Space>
        );
      },
    },
  ], [neighborhoodRunId, onOpenRun, onRunTrendNeighborhood, trackedRunNotesByRunId]);
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
  function openDecisionModal(targetType: string, targetId: string, title: string, initialValues: Record<string, unknown> = {}) {
    decisionForm.resetFields();
    decisionForm.setFieldsValue({ author: 'local', decision_status: 'candidate', labels: [], ...initialValues });
    setDecisionTarget({ targetType, targetId, title });
  }

  const batchParameterGroupColumns = useMemo<ColumnDef<NonNullable<ParameterExperimentBatchDetail['parameter_groups']>[number]>[]>(() => [
    {
      id: 'parameter_summary',
      header: '参数组',
      size: 260,
      minSize: 220,
      accessorFn: (row) => parameterGroupSummary(row),
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Text>{parameterGroupSummary(row.original)}</Text>
          {row.original.signal_filter_summary ? <Tag color="blue">{row.original.signal_filter_summary}</Tag> : null}
        </Space>
      ),
    },
    {
      id: 'labels',
      header: '参数组推荐标签',
      enableSorting: false,
      size: 240,
      minSize: 220,
      cell: ({ row }) => {
        const key = buildParameterGroupKey(row.original);
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
    { id: 'score', header: '总分', accessorFn: (row) => row.score, cell: ({ row }) => formatNumber(row.original.score, 1) },
    { id: 'confidence', header: '置信度', accessorFn: (row) => row.confidence, cell: ({ row }) => formatNumber(row.original.confidence, 1) },
    { id: 'avg_oos_total_return', header: '平均样本外收益', accessorFn: (row) => row.avg_oos_total_return, cell: ({ row }) => formatPct(row.original.avg_oos_total_return) },
    { id: 'is_oos_gap', header: 'IS/OOS 差', accessorFn: (row) => row.is_oos_gap ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.is_oos_gap) },
    { id: 'avg_max_drawdown', header: '平均最大回撤', accessorFn: (row) => row.avg_max_drawdown, cell: ({ row }) => formatPct(row.original.avg_max_drawdown) },
    { id: 'min_oos_trade_count', header: '最少 OOS 交易', accessorFn: (row) => row.min_oos_trade_count ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => row.original.min_oos_trade_count ?? '--' },
    { id: 'return_over_drawdown', header: '收益回撤比', accessorFn: (row) => row.return_over_drawdown, cell: ({ row }) => formatNumber(row.original.return_over_drawdown, 2) },
    { id: 'neighbor_stability_score', header: '邻域稳定度', accessorFn: (row) => row.neighbor_stability_score ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.neighbor_stability_score) },
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
                  `参数组 ${parameterGroupSummary(row.original)}`,
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
  const trendNeighborhoodColumns = useMemo<ColumnDef<NeighborhoodRunMatch>[]>(() => [
    {
      id: 'run',
      header: 'Run',
      size: 190,
      minSize: 180,
      accessorFn: (match) => match.row.run_id,
      cell: ({ row }) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            <Text strong={row.original.isSource}>{shortRunId(row.original.row.run_id)}</Text>
            {row.original.isSource ? <Tag color="blue">当前</Tag> : null}
          </Space>
          <Text type="secondary">{row.original.row.symbol} · {row.original.row.timeframe.toUpperCase()}</Text>
        </Space>
      ),
    },
    {
      id: 'periods',
      header: '趋势周期',
      size: 132,
      minSize: 124,
      accessorFn: (match) => `${match.row.trend_fast_period ?? ''}/${match.row.trend_slow_period ?? ''}`,
      cell: ({ row }) => `tf${row.original.row.trend_fast_period ?? '--'} / ts${row.original.row.trend_slow_period ?? '--'}`,
    },
    {
      id: 'delta',
      header: '偏移',
      size: 112,
      minSize: 104,
      accessorFn: (match) => match.distance,
      cell: ({ row }) => {
        const formatDelta = (value: number | null) => (value === null ? '--' : value > 0 ? `+${value}` : `${value}`);
        return `tf ${formatDelta(row.original.fastDelta)} / ts ${formatDelta(row.original.slowDelta)}`;
      },
    },
    { id: 'total_return', header: '收益率', size: 96, minSize: 92, accessorFn: (match) => match.row.total_return, cell: ({ row }) => formatPct(row.original.row.total_return) },
    { id: 'oos_total_return', header: 'OOS', size: 96, minSize: 92, accessorFn: (match) => match.row.oos_total_return ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatPct(row.original.row.oos_total_return) },
    { id: 'gap', header: 'Gap', size: 92, minSize: 88, accessorFn: (match) => runIsoosGap(match.row) ?? Number.POSITIVE_INFINITY, cell: ({ row }) => formatPct(runIsoosGap(row.original.row)) },
    { id: 'max_drawdown', header: '回撤', size: 92, minSize: 88, accessorFn: (match) => match.row.max_drawdown, cell: ({ row }) => formatPct(row.original.row.max_drawdown) },
    { id: 'trade_count', header: '交易数', size: 76, minSize: 72, accessorFn: (match) => match.row.trade_count, cell: ({ row }) => row.original.row.trade_count },
    { id: 'profit_factor', header: 'PF', size: 72, minSize: 68, accessorFn: (match) => match.row.profit_factor ?? Number.NEGATIVE_INFINITY, cell: ({ row }) => formatNumber(row.original.row.profit_factor, 2) },
    {
      id: 'actions',
      header: '操作',
      size: 92,
      minSize: 88,
      enableSorting: false,
      cell: ({ row }) => <Button size="small" onClick={() => onOpenRun(row.original.row.run_id)}>打开</Button>,
    },
  ], [onOpenRun]);

  const resultStats = useMemo(() => {
    const sourceRows = workspaceMode === 'batch'
      ? filteredBatchRunRows
      : workspaceMode === 'tracking'
        ? filteredTrackedRunRows
        : filteredExperimentRunRows;
    const baseRows = workspaceMode === 'batch'
      ? selectedBatchRows
      : workspaceMode === 'tracking'
        ? trackedRunRows
        : selectedExperimentRows;
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
  }, [allRows.length, filteredBatchRunRows, filteredExperimentRunRows, filteredTrackedRunRows, selectedBatchRows, selectedExperimentRows, trackedRunRows, workspaceMode]);

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
      <Card
        className="cbw-workspace-nav"
        title={(
          <Space direction="vertical" size={0}>
            <Text strong>参数实验工作区</Text>
            <Text type="secondary" style={{ fontWeight: 400 }}>按初筛池、研究池、稳定池组织研究动作，批次和实验明细保留在高级区。</Text>
          </Space>
        )}
        extra={(
          <Space wrap>
            {workspaceMode !== 'launch' ? (
              <Input
                placeholder="搜索 run / 数据集 / 标的 / 参数"
                value={parameterQuery}
                onChange={(event) => setParameterQuery(event.target.value)}
                style={{ width: 260 }}
              />
            ) : null}
            <Button onClick={() => void onRefreshExperiments()}>刷新状态</Button>
          </Space>
        )}
      >
        <Segmented<ParameterWorkspaceMode>
          block
          className="cbw-workbench-switcher"
          value={workspaceMode}
          onChange={setWorkspaceMode}
          options={[
            { label: '发起实验', value: 'launch' },
            { label: '初筛池', value: 'screening' },
            { label: '研究池', value: 'research' },
            { label: '稳定池', value: 'stable' },
          ]}
        />
      </Card>

      {runCompareRows.length ? (
        <Alert
          type={runCompareRows.length === 2 ? 'success' : 'info'}
          showIcon
          message={`Run 对比：已选择 ${runCompareRows.length} / 2`}
          description={runCompareSelectionText}
          action={(
            <Space>
              <Button size="small" disabled={!runCompareModel} onClick={() => setRunCompareOpen(true)}>打开对比</Button>
              <Button size="small" onClick={clearRunCompare}>清空</Button>
            </Space>
          )}
        />
      ) : null}

      {workspaceMode === 'launch' ? (
        <Card
          className="cbw-experiment-form-card"
          title="发起实验批次"
          extra={(
            <Space>
              <Button onClick={() => void onRefreshExperiments()}>刷新状态</Button>
            </Space>
          )}
        >
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            提交新的 EMA 参数实验批次。提交后回到下方工作区查看批次推荐、参数组和研究决策。
          </Paragraph>
          <Form form={experimentForm} layout="vertical" onFinish={(values) => void onSubmitExperiment(values as Record<string, unknown>)}>
            <Row gutter={12}>
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
              <Col span={24}>
                <Form.Item name="strategy_name" label="策略" rules={[{ required: true }]}>
                  <Segmented block options={STRATEGY_OPTIONS} />
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
              {experimentStrategyName === 'ema_pullback_atr_v2' ? (
                <>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="trend_fast_periods"
                      label="趋势快线候选"
                      rules={[
                        {
                          validator: async (_, value) => {
                            const message = validateIntegerListInput(value, '趋势快线候选');
                            if (message) {
                              throw new Error(message);
                            }
                            const slowValue = experimentForm.getFieldValue('trend_slow_periods');
                            const slowMessage = validateIntegerListInput(slowValue, '趋势慢线候选');
                            if (!slowMessage) {
                              const fastPeriods = parseIntegerList(value);
                              const slowPeriods = parseIntegerList(slowValue);
                              const invalidPair = fastPeriods.flatMap((fastPeriod) => (
                                slowPeriods.filter((slowPeriod) => fastPeriod >= slowPeriod).map((slowPeriod) => `${fastPeriod}/${slowPeriod}`)
                              ))[0];
                              if (invalidPair) {
                                throw new Error(`所有组合都必须满足趋势快线周期 < 趋势慢线周期，当前存在 ${invalidPair}`);
                              }
                            }
                          },
                        },
                      ]}
                    >
                      <Input placeholder="例如 8,13" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="trend_slow_periods"
                      label="趋势慢线候选"
                      rules={[
                        {
                          validator: async (_, value) => {
                            const message = validateIntegerListInput(value, '趋势慢线候选');
                            if (message) {
                              throw new Error(message);
                            }
                            const fastValue = experimentForm.getFieldValue('trend_fast_periods');
                            const fastMessage = validateIntegerListInput(fastValue, '趋势快线候选');
                            if (!fastMessage) {
                              const fastPeriods = parseIntegerList(fastValue);
                              const slowPeriods = parseIntegerList(value);
                              const invalidPair = fastPeriods.flatMap((fastPeriod) => (
                                slowPeriods.filter((slowPeriod) => fastPeriod >= slowPeriod).map((slowPeriod) => `${fastPeriod}/${slowPeriod}`)
                              ))[0];
                              if (invalidPair) {
                                throw new Error(`所有组合都必须满足趋势快线周期 < 趋势慢线周期，当前存在 ${invalidPair}`);
                              }
                            }
                          },
                        },
                      ]}
                    >
                      <Input placeholder="例如 34,55" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="atr_entry_tolerances"
                      label="ATR 入场容忍候选"
                      rules={[
                        {
                          validator: async (_, value) => {
                            const message = validateNonNegativeNumberListInput(value, 'ATR 入场容忍候选');
                            if (message) {
                              throw new Error(message);
                            }
                          },
                        },
                      ]}
                    >
                      <Input placeholder="例如 0.5,1.0" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="atr_stop_mults"
                      label="ATR 止损倍数候选"
                      rules={[
                        {
                          validator: async (_, value) => {
                            const message = validatePositiveNumberListInput(value, 'ATR 止损倍数候选');
                            if (message) {
                              throw new Error(message);
                            }
                          },
                        },
                      ]}
                    >
                      <Input placeholder="例如 1.5,2.0" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="risk_reward_ratios"
                      label="盈亏比候选"
                      rules={[
                        {
                          validator: async (_, value) => {
                            const message = validatePositiveNumberListInput(value, '盈亏比候选');
                            if (message) {
                              throw new Error(message);
                            }
                          },
                        },
                      ]}
                    >
                      <Input placeholder="例如 1.5,2.0" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Descriptions size="small" bordered column={2} style={{ marginTop: 30 }}>
                      <Descriptions.Item label="Entry EMA">21</Descriptions.Item>
                      <Descriptions.Item label="ATR">14</Descriptions.Item>
                      <Descriptions.Item label="Min ATR/Price">0.2%</Descriptions.Item>
                      <Descriptions.Item label="Min Stop">0.3%</Descriptions.Item>
                    </Descriptions>
                  </Col>
                </>
              ) : (
                <>
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
                </>
              )}
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
              <Form.Item noStyle shouldUpdate={(prev, current) => prev.strategy_name !== current.strategy_name || prev.qty_policy_ref !== current.qty_policy_ref}>
                {({ getFieldValue }) => {
                  const isV2 = getFieldValue('strategy_name') === 'ema_pullback_atr_v2';
                  const qtyPolicyRef = String(getFieldValue('qty_policy_ref') ?? 'percent_of_cash');
                  const showRiskPct = isV2 && usesRiskPct(qtyPolicyRef);
                  const showCashAllocation = !isV2 || usesCashAllocation(qtyPolicyRef);
                  return (
                    <>
                      {isV2 ? (
                        <Col xs={24} md={8} xl={4}>
                          <Form.Item name="qty_policy_ref" label="仓位模式" rules={[{ required: true, message: '请选择仓位模式' }]}>
                            <Select options={QTY_POLICY_OPTIONS} />
                          </Form.Item>
                        </Col>
                      ) : null}
                      {showRiskPct ? (
                        <Col xs={24} md={8} xl={4}>
                          <Form.Item name="risk_pct_per_trade" label="单笔风险比例" rules={[{ required: true, message: '请输入单笔风险比例' }]}>
                            <InputNumber min={0.001} max={0.99} step={0.001} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      ) : null}
                      {showCashAllocation ? (
                        <Col xs={24} md={8} xl={4}>
                          <Form.Item
                            name="cash_allocation_pct"
                            label={qtyPolicyRef === 'risk_pct_of_cash_allocation' ? '最多动用资金 (%)' : '资金使用比例 (%)'}
                            rules={[{ required: true, message: '请输入资金使用比例' }]}
                          >
                            <InputNumber min={0.01} max={100} step={1} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      ) : null}
                    </>
                  );
                }}
              </Form.Item>
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
      {workspaceMode === 'launch' ? (
        <Card
          className="cbw-launch-progress-card"
          title="最近批次进度"
          extra={<Button onClick={() => void onRefreshExperiments()}>刷新状态</Button>}
        >
          {recentBatches.length ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              {recentBatches.map((batch) => {
                const plannedRuns = batch.planned_run_count || 0;
                const completedRuns = batch.run_count || 0;
                const failedCount = batch.failed_experiment_count || 0;
                const isRunning = batch.status === 'pending' || batch.status === 'running';
                const percent = plannedRuns > 0
                  ? Math.min(100, Math.round(((completedRuns + failedCount) / plannedRuns) * 100))
                  : batch.status === 'success' ? 100 : 0;
                return (
                  <div className="cbw-batch-progress-row" key={batch.batch_id}>
                    <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
                      <Space wrap size={[8, 8]}>
                        <Text strong>{shortRunId(batch.batch_id)}</Text>
                        <Tag color={experimentStatusColor(batch.status)}>{experimentStatusText(batch.status)}</Tag>
                        <Text type="secondary">{experimentSearchTypeLabel(batch.search_type)} · {batch.snapshot_count} 快照</Text>
                      </Space>
                      <Space>
                        <Button
                          size="small"
                          onClick={() => {
                            setSelectedBatchId(batch.batch_id);
                            setWorkspaceMode('batch');
                          }}
                        >
                          查看明细
                        </Button>
                        {batch.status === 'success' ? (
                          <Button size="small" type="primary" onClick={() => setWorkspaceMode('screening')}>
                            去初筛池
                          </Button>
                        ) : null}
                      </Space>
                    </Flex>
                    <Progress
                      percent={percent}
                      status={batch.status === 'failed' ? 'exception' : batch.status === 'success' ? 'success' : 'active'}
                      showInfo
                    />
                    <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
                      <Text type="secondary">
                        Run {completedRuns} / {plannedRuns || '--'} · 失败实验 {failedCount}
                      </Text>
                      <Text type="secondary">{formatDateTime(batch.created_at)}</Text>
                    </Flex>
                    {isRunning ? (
                      <Text type="secondary">状态会自动刷新。</Text>
                    ) : null}
                  </div>
                );
              })}
            </Space>
          ) : (
            <Alert type="info" showIcon message="还没有提交过实验批次。" />
          )}
        </Card>
      ) : null}
      {workspaceMode !== 'launch' ? (
        <Card
          className="cbw-research-workbench"
          title={workspaceMode === 'screening' ? '初筛池' : workspaceMode === 'research' ? '研究池' : workspaceMode === 'stable' ? '稳定池' : '高级区'}
        >
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="当前结果" value={resultStats.runCount} suffix={`/ ${resultStats.baseCount}`} /></Card></Col>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="筛选命中" value={resultStats.filteredCount} /></Card></Col>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="平均收益率" value={resultStats.avgReturn === null ? '--' : formatPct(resultStats.avgReturn)} /></Card></Col>
              <Col xs={12} md={6}><Card size="small" className="cbw-summary-card"><Statistic className="cbw-summary-stat" title="最佳收益率" value={resultStats.bestReturn === null ? '--' : formatPct(resultStats.bestReturn)} /></Card></Col>
            </Row>
            {workspaceMode !== 'screening' && workspaceMode !== 'stable' ? (
              <Card size="small" className="cbw-filter-panel" title="筛选与定位">
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  {workspaceMode === 'research' ? (
                    <Space wrap>
                    <Select
                      showSearch
                      value={selectedResearchSubjectKey ?? undefined}
                      style={{ minWidth: 360 }}
                      placeholder="选择研究对象"
                      onChange={(value) => setSelectedResearchSubjectKey(value)}
                      options={researchSubjects.map((subject) => ({
                        label: `${subject.strategy_name} · ${subject.symbol} · ${subject.timeframe.toUpperCase()} · ${subject.validation_split_id}`,
                        value: subject.subject_key,
                      }))}
                    />
                    <Select
                      mode="multiple"
                      allowClear
                      value={researchClassificationFilter}
                      style={{ minWidth: 220 }}
                      placeholder="参数组分类"
                      onChange={setResearchClassificationFilter}
                      options={['robust_candidate', 'high_return_candidate', 'exploratory_candidate', 'excluded'].map((value) => ({
                        label: parameterGroupClassificationText(value),
                        value,
                      }))}
                    />
                    <Select
                      allowClear
                      value={researchQtyPolicyFilter ?? undefined}
                      style={{ minWidth: 180 }}
                      placeholder="仓位模式"
                      onChange={(value) => setResearchQtyPolicyFilter(value ?? null)}
                      options={Array.from(new Set(researchParameterGroups.map((group) => group.qty_policy_ref).filter((value): value is string => Boolean(value)))).map((value) => ({
                        label: value,
                        value,
                      }))}
                    />
                    </Space>
                  ) : null}
                  {workspaceMode === 'batch' && selectedBatchId === ALL_BATCHES ? (
                    <>
                      <Space wrap>
                      <Select
                        mode="multiple"
                        allowClear
                        value={batchDecisionStatusFilter}
                        style={{ minWidth: 200 }}
                        placeholder="批次状态"
                        onChange={setBatchDecisionStatusFilter}
                        options={availableBatchStatuses.map((status) => ({
                          label: BATCH_STATUS_TEXT[status] ?? status,
                          value: status,
                        }))}
                      />
                      <Select
                        mode="multiple"
                        allowClear
                        disabled={!availableBatchDecisionLabels.length}
                        value={batchDecisionLabelFilter}
                        style={{ minWidth: 230 }}
                        placeholder={availableBatchDecisionLabels.length ? '批次级人工标签' : '暂无批次级人工标签'}
                        onChange={setBatchDecisionLabelFilter}
                        options={availableBatchDecisionLabels.map((label) => ({
                          label: RESEARCH_LABEL_TEXT[label] ?? label,
                          value: label,
                        }))}
                      />
                      </Space>
                      <Text type="secondary">批次标签只匹配批次级 Research Note，不包含 Run 或参数组标签。</Text>
                    </>
                  ) : null}
                  {workspaceMode === 'batch' && selectedBatchId !== ALL_BATCHES ? (
                    <Space wrap>
                    <Select
                      mode="multiple"
                      allowClear
                      value={autoLabelFilter}
                      style={{ minWidth: 220 }}
                      placeholder="参数组自动标签"
                      onChange={setAutoLabelFilter}
                      options={availableAutoLabels.map((label) => ({
                        label: AUTO_GROUP_MEMBERSHIP_LABEL_TEXT[label] ?? label,
                        value: label,
                      }))}
                    />
                    <Select
                      mode="multiple"
                      allowClear
                      value={groupDecisionStatusFilter}
                      style={{ minWidth: 220 }}
                      placeholder="参数组决策状态"
                      onChange={setGroupDecisionStatusFilter}
                      options={DECISION_STATUS_OPTIONS}
                    />
                    <Select
                      mode="multiple"
                      allowClear
                      value={groupDecisionLabelFilter}
                      style={{ minWidth: 220 }}
                      placeholder="参数组人工标签"
                      onChange={setGroupDecisionLabelFilter}
                      options={availableGroupDecisionLabels.map((label) => ({
                        label: RESEARCH_LABEL_TEXT[label] ?? label,
                        value: label,
                      }))}
                    />
                    </Space>
                  ) : null}
                  {(workspaceMode === 'tracking' || workspaceMode === 'experiment' || workspaceMode === 'decisions' || workspaceMode === 'sensitivity') ? (
                    <Space wrap>
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
                    </Space>
                  ) : null}
                  {workspaceMode === 'batch' && selectedBatchId !== ALL_BATCHES ? (
                    <Space wrap>
                    <InputNumber
                      min={0}
                      max={100}
                      step={5}
                      style={{ width: 132 }}
                      value={minScoreFilter}
                      placeholder="最小总分"
                      onChange={(value) => setMinScoreFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={0}
                      max={100}
                      step={5}
                      style={{ width: 132 }}
                      value={minConfidenceFilter}
                      placeholder="最小置信度"
                      onChange={(value) => setMinConfidenceFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={0}
                      max={100}
                      step={5}
                      style={{ width: 146 }}
                      value={maxDrawdownFilter}
                      placeholder="最大回撤%"
                      onChange={(value) => setMaxDrawdownFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={0}
                      step={0.1}
                      style={{ width: 150 }}
                      value={minReturnDrawdownFilter}
                      placeholder="最小收益回撤比"
                      onChange={(value) => setMinReturnDrawdownFilter(value === null ? null : Number(value))}
                    />
                    <InputNumber
                      min={1}
                      max={100}
                      step={1}
                      style={{ width: 120 }}
                      value={topNFilter}
                      placeholder="Top N"
                      onChange={(value) => setTopNFilter(value === null ? null : Number(value))}
                    />
                    </Space>
                  ) : null}
                </Space>
              </Card>
            ) : null}

            {workspaceMode === 'screening' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="初筛 Run" value={filteredScreeningRuns.length} suffix={`/ ${screeningPoolRuns.length}`} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="值得研究" value={filteredScreeningRuns.filter((run) => run.auto_labels.includes('值得研究')).length} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="平均 OOS" value={formatPct(averageNullable(filteredScreeningRuns.map((run) => run.oos_total_return)))} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="平均评分" value={formatNumber(averageNullable(filteredScreeningRuns.map((run) => run.score)), 1)} /></Card></Col>
                </Row>
                {screeningRiskProfile.length ? (
                  <Card size="small" title="参数风险提示">
                    <Row gutter={[12, 12]}>
                      {screeningRiskProfile.map((item) => (
                        <Col xs={24} lg={12} xxl={8} key={item.key}>
                          <Alert
                            type={item.severity === 'danger' ? 'error' : 'warning'}
                            showIcon
                            message={(
                              <Space size={8} wrap>
                                <Text strong>{item.dimension}</Text>
                                <Tag color={item.severity === 'danger' ? 'red' : 'orange'}>{item.label}</Tag>
                                <Text>{item.severity === 'danger' ? '不建议继续扩大' : '谨慎复测'}</Text>
                              </Space>
                            )}
                            description={item.reason}
                          />
                        </Col>
                      ))}
                    </Row>
                  </Card>
                ) : null}
                <Card size="small" title="初筛池">
                  <Paragraph type="secondary">
                    汇总所有已落盘 run，用自动评分和标签排序。Run 是初筛证据，进入研究池后会升维成同一入场结构与风险配置的研究候选。
                  </Paragraph>
                  <Space direction="vertical" size={12} style={{ width: '100%', marginBottom: 12 }}>
                    <Space wrap>
                      <Select
                        mode="multiple"
                        allowClear
                        value={screeningLabelFilter}
                        style={{ minWidth: 260 }}
                        placeholder="标签"
                        onChange={setScreeningLabelFilter}
                        options={screeningLabelOptions.map((label) => ({ label: researchLabelText(label), value: label }))}
                      />
                      <Select
                        allowClear
                        value={screeningStrategyFilter ?? undefined}
                        style={{ minWidth: 190 }}
                        placeholder="策略"
                        onChange={(value) => setScreeningStrategyFilter(value ?? null)}
                        options={screeningStrategyOptions.map((strategy) => ({ label: strategy, value: strategy }))}
                      />
                      <Select
                        allowClear
                        value={screeningSymbolFilter ?? undefined}
                        style={{ minWidth: 180 }}
                        placeholder="标的"
                        onChange={(value) => setScreeningSymbolFilter(value ?? null)}
                        options={screeningSymbolOptions.map((symbol) => ({ label: symbol, value: symbol }))}
                      />
                      <InputNumber
                        min={0}
                        max={100}
                        step={1}
                        style={{ width: 120 }}
                        value={screeningMinScoreFilter}
                        placeholder="最低评分"
                        onChange={(value) => setScreeningMinScoreFilter(value === null ? null : Number(value))}
                      />
                      <InputNumber
                        step={5}
                        style={{ width: 128 }}
                        value={screeningMinOosReturnFilter}
                        placeholder="最低 OOS%"
                        onChange={(value) => setScreeningMinOosReturnFilter(value === null ? null : Number(value))}
                      />
                      <InputNumber
                        step={5}
                        style={{ width: 138 }}
                        value={screeningMinIsExcessReturnFilter}
                        placeholder="最低 IS超额%"
                        onChange={(value) => setScreeningMinIsExcessReturnFilter(value === null ? null : Number(value))}
                      />
                      <InputNumber
                        min={0}
                        step={5}
                        style={{ width: 128 }}
                        value={screeningMaxGapFilter}
                        placeholder="最大 Gap%"
                        onChange={(value) => setScreeningMaxGapFilter(value === null ? null : Number(value))}
                      />
                      <InputNumber
                        min={0}
                        step={5}
                        style={{ width: 132 }}
                        value={screeningMaxDrawdownFilter}
                        placeholder="最大回撤%"
                        onChange={(value) => setScreeningMaxDrawdownFilter(value === null ? null : Number(value))}
                      />
                      <InputNumber
                        min={0}
                        step={0.1}
                        style={{ width: 110 }}
                        value={screeningMinProfitFactorFilter}
                        placeholder="最低 PF"
                        onChange={(value) => setScreeningMinProfitFactorFilter(value === null ? null : Number(value))}
                      />
                      <InputNumber
                        min={0}
                        step={1}
                        style={{ width: 120 }}
                        value={screeningMinTradeCountFilter}
                        placeholder="最少交易"
                        onChange={(value) => setScreeningMinTradeCountFilter(value === null ? null : Number(value))}
                      />
                      <Button
                        onClick={() => {
                          setScreeningLabelFilter([]);
                          setScreeningStrategyFilter(null);
                          setScreeningSymbolFilter(null);
                          setScreeningMinScoreFilter(null);
                          setScreeningMinOosReturnFilter(null);
                          setScreeningMinIsExcessReturnFilter(null);
                          setScreeningMaxGapFilter(null);
                          setScreeningMaxDrawdownFilter(null);
                          setScreeningMinProfitFactorFilter(null);
                          setScreeningMinTradeCountFilter(null);
                          setScreeningSorting([{ id: 'score', desc: true }]);
                        }}
                      >
                        重置筛选
                      </Button>
                    </Space>
                  </Space>
                  {filteredScreeningRuns.length ? (
                    <DataTable
                      columns={screeningRunColumns}
                      data={filteredScreeningRuns}
                      tableClassName="cbw-parameter-result-table"
                      initialPageSize={12}
                      pageSizeOptions={[12, 24, 48]}
                      initialSorting={[{ id: 'score', desc: true }]}
                      sorting={screeningSorting}
                      onSortingChange={setScreeningSorting}
                    />
                  ) : (
                    <Alert type="info" showIcon message="当前初筛池没有可展示的 run" />
                  )}
                </Card>
              </Space>
            )}

            {false && workspaceMode === 'screening' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {!researchSubjects.length ? (
                  <Alert type="info" showIcon message="当前还没有可横向对比的参数实验结果" />
                ) : (
                  <>
                    <Row gutter={[12, 12]}>
                      <Col xs={12} md={6}>
                        <Card size="small">
                          <Statistic title="研究对象" value={researchSubjects.length} />
                        </Card>
                      </Col>
                      <Col xs={12} md={6}>
                        <Card size="small">
                          <Statistic title="参数组" value={filteredResearchGroups.length} />
                        </Card>
                      </Col>
                      <Col xs={12} md={6}>
                        <Card size="small">
                          <Statistic
                            title="平均 OOS"
                            value={formatPct(averageNullable(filteredResearchGroups.map((group) => group.avg_oos_total_return)))}
                          />
                        </Card>
                      </Col>
                      <Col xs={12} md={6}>
                        <Card size="small">
                          <Statistic
                            title="最差回撤"
                            value={formatPct(filteredResearchGroups.length ? Math.max(...filteredResearchGroups.map((group) => group.worst_max_drawdown)) : null)}
                          />
                        </Card>
                      </Col>
                    </Row>

                    <Card size="small" title="全局研究结论">
                      <Paragraph type="secondary">
                        跨所有研究对象、批次和快照自动筛选参数组。优先看首选候选和稳健候选；高收益但激进、需要降风险验证只能作为下一轮复测来源。
                      </Paragraph>
                      <Row gutter={[12, 12]}>
                        {researchConclusionBuckets.map((bucket) => (
                          <Col key={bucket.key} xs={24} xl={bucket.key === 'excluded' ? 24 : 12} xxl={bucket.key === 'excluded' ? 24 : 8}>
                            <Alert
                              type={bucket.tone}
                              showIcon
                              message={(
                                <Space size={8} wrap>
                                  <Text strong>{bucket.title}</Text>
                                  <Tag>{bucket.items.length}</Tag>
                                </Space>
                              )}
                              description={(
                                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                                  <Text type="secondary">{bucket.description}</Text>
                                  {bucket.items.length ? (
                                    bucket.items.map((item, index) => (
                                      <div key={item.group.group_key}>
                                        <Space size={[6, 4]} wrap>
                                          <Text strong>{index + 1}.</Text>
                                          <Text strong>{item.group.symbol} · {item.group.timeframe.toUpperCase()}</Text>
                                          {renderParameterPoints(parameterGroupPoints(item.group), bucket.tone === 'error' ? 'default' : 'blue')}
                                        </Space>
                                        <Flex justify="space-between" align="center" wrap="wrap" gap={8} style={{ marginTop: 4 }}>
                                          <Text type="secondary">{item.reasons.join(' · ')}</Text>
                                          <Space size={6}>
                                            <Button size="small" onClick={() => setSelectedParameterGroupKey(item.group.group_key)}>详情</Button>
                                            <Button size="small" onClick={() => setRiskCompareGroupKey(item.group.group_key)}>风险对比</Button>
                                            {item.group.representative_run_id ? (
                                              <Button size="small" onClick={() => onOpenRun(item.group.representative_run_id as string)}>代表 Run</Button>
                                            ) : null}
                                          </Space>
                                        </Flex>
                                      </div>
                                    ))
                                  ) : (
                                    <Text type="secondary">暂无命中</Text>
                                  )}
                                </Space>
                              )}
                            />
                          </Col>
                        ))}
                      </Row>
                    </Card>
                  </>
                )}
              </Space>
            )}

            {workspaceMode === 'research' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {!researchPoolCandidates.length ? (
                  <Alert type="info" showIcon message="研究池还没有候选" description="在初筛池点击“加入研究池”后，候选会按入场结构和风险配置合并到这里。" />
                ) : (
                  <>
                    <Row gutter={[12, 12]}>
                      <Col xs={12} md={6}><Card size="small"><Statistic title="研究候选" value={filteredResearchPoolCandidates.length} suffix={`/ ${researchPoolCandidates.length}`} /></Card></Col>
                      <Col xs={12} md={6}><Card size="small"><Statistic title="可入稳定池" value={filteredResearchPoolCandidates.filter((candidate) => candidate.status === '可入稳定池').length} /></Card></Col>
                      <Col xs={12} md={6}><Card size="small"><Statistic title="邻域已跑" value={filteredResearchPoolCandidates.filter((candidate) => candidate.neighborhood_summary.status === '已跑').length} /></Card></Col>
                      <Col xs={12} md={6}><Card size="small"><Statistic title="风险矩阵已跑" value={filteredResearchPoolCandidates.filter((candidate) => candidate.risk_matrix_summary.status === '已跑').length} /></Card></Col>
                    </Row>

                    <Card size="small" title="研究池">
                      <DataTable
                        columns={researchPoolColumns}
                        data={filteredResearchPoolCandidates}
                        tableClassName="cbw-parameter-group-table"
                        initialPageSize={8}
                        pageSizeOptions={[8, 16, 32]}
                        initialSorting={[{ id: 'representative_run_score', desc: true }]}
                      />
                    </Card>

                    {false ? <Card
                      size="small"
                      title={(
                        <Space direction="vertical" size={2} style={{ width: '100%' }}>
                          <Text strong>{researchGroupTitle.title}</Text>
                          <Text type="secondary" style={{ whiteSpace: 'normal' }}>{researchGroupTitle.common}</Text>
                        </Space>
                      )}
                    >
                      <Paragraph type="secondary">
                        同一参数组会合并来自不同批次和快照的 run；列表中只展示每行真正变化的参数。
                      </Paragraph>
                      {recommendedResearchGroups.length ? (
                        <Alert
                          type="success"
                          showIcon
                          message="直接推荐参数组"
                          description={(
                            <Space direction="vertical" size={6} style={{ width: '100%' }}>
                              {recommendedResearchGroups.map((group, index) => {
                                const efficiency = (group.avg_oos_total_return ?? group.avg_total_return) / Math.max(group.worst_max_drawdown, 0.01);
                                return (
                                  <Space key={group.group_key} size={[6, 6]} wrap>
                                    <Text strong>{index + 1}.</Text>
                                    {renderParameterPoints(parameterGroupPoints(group).filter((point) => !researchGroupCommonKeys.has(point.key)), 'blue')}
                                    <Text type="secondary">
                                      OOS {formatPct(group.avg_oos_total_return)} · 最差回撤 {formatPct(group.worst_max_drawdown)} · PF {formatNumber(group.avg_profit_factor, 2)} · OOS/DD {formatNumber(efficiency, 2)}
                                    </Text>
                                  </Space>
                                );
                              })}
                            </Space>
                          )}
                          style={{ marginBottom: 12 }}
                        />
                      ) : null}
                      {filteredResearchGroups.length ? (
                        <DataTable
                          columns={researchParameterGroupColumns}
                          data={filteredResearchGroups}
                          tableClassName="cbw-parameter-group-table"
                          initialPageSize={12}
                          pageSizeOptions={[12, 24, 48]}
                          initialSorting={[{ id: 'research_score', desc: true }]}
                        />
                      ) : (
                        <Alert type="info" showIcon message="当前筛选下没有参数组" />
                      )}
                    </Card> : null}
                  </>
                )}
              </Space>
            )}

            {workspaceMode === 'stable' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="稳定组合" value={filteredStablePoolCandidates.length} suffix={`/ ${stablePoolCandidates.length}`} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="证据 Run" value={filteredStablePoolCandidates.reduce((total, candidate) => total + candidate.evidence_run_ids.length, 0)} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="执行已验证" value={filteredStablePoolCandidates.filter((candidate) => candidate.execution_verification.status === 'passed').length} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="平均评分" value={formatNumber(averageNullable(filteredStablePoolCandidates.map((candidate) => Number(candidate.validation_summary.score ?? NaN)).filter((value) => Number.isFinite(value))), 1)} /></Card></Col>
                </Row>
                <Card size="small" title="稳定池">
                  <Paragraph type="secondary">
                    稳定池只放已经人工确认的候选配置，包含入场结构、风险配置和证据 Run。后续复测、导出配置和归档从这里进入。
                  </Paragraph>
                  {filteredStablePoolCandidates.length ? (
                    <DataTable
                      columns={stablePoolColumns}
                      data={filteredStablePoolCandidates}
                      tableClassName="cbw-parameter-group-table"
                      initialPageSize={8}
                      pageSizeOptions={[8, 16, 32]}
                      initialSorting={[{ id: 'score', desc: true }]}
                    />
                  ) : (
                    <Alert type="info" showIcon message="稳定池还没有候选" description="在研究池点击“加入稳定池”后会出现在这里。" />
                  )}
                </Card>
              </Space>
            )}

            <Collapse
              items={[
                {
                  key: 'advanced',
                  label: '高级区：批次、单实验、台账与敏感度',
                  children: (
                    <Space wrap>
                      <Button onClick={() => setWorkspaceMode('tracking')}>追踪 Run</Button>
                      <Button onClick={() => setWorkspaceMode('batch')}>批次明细</Button>
                      <Button onClick={() => setWorkspaceMode('experiment')}>单实验</Button>
                      <Button onClick={() => setWorkspaceMode('decisions')}>决策台账</Button>
                      <Button onClick={() => setWorkspaceMode('sensitivity')}>敏感度</Button>
                    </Space>
                  ),
                },
              ]}
            />

            {workspaceMode === 'tracking' && (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Alert
                  type="info"
                  showIcon
                  message="追踪中的 Run"
                  description="从推荐表、实验结果或单次分析里冻结的 run 会集中到这里。这个视图只保留你主动关注的参数，后续可以打开分析、记录观察结论，或在决策台账中归档。"
                />
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="追踪 Run" value={filteredTrackedRunRows.length} suffix={`/ ${trackedRunRows.length}`} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="平均 OOS" value={formatPct(averageNullable(filteredTrackedRunRows.map((row) => row.oos_total_return)))} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="最差回撤" value={formatPct(filteredTrackedRunRows.length ? Math.max(...filteredTrackedRunRows.map((row) => row.max_drawdown)) : null)} /></Card></Col>
                  <Col xs={12} md={6}><Card size="small"><Statistic title="平均 PF" value={formatNumber(averageNullable(filteredTrackedRunRows.map((row) => row.profit_factor)), 2)} /></Card></Col>
                </Row>
                {trackedMissingNotes.length ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={`${trackedMissingNotes.length} 条追踪记录没有匹配到当前参数实验行`}
                    description="通常是 run 已删除，或当前本地参数实验 readmodel 尚未包含这条 run。仍可在决策台账里按“追踪中”标签查看原始记录。"
                  />
                ) : null}
                <Card size="small" title="冻结参数列表">
                  {filteredTrackedRunRows.length ? (
                    <DataTable
                      columns={trackingRunColumns}
                      data={filteredTrackedRunRows}
                      tableClassName="cbw-parameter-result-table"
                      initialPageSize={8}
                      pageSizeOptions={[8, 16, 32]}
                      initialSorting={[{ id: 'tracked_at', desc: true }]}
                    />
                  ) : (
                    <Alert type="info" showIcon message="还没有冻结追踪的 run" description="在推荐研究 Run、实验 Run 结果或单次分析里点击“冻结”，就会出现在这里。" />
                  )}
                </Card>
              </Space>
            )}

            {workspaceMode === 'batch' && (
              <Spin spinning={experimentDetailLoading}>
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text type="secondary">
                      批次视角优先看推荐研究 Run 和参数组结论，完整明细放在高级区。
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
                        <Alert type="info" showIcon message="当前批次人工标签筛选没有命中批次" />
                      ) : null}
                      <Alert
                        type="info"
                        showIcon
                        message="先从批次列表进入单个批次，再查看参数组推荐和 Run 明细。"
                      />
                    </>
                  ) : (
                    <>
                      <Card size="small" className="cbw-context-panel">
                        <Flex justify="space-between" align="flex-start" wrap="wrap" gap={12}>
                          <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ flex: 1, minWidth: 520 }}>
                            <Descriptions.Item label="搜索方式">{experimentSearchTypeLabel(selectedBatchDetail?.batch.search_type ?? selectedBatchSummary?.search_type)}</Descriptions.Item>
                            <Descriptions.Item label="快照 / 实验">{selectedBatchDetail?.batch.dataset_snapshot_ids.length ?? selectedBatchSummary?.snapshot_count ?? 0} / {selectedBatchDetail?.batch.experiment_ids.length ?? selectedBatchSummary?.experiment_count ?? 0}</Descriptions.Item>
                            <Descriptions.Item label="Run">{selectedBatchDetail?.execution.run_ids?.length ?? selectedBatchSummary?.run_count ?? 0}</Descriptions.Item>
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
                      {isDrawdownProtectionBatch ? (
                        <Card size="small" title="回撤保护对比">
                          <Space direction="vertical" size={12} style={{ width: '100%' }}>
                            <Alert
                              type="info"
                              showIcon
                              message="以无保护 Run 为基准，对比每个保护方案的 OOS、最大回撤、PF 和交易保留。"
                              description="候选表示回撤下降且 OOS/PF 没有明显受损；权衡表示风险收益需要人工判断。"
                            />
                            <DataTable
                              columns={drawdownProtectionComparisonColumns}
                              data={drawdownProtectionComparisonRows}
                              tableClassName="cbw-parameter-result-table"
                              initialPageSize={12}
                              pageSizeOptions={[12, 24]}
                              initialSorting={[{ id: 'drawdown_delta', desc: false }]}
                            />
                          </Space>
                        </Card>
                      ) : null}
                      <Card size="small" title="推荐研究 Run">
                        <Paragraph type="secondary">
                          按样本外收益、超额、交易数、回撤和 IS/OOS 差综合排序。可直接打开分析，或固定风险参数后跑趋势周期邻域。
                        </Paragraph>
                        {recommendedResearchRuns.length ? (
                          <DataTable
                            columns={researchRunColumns}
                            data={recommendedResearchRuns}
                            tableClassName="cbw-parameter-result-table"
                            initialPageSize={8}
                            pageSizeOptions={[8]}
                            initialSorting={[{ id: 'score', desc: true }]}
                          />
                        ) : (
                          <Alert type="info" showIcon message="当前筛选下没有可推荐的 Run" />
                        )}
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
                                        message={parameterGroupSummary(item)}
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
                                    message={parameterGroupSummary(item)}
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
                                        <Text>{parameterGroupSummary(group)}</Text>
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
                      <Card size="small" title="参数组结论">
                        <Paragraph type="secondary">
                          聚合后只保留研究判断相关列：样本外收益、IS/OOS 差、回撤、交易数和稳定度。
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
                      <Collapse
                        items={[
                          {
                            key: 'run-results',
                            label: `高级明细：完整 Run 表（${filteredBatchRunRows.length}）`,
                            children: (
                              <DataTable
                                columns={experimentResultColumns}
                                data={filteredBatchRunRows}
                                tableClassName="cbw-parameter-result-table"
                                initialPageSize={8}
                                pageSizeOptions={[8, 16, 32]}
                                initialSorting={[{ id: 'total_return', desc: true }]}
                              />
                            ),
                          },
                          ...(selectedBatchDetail ? [{
                            key: 'scoring-rules',
                            label: '评分标准',
                            children: (
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
                            ),
                          }] : []),
                        ]}
                      />
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
                        <Space direction="vertical" size={12} style={{ width: '100%' }}>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            当前显示 {filteredExperimentRunRows.length} / {selectedExperimentRows.length} 条已落盘 run。筛选支持“大于等于”阈值，最大回撤是“小于等于”阈值。
                          </Paragraph>
                          <Space wrap>
                            <InputNumber
                              min={0}
                              step={1}
                              value={experimentMinResearchScoreFilter}
                              placeholder="评分 ≥"
                              style={{ width: 112 }}
                              onChange={(value) => setExperimentMinResearchScoreFilter(value === null ? null : Number(value))}
                            />
                            <InputNumber
                              step={10}
                              value={experimentMinOosReturnFilter}
                              placeholder="OOS% ≥"
                              style={{ width: 116 }}
                              onChange={(value) => setExperimentMinOosReturnFilter(value === null ? null : Number(value))}
                            />
                            <InputNumber
                              step={10}
                              value={experimentMinTotalReturnFilter}
                              placeholder="收益% ≥"
                              style={{ width: 116 }}
                              onChange={(value) => setExperimentMinTotalReturnFilter(value === null ? null : Number(value))}
                            />
                            <InputNumber
                              min={0}
                              step={0.05}
                              value={experimentMinProfitFactorFilter}
                              placeholder="PF ≥"
                              style={{ width: 100 }}
                              onChange={(value) => setExperimentMinProfitFactorFilter(value === null ? null : Number(value))}
                            />
                            <InputNumber
                              min={0}
                              step={5}
                              value={experimentMaxDrawdownFilter}
                              placeholder="回撤% ≤"
                              style={{ width: 116 }}
                              onChange={(value) => setExperimentMaxDrawdownFilter(value === null ? null : Number(value))}
                            />
                            <InputNumber
                              min={0}
                              step={10}
                              value={experimentMinTradeCountFilter}
                              placeholder="交易数 ≥"
                              style={{ width: 116 }}
                              onChange={(value) => setExperimentMinTradeCountFilter(value === null ? null : Number(value))}
                            />
                            <Button
                              size="small"
                              onClick={() => {
                                setExperimentMinResearchScoreFilter(null);
                                setExperimentMinOosReturnFilter(null);
                                setExperimentMinTotalReturnFilter(null);
                                setExperimentMinProfitFactorFilter(null);
                                setExperimentMaxDrawdownFilter(null);
                                setExperimentMinTradeCountFilter(null);
                              }}
                            >
                              清空筛选
                            </Button>
                          </Space>
                        </Space>
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
      ) : null}
    </Space>
    <Modal
      title={filterResults ? `过滤结果 · ${filterResults.base_group.symbol} · ${filterResults.base_group.timeframe.toUpperCase()}` : '过滤结果'}
      open={Boolean(filterResultsCandidateId)}
      width={1280}
      footer={null}
      onCancel={() => {
        setFilterResultsCandidateId(null);
        setFilterResults(null);
      }}
    >
      <Spin spinning={filterResultsLoading}>
        {filterResults ? (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Descriptions size="small" column={{ xs: 1, md: 3 }}>
              <Descriptions.Item label="原始参数">{filterResults.base_group.parameter_summary}</Descriptions.Item>
              <Descriptions.Item label="原始 Run / 快照">{filterResults.base_group.run_count} / {filterResults.base_group.snapshot_count}</Descriptions.Item>
              <Descriptions.Item label="过滤 Run">{filterResults.filter_runs.length}</Descriptions.Item>
              <Descriptions.Item label="原始平均 OOS">{formatPct(filterResults.base_group.avg_oos_total_return)}</Descriptions.Item>
              <Descriptions.Item label="原始平均回撤">{formatPct(filterResults.base_group.avg_max_drawdown)}</Descriptions.Item>
              <Descriptions.Item label="原始平均 PF">{formatNumber(filterResults.base_group.avg_profit_factor, 2)}</Descriptions.Item>
            </Descriptions>
            {filterResults.filter_groups.length ? (
              <>
                <Card size="small" title="过滤器汇总">
                  <DataTable
                    columns={filterResultGroupColumns}
                    data={filterResults.filter_groups}
                    tableClassName="cbw-parameter-group-table"
                    initialPageSize={8}
                    pageSizeOptions={[8, 16, 32]}
                    initialSorting={[{ id: 'avg_oos_delta', desc: true }]}
                  />
                </Card>
                <Card size="small" title="过滤后 Run">
                  <DataTable
                    columns={filterResultRunColumns}
                    data={filterResults.filter_runs}
                    tableClassName="cbw-parameter-result-table"
                    initialPageSize={8}
                    pageSizeOptions={[8, 16, 32]}
                    initialSorting={[{ id: 'oos_total_return', desc: true }]}
                  />
                </Card>
              </>
            ) : (
              <Alert
                type="info"
                showIcon
                message="还没有匹配到过滤后 Run"
                description="先在研究池点击早败或通用提交过滤器实验；实验完成后再打开这里查看。"
              />
            )}
          </Space>
        ) : filterResultsLoading ? null : (
          <Alert type="info" showIcon message="未能加载过滤结果" />
        )}
      </Spin>
    </Modal>
    <Modal
      title={tradeAttribution ? `交易归因 · ${tradeAttribution.candidate.symbol} · ${tradeAttribution.candidate.timeframe.toUpperCase()}` : '交易归因'}
      open={Boolean(tradeAttributionCandidateId)}
      width={1280}
      footer={null}
      onCancel={() => {
        setTradeAttributionCandidateId(null);
        setTradeAttribution(null);
      }}
    >
      <Spin spinning={tradeAttributionLoading}>
        {tradeAttribution ? (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Descriptions size="small" column={{ xs: 1, md: 3 }}>
              <Descriptions.Item label="参数">{tradeAttribution.candidate.parameter_summary}</Descriptions.Item>
              <Descriptions.Item label="Run / 交易">{tradeAttribution.summary.run_count} / {tradeAttribution.summary.trade_count}</Descriptions.Item>
              <Descriptions.Item label="OOS 交易">{tradeAttribution.summary.oos_trade_count}</Descriptions.Item>
              <Descriptions.Item label="胜率">{formatPct(tradeAttribution.summary.win_rate)}</Descriptions.Item>
              <Descriptions.Item label="PF">{formatNumber(tradeAttribution.summary.profit_factor, 2)}</Descriptions.Item>
              <Descriptions.Item label="特征覆盖">{formatPct(tradeAttribution.summary.feature_meta_coverage)}</Descriptions.Item>
            </Descriptions>
            <Alert
              type={tradeAttribution.summary.anti_overfit_passed ? 'success' : 'warning'}
              showIcon
              message={tradeAttribution.summary.anti_overfit_passed ? '防拟合检查通过，可进入假设复验' : '防拟合检查未完全通过，只能看现象，不能定规则'}
              description={(
                <Space size={[6, 6]} wrap>
                  {tradeAttribution.anti_overfit_checks.map((check) => (
                    <Tag key={check.key} color={check.passed ? 'green' : 'orange'}>
                      {check.label} {formatNumber(check.actual, check.key === 'feature_meta_coverage' ? 2 : 0)} / {formatNumber(check.required, check.key === 'feature_meta_coverage' ? 2 : 0)}
                    </Tag>
                  ))}
                </Space>
              )}
            />
            <Alert
              type="info"
              showIcon
              message="早期失败归因流程：先把前三根无浮盈当失败标签，再倒推入场前代理特征"
              description={`早期失败定义为入场后三根最大浮盈 < 0.25R；主表优先展示趋势、回踩、突破、波动与方向组合。${earlyFailBaselineText}。`}
            />
            <Card size="small" title="早期失败归因（主看）">
              <Alert
                type={earlyFailAttributionConclusion.type}
                showIcon
                message={earlyFailAttributionConclusion.message}
                description={earlyFailAttributionConclusion.description}
                style={{ marginBottom: 12 }}
              />
              {!primaryEarlyFailAttributionBuckets.length && fallbackEarlyFailAttributionBuckets.length ? (
                <Alert
                  type="warning"
                  showIcon
                  message="没有强信号，下面仅展示弱线索"
                  description="这些行没有满足 OOS 复现或明显高于总体的门槛，只用于说明当前入场前特征的解释力偏弱。"
                  style={{ marginBottom: 12 }}
                />
              ) : null}
              {visibleEarlyFailAttributionBuckets.length ? (
                <DataTable
                  columns={earlyFailAttributionColumns}
                  data={visibleEarlyFailAttributionBuckets}
                  tableClassName="cbw-parameter-group-table"
                  stickyColumnCount={4}
                  initialPageSize={8}
                  pageSizeOptions={[8, 12, 24]}
                  initialSorting={[{ id: 'judgement', desc: true }]}
                />
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message="没有可展示的早期失败入场前线索"
                  description="当前候选的入场前特征覆盖不足，或没有任何维度达到最低 IS 样本门槛。"
                />
              )}
            </Card>
            <Alert
              type="info"
              showIcon
              message="止损归因流程：IS 找高止损共性，OOS 看是否复现"
              description="止损归因保留入场后路径线索，用来解释已经发生的止损亏损；它不能替代早期失败的入场前过滤实验。"
            />
            <Card size="small" title="止损归因（辅助）">
              <Alert
                type={stopLossAttributionConclusion.type}
                showIcon
                message={stopLossAttributionConclusion.message}
                description={stopLossAttributionConclusion.description}
                style={{ marginBottom: 12 }}
              />
              {pathStopLossAttributionBuckets.length ? (
                <DataTable
                  columns={stopLossAttributionColumns}
                  data={pathStopLossAttributionBuckets}
                  tableClassName="cbw-parameter-group-table"
                  initialPageSize={8}
                  pageSizeOptions={[8, 12, 24]}
                  initialSorting={[{ id: 'judgement', desc: true }]}
                />
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message="没有明显高于总体的止损共性"
                  description="这通常说明止损分布更像策略本身的常态损耗，或当前可用的入场特征还不足以解释止损原因。"
                />
              )}
            </Card>
            <Card size="small" title="止损亏损拆解（全部线索）">
              <DataTable
                columns={stopLossAttributionColumns}
                data={primaryStopLossAttributionBuckets}
                tableClassName="cbw-parameter-group-table"
                initialPageSize={8}
                pageSizeOptions={[8, 12, 24]}
                initialSorting={[{ id: 'judgement', desc: true }]}
              />
            </Card>
            {tradeAttribution.hypotheses.length ? (
              <Card size="small" title="候选归因假设">
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {tradeAttribution.hypotheses.map((hypothesis) => (
                    <Alert
                      key={hypothesis.hypothesis_id}
                      type={hypothesis.status === 'candidate' ? 'info' : 'warning'}
                      showIcon
                      message={hypothesis.description}
                      description={`${hypothesis.evidence}。${hypothesis.risk_note}`}
                    />
                  ))}
                </Space>
              </Card>
            ) : (
              <Alert type="info" showIcon message="暂时没有生成可复验的归因假设" />
            )}
            <Card size="small" title="收益归因（辅助）">
              {primaryTradeAttributionBuckets.length ? (
                <DataTable
                  columns={tradeAttributionBucketColumns}
                  data={primaryTradeAttributionBuckets}
                  tableClassName="cbw-parameter-group-table"
                  initialPageSize={8}
                  pageSizeOptions={[8, 12, 24]}
                  initialSorting={[{ id: 'judgement', desc: true }]}
                />
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message="没有足够稳定的入场前分桶"
                  description="当前 Run 仍可看全部分桶做现象排查，但还不适合直接形成入场过滤规则。"
                />
              )}
            </Card>
            <Card size="small" title="全部分桶（含结果解释）">
              <DataTable
                columns={tradeAttributionBucketColumns}
                data={tradeAttribution.buckets ?? []}
                tableClassName="cbw-parameter-group-table"
                initialPageSize={10}
                pageSizeOptions={[10, 20, 40]}
                initialSorting={[{ id: 'judgement', desc: true }]}
              />
            </Card>
            <Card size="small" title="大亏交易">
              {tradeAttribution.drawdown_trades.length ? (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {tradeAttribution.drawdown_trades.slice(0, 12).map((trade) => (
                    <Flex key={String(trade.trade_id)} justify="space-between" align="center" wrap="wrap" gap={8}>
                      <Space size={[6, 4]} wrap>
                        <Text strong>{shortRunId(String(trade.run_id))}</Text>
                        <Tag>{String(trade.segment).toUpperCase()}</Tag>
                        <Tag>{String(trade.side)}</Tag>
                        <Text type="secondary">{formatDateTime(String(trade.entry_time))}</Text>
                        <Text>{String(trade.exit_reason)}</Text>
                      </Space>
                      <Space size={10}>
                        <Text type="danger">{formatNumber(Number(trade.net_pnl), 2)}</Text>
                        <Text type="secondary">{formatPct(Number(trade.return_pct))}</Text>
                        <Button size="small" onClick={() => onOpenRun(String(trade.run_id))}>打开 Run</Button>
                      </Space>
                    </Flex>
                  ))}
                </Space>
              ) : (
                <Alert type="info" showIcon message="没有亏损交易" />
              )}
            </Card>
          </Space>
        ) : tradeAttributionLoading ? null : (
          <Alert type="info" showIcon message="未能加载交易归因" />
        )}
      </Spin>
    </Modal>
    <Modal
      title={riskCompareSourceGroup ? `风险 / 杠杆对比 · ${riskCompareSourceGroup.symbol} · ${riskCompareSourceGroup.timeframe.toUpperCase()}` : '风险 / 杠杆对比'}
      open={Boolean(riskCompareGroupKey)}
      width={1180}
      footer={null}
      onCancel={() => setRiskCompareGroupKey(null)}
    >
      {riskCompareSourceGroup ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions size="small" column={{ xs: 1, md: 2 }}>
            <Descriptions.Item label="固定入场结构">{riskCompareEntryText}</Descriptions.Item>
            <Descriptions.Item label="比较对象">只比较 risk / cash / 杠杆变化</Descriptions.Item>
          </Descriptions>
          <Alert
            type="info"
            showIcon
            message="怎么看"
            description="优先看 OOS/DD、最差回撤和 PF。收益更高但回撤同步放大的组合，不一定比低风险组合更好。"
          />
          {riskCompareGroups.length ? (
            <DataTable
              columns={riskCompareColumns}
              data={riskCompareGroups}
              tableClassName="cbw-parameter-group-table"
              initialPageSize={12}
              pageSizeOptions={[12, 24, 48]}
              initialSorting={[{ id: 'oos_drawdown_ratio', desc: true }]}
            />
          ) : (
            <Alert type="info" showIcon message="没有找到同入场结构下的其他风险/杠杆组合" />
          )}
        </Space>
      ) : null}
    </Modal>
    <Modal
      title="Run 对比"
      open={runCompareOpen}
      width={1180}
      footer={(
        <Space>
          <Button onClick={clearRunCompare}>清空选择</Button>
          <Button type="primary" onClick={clearRunCompare}>关闭</Button>
        </Space>
      )}
      onCancel={clearRunCompare}
    >
      {runCompareModel ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message={runCompareModel.summary}
            description={`相同项 ${runCompareModel.sameCount} 个，不同项 ${runCompareModel.diffCount} 个。绿色表示该指标相对更优，灰色表示相同或不排序。`}
          />
          <Row gutter={[12, 12]}>
            {[runCompareModel.left, runCompareModel.right].map((row, index) => (
              <Col xs={24} md={12} key={row.run_id}>
                <div className="cbw-run-compare-summary">
                  <Space direction="vertical" size={2}>
                    <Text type="secondary">Run {index === 0 ? 'A' : 'B'}</Text>
                    <Text strong>{shortRunId(row.run_id)}</Text>
                    <Text type="secondary">{row.symbol} · {row.timeframe.toUpperCase()} · {compactStrategyName(row.strategy_name)}</Text>
                    <Text>{row.parameter_summary}</Text>
                  </Space>
                  <Button size="small" onClick={() => onOpenRun(row.run_id)}>打开分析</Button>
                </div>
              </Col>
            ))}
          </Row>
          {runCompareModel.sections.map((section) => (
            <div key={section.key} className="cbw-run-compare-section">
              <Text strong>{section.title}</Text>
              <div className="cbw-run-compare-table-wrap">
                <table className="cbw-run-compare-table">
                  <thead>
                    <tr>
                      <th>项目</th>
                      <th>Run A</th>
                      <th>Run B</th>
                      <th>判断</th>
                    </tr>
                  </thead>
                  <tbody>
                    {section.rows.map((item) => (
                      <tr key={item.key} className={item.same ? 'is-same' : 'is-different'}>
                        <td>{item.label}</td>
                        <td className={item.leftBetter ? 'is-better' : item.rightBetter ? 'is-worse' : undefined}>{item.leftText}</td>
                        <td className={item.rightBetter ? 'is-better' : item.leftBetter ? 'is-worse' : undefined}>{item.rightText}</td>
                        <td>
                          {item.same ? (
                            <Tag>相同</Tag>
                          ) : item.leftBetter ? (
                            <Tag color="green">A 更优</Tag>
                          ) : item.rightBetter ? (
                            <Tag color="green">B 更优</Tag>
                          ) : (
                            <Tag color="blue">不同</Tag>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </Space>
      ) : (
        <Alert type="info" showIcon message="请选择两条 Run 后再打开对比" />
      )}
    </Modal>
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
    <Modal
      title={selectedParameterGroupDetail ? `参数组详情 · ${selectedParameterGroupDetail.group.parameter_summary}` : '参数组详情'}
      open={Boolean(selectedParameterGroupKey)}
      width={1280}
      footer={null}
      onCancel={() => {
        setSelectedParameterGroupKey(null);
        setSelectedParameterGroupDetail(null);
      }}
    >
      <Spin spinning={parameterGroupDetailLoading}>
        {selectedParameterGroupDetail ? (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Descriptions size="small" column={{ xs: 1, md: 3 }}>
              <Descriptions.Item label="研究对象">
                {selectedParameterGroupDetail.group.strategy_name} · {selectedParameterGroupDetail.group.symbol} · {selectedParameterGroupDetail.group.timeframe.toUpperCase()}
              </Descriptions.Item>
              <Descriptions.Item label="分类">
                <Tag color={parameterGroupClassificationColor(selectedParameterGroupDetail.group.classification)}>
                  {parameterGroupClassificationText(selectedParameterGroupDetail.group.classification)}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="研究分">{formatNumber(selectedParameterGroupDetail.group.research_score, 1)}</Descriptions.Item>
              <Descriptions.Item label="Run / 快照">{selectedParameterGroupDetail.group.run_count} / {selectedParameterGroupDetail.group.snapshot_count}</Descriptions.Item>
              <Descriptions.Item label="平均 OOS">{formatPct(selectedParameterGroupDetail.group.avg_oos_total_return)}</Descriptions.Item>
              <Descriptions.Item label="平均 Gap">{formatPct(selectedParameterGroupDetail.group.avg_gap)}</Descriptions.Item>
              <Descriptions.Item label="平均回撤">{formatPct(selectedParameterGroupDetail.group.avg_max_drawdown)}</Descriptions.Item>
              <Descriptions.Item label="最差回撤">{formatPct(selectedParameterGroupDetail.group.worst_max_drawdown)}</Descriptions.Item>
              <Descriptions.Item label="平均 PF">{formatNumber(selectedParameterGroupDetail.group.avg_profit_factor, 2)}</Descriptions.Item>
            </Descriptions>
            <Card size="small" title="跨批次 Run">
              {selectedParameterGroupDetail.runs.length ? (
                <DataTable
                  columns={parameterGroupRunColumns}
                  data={selectedParameterGroupDetail.runs}
                  tableClassName="cbw-parameter-result-table"
                  initialPageSize={8}
                  pageSizeOptions={[8, 16, 32]}
                  initialSorting={[{ id: 'oos_total_return', desc: true }]}
                />
              ) : (
                <Alert type="info" showIcon message="该参数组没有可展示的 run" />
              )}
            </Card>
            <Card size="small" title="趋势周期邻域">
              <Paragraph type="secondary">
                邻域只固定同一研究对象、同一 tol/sl/rr/仓位/杠杆等参数，比较趋势快慢周期附近组合，判断参数是否只在一个点上偶然有效。
              </Paragraph>
              {selectedParameterGroupDetail.neighbors.length ? (
                <DataTable
                  columns={researchParameterGroupColumns}
                  data={selectedParameterGroupDetail.neighbors}
                  tableClassName="cbw-parameter-group-table"
                  initialPageSize={8}
                  pageSizeOptions={[8, 16, 32]}
                  initialSorting={[{ id: 'research_score', desc: true }]}
                />
              ) : (
                <Alert type="info" showIcon message="当前参数组没有匹配到趋势周期邻域" />
              )}
            </Card>
          </Space>
        ) : parameterGroupDetailLoading ? null : (
          <Alert type="info" showIcon message="未能加载参数组详情" />
        )}
      </Spin>
    </Modal>
    <Modal
      title={neighborhoodSourceRun ? `趋势周期邻域 · ${shortRunId(neighborhoodSourceRun.run_id)}` : '趋势周期邻域'}
      open={Boolean(neighborhoodSourceRun)}
      width={1120}
      footer={null}
      onCancel={() => setNeighborhoodSourceRunId(null)}
    >
      {neighborhoodSourceRun ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions size="small" column={{ xs: 1, md: 3 }}>
            <Descriptions.Item label="数据">{neighborhoodSourceRun.symbol} · {neighborhoodSourceRun.timeframe.toUpperCase()}</Descriptions.Item>
            <Descriptions.Item label="当前周期">tf{neighborhoodSourceRun.trend_fast_period} / ts{neighborhoodSourceRun.trend_slow_period}</Descriptions.Item>
            <Descriptions.Item label="固定参数">
              tol {formatNumber(neighborhoodSourceRun.atr_entry_tolerance, 2)}
              {' '}· sl {formatNumber(neighborhoodSourceRun.atr_stop_mult, 2)}
              {' '}· rr {formatNumber(neighborhoodSourceRun.risk_reward_ratio, 2)}
              {' '}· l{formatNumber(neighborhoodSourceRun.leverage, 2)}
            </Descriptions.Item>
          </Descriptions>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            从全部实验结果中匹配同一快照、同一 tol/sl/rr/杠杆，只比较当前趋势快慢周期前后相邻组合。
          </Paragraph>
          <Alert
            showIcon
            type={trendNeighborhoodStats.verdict === 'stable' ? 'success' : trendNeighborhoodStats.verdict === 'watch' ? 'warning' : 'info'}
            message={(
              <Space size={8} wrap>
                <Text strong>{trendNeighborhoodStats.verdictText}</Text>
                <Tag color={trendNeighborhoodStats.verdict === 'stable' ? 'green' : trendNeighborhoodStats.verdict === 'watch' ? 'orange' : 'default'}>
                  稳定分 {trendNeighborhoodStats.score === null ? '--' : formatNumber(trendNeighborhoodStats.score, 1)}
                </Tag>
              </Space>
            )}
            description={trendNeighborhoodStats.reason}
          />
          <Row gutter={[12, 12]}>
            <Col xs={12} md={4}><Statistic title="邻居数" value={trendNeighborhoodStats.sampleCount} /></Col>
            <Col xs={12} md={4}><Statistic title="OOS 正比例" value={formatPct(trendNeighborhoodStats.positiveOosRatio)} /></Col>
            <Col xs={12} md={4}><Statistic title="平均 OOS" value={formatPct(trendNeighborhoodStats.avgOosReturn)} /></Col>
            <Col xs={12} md={4}><Statistic title="平均 Gap" value={formatPct(trendNeighborhoodStats.avgGap)} /></Col>
            <Col xs={12} md={4}><Statistic title="最差回撤" value={formatPct(trendNeighborhoodStats.worstDrawdown)} /></Col>
            <Col xs={12} md={4}><Statistic title="最少交易" value={trendNeighborhoodStats.minTradeCount ?? '--'} /></Col>
          </Row>
          {trendNeighborhoodMatches.length ? (
            <DataTable
              columns={trendNeighborhoodColumns}
              data={trendNeighborhoodMatches}
              tableClassName="cbw-parameter-result-table"
              initialPageSize={12}
              pageSizeOptions={[12, 24, 48]}
              initialSorting={[{ id: 'total_return', desc: true }]}
            />
          ) : (
            <Alert type="info" showIcon message="没有匹配到已完成的邻域结果" />
          )}
        </Space>
      ) : null}
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
