export interface WorkspaceData {
  generated_at: string;
  source: WorkspaceSource;
  datasets: DatasetSnapshotView[];
  overview: WorkspaceOverview;
  analysis: WorkspaceAnalysis;
  parameter_lab: WorkspaceParameterLab;
}

export interface WorkspaceSource {
  data_dir: string;
  run_count: number;
  dataset_count: number;
}

export interface WorkspaceOverview {
  summaries: RunSummaryView[];
  comparisons: RunComparisonView[];
  multi_run_equity: MultiRunEquityRow[];
}

export interface WorkspaceAnalysis {
  runs: RunAnalysisView[];
}

export interface WorkspaceParameterLab {
  rows: ParameterLabRow[];
  fast_period_total_return: SensitivityRow[];
  slow_period_total_return: SensitivityRow[];
}

export interface DatasetsPayload {
  generated_at: string;
  source: WorkspaceSource;
  datasets: DatasetSnapshotView[];
}

export interface OverviewPayload {
  generated_at: string;
  source: WorkspaceSource;
  overview: WorkspaceOverview;
}

export interface OverviewEquityPayload {
  generated_at: string;
  source: WorkspaceSource;
  multi_run_equity: MultiRunEquityRow[];
}

export interface RunIndexPayload {
  generated_at: string;
  source: WorkspaceSource;
  runs: RunSummaryView[];
}

export interface RunDetailPayload {
  generated_at: string;
  source: WorkspaceSource;
  run: RunAnalysisView;
}

export interface ParametersPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_lab: WorkspaceParameterLab;
}

export interface ParameterResearchPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_research: ParameterResearchWorkspace;
}

export interface ResearchWorkflowPayload {
  generated_at: string;
  source: WorkspaceSource;
  research_workflow: ResearchWorkflow;
}

export interface ParameterGroupDetailPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_group: ParameterGroupDetail;
}

export interface ResearchCandidateFilterResultsPayload {
  generated_at: string;
  source: WorkspaceSource;
  filter_results: ResearchCandidateFilterResults;
}

export interface TradeAttributionPayload {
  generated_at: string;
  source: WorkspaceSource;
  trade_attribution: TradeAttributionView;
}

export interface ParameterExperimentIndexPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_experiments: ParameterExperimentSummary[];
}

export interface ParameterExperimentBatchIndexPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_experiment_batches: ParameterExperimentBatchSummary[];
}

export interface ParameterExperimentDetailPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_experiment: ParameterExperimentDetail;
}

export interface ParameterExperimentBatchDetailPayload {
  generated_at: string;
  source: WorkspaceSource;
  parameter_experiment_batch: ParameterExperimentBatchDetail;
}

export interface ResearchNotesPayload {
  generated_at: string;
  source: WorkspaceSource;
  research_notes: ResearchNote[];
}

export interface DatasetSnapshotView {
  created_at: string;
  data_source: string;
  dataset_snapshot_id: string;
  exchange: string;
  feature_version: string;
  market_type: string;
  price_type: string;
  row_count: number;
  schema_version: string;
  source: string;
  storage_uri: string;
  symbol: string;
  time_range_end: string;
  time_range_start: string;
  timeframe: string;
}

export interface RunSummaryView {
  run_id: string;
  strategy_name: string;
  dataset_snapshot_id: string;
  symbol: string;
  timeframe: string;
  fast_period: number | null;
  slow_period: number | null;
  parameter_summary: string;
  leverage: number | null;
  status: string;
  created_at: string;
  validation_split_id: string;
  total_return: number;
  max_drawdown: number;
  final_equity: number;
  trade_count: number;
  win_rate: number;
  profit_factor: number | null;
  benchmark_return: number | null;
  excess_return: number | null;
  is_total_return: number | null;
  is_excess_return: number | null;
  oos_total_return: number | null;
  oos_excess_return: number | null;
  oos_trade_count: number | null;
  oos_win_rate: number | null;
  warning_count: number;
  order_count: number;
  fill_count: number;
}

