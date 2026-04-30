import type {
  DatasetsPayload,
  OverviewEquityPayload,
  ParameterExperimentBatchDetailPayload,
  ParameterExperimentBatchIndexPayload,
  ParameterExperimentDetailPayload,
  OverviewPayload,
  ParameterExperimentIndexPayload,
  ParametersPayload,
  ResearchNote,
  ResearchNotesPayload,
  RunDetailPayload,
  RunIndexPayload,
  WorkspaceData,
  MultiRunEquityRow,
} from '../types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '';

let fallbackWorkspacePromise: Promise<WorkspaceData> | null = null;

function apiUrl(path: string): string {
  if (!API_BASE) {
    return path;
  }
  return `${API_BASE}${path}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { error?: { message?: string } };
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'error' in payload
      ? payload.error?.message ?? `Request failed with status ${response.status}`
      : `Request failed with status ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path));
  return parseResponse<T>(response);
}

async function loadFallbackWorkspace(): Promise<WorkspaceData> {
  if (fallbackWorkspacePromise === null) {
    fallbackWorkspacePromise = fetch('/demo/workspace.json').then((response) => parseResponse<WorkspaceData>(response));
  }
  return fallbackWorkspacePromise;
}

export async function loadDatasets(): Promise<DatasetsPayload> {
  try {
    return await fetchJson<DatasetsPayload>('/api/datasets');
  } catch {
    const workspace = await loadFallbackWorkspace();
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      datasets: workspace.datasets,
    };
  }
}

export async function loadOverview(): Promise<OverviewPayload> {
  try {
    return await fetchJson<OverviewPayload>('/api/overview');
  } catch {
    const workspace = await loadFallbackWorkspace();
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      overview: workspace.overview,
    };
  }
}

export async function loadOverviewEquity(runIds: string[]): Promise<OverviewEquityPayload> {
  try {
    const params = new URLSearchParams();
    for (const runId of runIds) {
      params.append('run_id', runId);
    }
    return await fetchJson<OverviewEquityPayload>(`/api/overview-equity?${params.toString()}`);
  } catch {
    const workspace = await loadFallbackWorkspace();
    if (!runIds.length) {
      return {
        generated_at: workspace.generated_at,
        source: workspace.source,
        multi_run_equity: [],
      };
    }
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      multi_run_equity: workspace.overview.multi_run_equity.map((row) => {
        const filtered: MultiRunEquityRow = {
          timestamp: row.timestamp,
        };
        for (const runId of runIds) {
          filtered[`${runId}_equity`] = row[`${runId}_equity`] ?? null;
          filtered[`${runId}_benchmark`] = row[`${runId}_benchmark`] ?? null;
        }
        return filtered;
      }),
    };
  }
}

export async function loadRuns(): Promise<RunIndexPayload> {
  try {
    return await fetchJson<RunIndexPayload>('/api/runs');
  } catch {
    const workspace = await loadFallbackWorkspace();
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      runs: workspace.overview.summaries,
    };
  }
}

export async function loadRunDetail(runId: string): Promise<RunDetailPayload> {
  try {
    return await fetchJson<RunDetailPayload>(`/api/runs/${encodeURIComponent(runId)}`);
  } catch {
    const workspace = await loadFallbackWorkspace();
    const run = workspace.analysis.runs.find((entry) => entry.run_id === runId);
    if (!run) {
      throw new Error(`Run not found: ${runId}`);
    }
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      run,
    };
  }
}

export async function loadParameters(): Promise<ParametersPayload> {
  try {
    return await fetchJson<ParametersPayload>('/api/parameters');
  } catch {
    const workspace = await loadFallbackWorkspace();
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      parameter_lab: workspace.parameter_lab,
    };
  }
}

export async function loadParameterExperiments(): Promise<ParameterExperimentIndexPayload> {
  return fetchJson<ParameterExperimentIndexPayload>('/api/parameter-experiments');
}

