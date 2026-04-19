import type {
  DatasetsPayload,
  ParameterExperimentDetailPayload,
  OverviewPayload,
  ParameterExperimentIndexPayload,
  ParametersPayload,
  RunDetailPayload,
  RunIndexPayload,
  WorkspaceData,
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

export async function loadParameterExperimentDetail(experimentId: string): Promise<ParameterExperimentDetailPayload> {
  return fetchJson<ParameterExperimentDetailPayload>(`/api/parameter-experiments/${encodeURIComponent(experimentId)}`);
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