export interface RunComparisonView {
  run_id: string;
  strategy_name: string;
  total_return: number;
  benchmark_return: number | null;
  excess_return: number | null;
  final_equity: number;
  trade_count: number;
  win_rate: number;
  profit_factor: number;
}

export interface MultiRunEquityRow {
  timestamp: string;
  [key: string]: number | string | null;
}

export interface RunAnalysisView {
  run_id: string;
  strategy_name: string;
  status: string;
  created_at: string;
  dataset_snapshot_id: string;
  validation_split_id: string;
  symbol: string;
  timeframe: string;
  manifest: {
    strategy_version: string;
    engine_version: string;
    execution_policy_id: string;
    metric_policy_id: string;
    feature_artifact_id: string;
    validation_split_id: string;
    resolved_config_json: Record<string, unknown>;
  };
  metrics: {
    initial_equity: number;
    final_equity: number;
    total_return: number;
    trade_count: number;
    win_rate: number;
    profit_factor: number;
    expectancy: number;
  };
  benchmark: {
    benchmark_id: string;
    run_id: string;
    benchmark_type: string;
    return_pct: number;
    max_drawdown: number;
    sharpe: number;
    equity_uri: string;
    daily_returns_uri: string | null;
  } | null;
  validation: {
    validation_split_id: string;
    is_segment: ValidationSegmentSummary;
    oos_segment: ValidationSegmentSummary;
  } | null;
  research_notes: ResearchNote[];
  execution_counts: {
    order_count: number;
    fill_count: number;
    trade_count: number;
    warning_count: number;
  };
  equity_rows: EquityRow[];
  trade_rows: TradeRow[];
  warning_rows: WarningRow[];
}

export interface EquityRow {
  timestamp: string;
  strategy_equity: number;
  benchmark_equity: number | null;
  strategy_cash: number;
  strategy_used_margin: number;
}

export interface ValidationSegmentSummary {
  name: string;
  warmup_bars: number;
  analysis_bar_count: number;
  window_bar_count: number;
  warmup_complete: boolean;
  analysis_start: string | null;
  analysis_end: string | null;
  metrics: {
    initial_equity: number;
    final_equity: number;
    total_return: number;
    trade_count: number;
    win_rate: number;
    profit_factor: number | null;
    expectancy: number;
  };
  benchmark_return: number | null;
  excess_return: number | null;
}

export interface ResearchNote {
  note_id: string;
  target_type: string;
  target_id: string;
  content: string;
  author: string;
  labels: string[];
  decision_status: string;
  decision_reason: string | null;
  confidence_score: number | null;
  linked_batch_id: string | null;
  linked_parameter_group: string | null;
  created_at: string;
}

export interface TradeRow {
  trade_id: string;
  symbol: string;
  side: string;
  entry_time: string;
  entry_price: number;
  exit_time: string | null;
  exit_price: number | null;
  qty: number;
  gross_pnl: number;
  fee: number;
  net_pnl: number;
  return_pct: number;
  holding_bars: number;
  entry_reason: string;
  exit_reason: string;
  planned_stop_loss_price: number | null;
  planned_take_profit_price: number | null;
  entry_signal_meta_json?: Record<string, unknown>;
}

export interface WarningRow {
  warning_id: string;
  warning_type: string;
  warning_code: string;
  severity: string;
  message: string;
  created_at: string;
}