export async function loadParameterExperimentBatches(): Promise<ParameterExperimentBatchIndexPayload> {
  return fetchJson<ParameterExperimentBatchIndexPayload>('/api/parameter-experiment-batches');
}

export async function loadParameterExperimentDetail(experimentId: string): Promise<ParameterExperimentDetailPayload> {
  return fetchJson<ParameterExperimentDetailPayload>(`/api/parameter-experiments/${encodeURIComponent(experimentId)}`);
}

export async function loadParameterExperimentBatchDetail(batchId: string): Promise<ParameterExperimentBatchDetailPayload> {
  return fetchJson<ParameterExperimentBatchDetailPayload>(`/api/parameter-experiment-batches/${encodeURIComponent(batchId)}`);
}

export interface ResearchNoteFilters {
  targetType?: string;
  targetId?: string;
  decisionStatus?: string;
  label?: string;
  linkedBatchId?: string;
  linkedParameterGroup?: string;
}

export async function loadResearchNotes(targetTypeOrFilters?: string | ResearchNoteFilters, targetId?: string): Promise<ResearchNotesPayload> {
  const filters: ResearchNoteFilters = typeof targetTypeOrFilters === 'object'
    ? targetTypeOrFilters
    : { targetType: targetTypeOrFilters, targetId };
  const params = new URLSearchParams();
  if (filters.targetType) {
    params.set('target_type', filters.targetType);
  }
  if (filters.targetId) {
    params.set('target_id', filters.targetId);
  }
  if (filters.decisionStatus) {
    params.set('decision_status', filters.decisionStatus);
  }
  if (filters.label) {
    params.set('label', filters.label);
  }
  if (filters.linkedBatchId) {
    params.set('linked_batch_id', filters.linkedBatchId);
  }
  if (filters.linkedParameterGroup) {
    params.set('linked_parameter_group', filters.linkedParameterGroup);
  }
  try {
    return await fetchJson<ResearchNotesPayload>(`/api/research-notes${params.size ? `?${params.toString()}` : ''}`);
  } catch {
    const workspace = await loadFallbackWorkspace();
    const notes = workspace.analysis.runs.flatMap((run) => run.research_notes ?? []);
    const filteredNotes = notes.filter((note) => (
      (!filters.targetType || note.target_type === filters.targetType)
      && (!filters.targetId || note.target_id === filters.targetId)
      && (!filters.decisionStatus || note.decision_status === filters.decisionStatus)
      && (!filters.label || (note.labels ?? []).includes(filters.label))
      && (!filters.linkedBatchId || note.linked_batch_id === filters.linkedBatchId)
      && (!filters.linkedParameterGroup || note.linked_parameter_group === filters.linkedParameterGroup)
    ));
    return {
      generated_at: workspace.generated_at,
      source: workspace.source,
      research_notes: filteredNotes as ResearchNote[],
    };
  }
}

export async function postIngest(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl('/api/ingest'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function postRunEma(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl('/api/run-ema'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function postParameterExperiment(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl('/api/parameter-experiments'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function postParameterExperimentBatch(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl('/api/parameter-experiment-batches'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function postResearchNote(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl('/api/research-notes'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function deleteRun(runId: string): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(`/api/runs/${encodeURIComponent(runId)}`), {
    method: 'DELETE',
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function deleteDataset(snapshotId: string): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(`/api/datasets/${encodeURIComponent(snapshotId)}`), {
    method: 'DELETE',
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function deleteParameterExperiment(experimentId: string): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(`/api/parameter-experiments/${encodeURIComponent(experimentId)}`), {
    method: 'DELETE',
  });
  return parseResponse<Record<string, unknown>>(response);
}

export async function deleteParameterExperimentBatch(batchId: string): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(`/api/parameter-experiment-batches/${encodeURIComponent(batchId)}`), {
    method: 'DELETE',
  });
  return parseResponse<Record<string, unknown>>(response);
}