export interface ParameterLabRow {
  run_id: string;
  strategy_name: string;
  dataset_snapshot_id: string;
  symbol: string;
  timeframe: string;
  validation_split_id: string;
  status: string;
  created_at: string;
  fast_period: number | null;
  slow_period: number | null;
  trend_fast_period: number | null;
  trend_slow_period: number | null;
  entry_ema_period: number | null;
  atr_period: number | null;
  atr_entry_tolerance: number | null;
  atr_stop_mult: number | null;
  risk_reward_ratio: number | null;
  parameter_summary: string;
  signal_filter_summary: string | null;
  qty_policy_ref: string | null;
  cash_allocation_pct: number | null;
  risk_pct_per_trade: number | null;
  leverage: number | null;
  fee_rate: number | null;
  slippage_bps: number | null;
  total_return: number;
  max_drawdown: number;
  benchmark_return: number | null;
  excess_return: number | null;
  is_total_return: number | null;
  is_excess_return: number | null;
  oos_total_return: number | null;
  oos_excess_return: number | null;
  oos_trade_count: number | null;
  oos_win_rate: number | null;
  final_equity: number;
  trade_count: number;
  win_rate: number;
  profit_factor: number | null;
  warning_count: number;
}

export interface ResearchSubjectView {
  subject_key: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  validation_split_id: string;
  parameter_group_count: number;
  run_count: number;
  snapshot_count: number;
  latest_run_at: string | null;
}

export interface ParameterGroupView {
  group_key: string;
  subject_key: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  validation_split_id: string;
  parameter_summary: string;
  signal_filter_summary: string | null;
  fast_period: number | null;
  slow_period: number | null;
  trend_fast_period: number | null;
  trend_slow_period: number | null;
  entry_ema_period: number | null;
  atr_period: number | null;
  atr_entry_tolerance: number | null;
  atr_stop_mult: number | null;
  risk_reward_ratio: number | null;
  qty_policy_ref: string | null;
  cash_allocation_pct: number | null;
  risk_pct_per_trade: number | null;
  leverage: number | null;
  run_count: number;
  snapshot_count: number;
  avg_total_return: number;
  avg_oos_total_return: number | null;
  oos_positive_ratio: number | null;
  avg_gap: number | null;
  avg_max_drawdown: number;
  worst_max_drawdown: number;
  avg_profit_factor: number | null;
  avg_win_rate: number;
  min_trade_count: number;
  min_oos_trade_count: number | null;
  neighbor_count: number;
  stable_neighbor_count: number;
  neighbor_stability_score: number | null;
  research_score: number;
  classification: string;
  representative_run_id: string | null;
  run_ids: string[];
}

export interface ParameterGroupRunView {
  group_key: string;
  run_id: string;
  batch_id: string | null;
  experiment_id: string | null;
  dataset_snapshot_id: string;
  created_at: string;
  total_return: number;
  oos_total_return: number | null;
  gap: number | null;
  max_drawdown: number;
  profit_factor: number | null;
  trade_count: number;
  oos_trade_count: number | null;
  win_rate: number;
  oos_win_rate: number | null;
  final_equity: number;
}

export interface ParameterResearchWorkspace {
  subjects: ResearchSubjectView[];
  parameter_groups: ParameterGroupView[];
}

export interface ScreeningRunView {
  run_id: string;
  strategy_name: string;
  dataset_snapshot_id: string;
  symbol: string;
  timeframe: string;
  validation_split_id: string;
  parameter_summary: string;
  signal_filter_summary: string | null;
  fast_period: number | null;
  slow_period: number | null;
  trend_fast_period: number | null;
  trend_slow_period: number | null;
  entry_ema_period: number | null;
  atr_period: number | null;
  atr_entry_tolerance: number | null;
  atr_stop_mult: number | null;
  risk_reward_ratio: number | null;
  qty_policy_ref: string | null;
  cash_allocation_pct: number | null;
  risk_pct_per_trade: number | null;
  leverage: number | null;
  score: number;
  auto_labels: string[];
  manual_labels: string[];
  pool_status: string;
  neighborhood_status: string;
  total_return: number;
  is_excess_return: number | null;
  oos_total_return: number | null;
  oos_excess_return: number | null;
  is_oos_gap: number | null;
  max_drawdown: number;
  profit_factor: number | null;
  trade_count: number;
  oos_trade_count: number | null;
  created_at: string;
}

export interface ResearchCandidateView {
  candidate_id: string;
  source_run_ids: string[];
  strategy_name: string;
  symbol: string;
  timeframe: string;
  validation_split_id: string;
  entry_structure: Record<string, unknown>;
  risk_profile: Record<string, unknown>;
  representative_run_id: string | null;
  representative_run_score: number;
  status: string;
  latest_note: ResearchNote | null;
  neighborhood_summary: Record<string, unknown>;
  risk_matrix_summary: Record<string, unknown>;
  recommendation: string;
  updated_at: string | null;
}

export interface StableCandidateView {
  stable_candidate_id: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  validation_split_id: string;
  entry_structure: Record<string, unknown>;
  chosen_risk_profile: Record<string, unknown>;
  evidence_run_ids: string[];
  representative_run_id: string | null;
  validation_summary: Record<string, unknown>;
  neighborhood_summary: Record<string, unknown>;
  risk_matrix_summary: Record<string, unknown>;
  final_recommendation: string;
  status: string;
  latest_note: ResearchNote | null;
}

export interface ResearchWorkflow {
  screening_pool: {
    runs: ScreeningRunView[];
  };
  research_pool: {
    candidates: ResearchCandidateView[];
  };
  stable_pool: {
    candidates: StableCandidateView[];
  };
}

export interface ParameterGroupDetail {
  group: ParameterGroupView;
  runs: ParameterGroupRunView[];
  neighbors: ParameterGroupView[];
}

export interface FilterResultGroup {
  filter_summary: string;
  run_count: number;
  snapshot_count: number;
  avg_total_return: number | null;
  avg_oos_total_return: number | null;
  avg_oos_delta: number | null;
  avg_max_drawdown: number | null;
  avg_drawdown_delta: number | null;
  worst_max_drawdown: number | null;
  avg_profit_factor: number | null;
  avg_profit_factor_delta: number | null;
  min_trade_count: number | null;
  min_oos_trade_count: number | null;
  trade_retention: number | null;
  run_ids: string[];
}

export interface ResearchCandidateFilterResults {
  candidate_id: string;
  base_group: ParameterGroupView;
  base_runs: ParameterGroupRunView[];
  filter_groups: FilterResultGroup[];
  filter_runs: ParameterLabRow[];
}

export interface TradeAttributionBucket {
  dimension: string;
  bucket_key: string;
  label: string;
  trade_count: number;
  oos_trade_count: number;
  win_rate: number;
  net_pnl: number;
  avg_return_pct: number;
  profit_factor: number | null;
  loss_contribution: number;
  big_loss_count: number;
  sample_ok: boolean;
}

export interface TradeAttributionHypothesis {
  hypothesis_id: string;
  description: string;
  evidence: string;
  risk_note: string;
  status: string;
  source_dimension: string;
  source_bucket: string;
}

export interface TradeAttributionView {
  candidate_id: string;
  candidate: {
    strategy_name: string;
    symbol: string;
    timeframe: string;
    parameter_summary: string;
    signal_filter_summary: string | null;
    run_ids: string[];
  };
  summary: {
    run_count: number;
    trade_count: number;
    oos_trade_count: number;
    win_rate: number;
    net_pnl: number;
    profit_factor: number | null;
    feature_meta_coverage: number;
    hypothesis_count: number;
    anti_overfit_passed: boolean;
  };
  anti_overfit_checks: Array<{
    key: string;
    label: string;
    passed: boolean;
    actual: number;
    required: number;
  }>;
  buckets: TradeAttributionBucket[];
  drawdown_trades: Array<Record<string, unknown>>;
  hypotheses: TradeAttributionHypothesis[];
}

export interface SensitivityRow {
  parameter_name: string;
  parameter_value: number;
  run_count: number;
  avg_metric: number;
  best_metric: number;
}

export interface ParameterExperimentSummary {
  experiment_id: string;
  strategy_name: string;
  dataset_bundle_id: string;
  search_type: string;
  task_id: string | null;
  status: string;
  planned_run_count: number;
  run_count: number;
  failed_run_count: number;
  created_at: string;
}

export interface ParameterExperimentDetail {
  experiment: {
    experiment_id: string;
    strategy_name: string;
    dataset_bundle_id: string;
    validation_split_id: string;
    metric_policy_id: string;
    benchmark_policy_version: string;
    benchmark_config_uri: string;
    search_type: string;
    search_space_json: Record<string, unknown>;
    base_config_uri: string;
    seed_policy: string;
    seed: number | null;
    shared_feature_artifact_ids: string[];
    created_at: string;
  };
  execution: {
    experiment_id?: string;
    task_id?: string;
    status?: string;
    run_ids?: string[];
    child_task_ids?: string[];
    failed_child_task_ids?: string[];
    planned_run_count?: number;
    updated_at?: string;
  };
}

export interface ParameterExperimentBatchSummary {
  batch_id: string;
  strategy_name: string;
  snapshot_count: number;
  experiment_count: number;
  search_type: string;
  task_id: string | null;
  status: string;
  planned_experiment_count: number;
  planned_run_count: number;
  run_count: number;
  failed_experiment_count: number;
  created_at: string;
}

export interface ParameterGroupRecommendation {
  strategy_name: string;
  parameter_summary: string;
  signal_filter_summary?: string | null;
  fast_period: number | null;
  slow_period: number | null;
  trend_fast_period?: number | null;
  trend_slow_period?: number | null;
  entry_ema_period?: number | null;
  atr_period?: number | null;
  atr_entry_tolerance?: number | null;
  atr_stop_mult?: number | null;
  risk_reward_ratio?: number | null;
  leverage: number | null;
  run_count: number;
  snapshot_count: number;
  timeframe_count: number;
  avg_total_return: number;
  avg_excess_return: number;
  avg_oos_total_return: number;
  avg_oos_excess_return: number;
  is_oos_gap: number | null;
  avg_max_drawdown: number;
  worst_max_drawdown: number;
  return_over_drawdown: number;
  best_total_return: number;
  min_trade_count: number | null;
  min_oos_trade_count: number | null;
  positive_ratio: number;
  oos_available_count: number;
  oos_positive_ratio: number | null;
  neighbor_count: number;
  stable_neighbor_count: number;
  neighbor_stability_score: number | null;
  score: number;
  confidence: number;
  run_ids: string[];
  reason: string;
}

export interface ParameterScoringRule {
  label: string;
  summary: string;
  thresholds: string[];
}

export interface ParameterExperimentBatchDetail {
  batch: {
    batch_id: string;
    strategy_name: string;
    dataset_snapshot_ids: string[];
    validation_split_id: string;
    metric_policy_id: string;
    benchmark_policy_version: string;
    search_type: string;
    search_space_json: Record<string, unknown>;
    base_config_uri: string;
    seed_policy: string;
    seed: number | null;
    experiment_ids: string[];
    created_at: string;
  };
  execution: {
    batch_id?: string;
    task_id?: string;
    status?: string;
    dataset_snapshot_ids?: string[];
    experiment_ids?: string[];
    run_ids?: string[];
    child_task_ids?: string[];
    failed_experiment_ids?: string[];
    planned_experiment_count?: number;
    planned_run_count?: number;
    updated_at?: string;
  };
  experiments: ParameterExperimentDetail[];
  run_rows: ParameterLabRow[];
  parameter_groups: Array<Omit<ParameterGroupRecommendation, 'reason'>>;
  recommendations: {
    robust_candidates: ParameterGroupRecommendation[];
    high_return_candidates: ParameterGroupRecommendation[];
    exploratory_candidates?: ParameterGroupRecommendation[];
    excluded_combinations: ParameterGroupRecommendation[];
  };
  scoring_rules: {
    robust_candidate: ParameterScoringRule;
    high_return_candidate: ParameterScoringRule;
    excluded_combination: ParameterScoringRule;
  };
}
