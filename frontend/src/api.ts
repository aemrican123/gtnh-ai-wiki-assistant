// Typed client for the local API in src/gtnh_assistant/api.py.

export interface LoadedModel {
  name: string;
  size_gb: number;
  vram_gb: number;
  gpu_percent: number;
  context_length: number | null;
}

export interface Gpu {
  name: string;
  memory_used_mb: number;
  memory_total_mb: number;
  utilization_percent: number;
}

export interface OllamaStatus {
  ok: boolean;
  host: string;
  version?: string;
  error?: string;
  models: string[];
  loaded: LoadedModel[];
  gpu: Gpu | null;
}

export interface KnowledgeStats {
  articles: number;
  indexed_articles: number;
  chunks: number;
  pending: number;
  errors: number;
  skipped: number;
  done: number;
}

export interface JobState {
  running: boolean;
  external: boolean;
  message: string;
  progress: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}

export interface Defaults {
  model: string;
  num_ctx: number;
  temperature: number;
  output_tokens: number;
  context_tokens: number;
  retrieval_limit: number;
  search_rounds: number;
}

export interface Status {
  ollama: OllamaStatus;
  knowledge_base: KnowledgeStats;
  job: JobState;
  defaults: Defaults;
  embedding_model: string;
  data_dir: string;
}

export interface Source {
  id: string;
  title: string;
  section: string;
  url: string;
  text: string;
}

export interface Answer {
  text: string;
  sources: Source[];
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  calls?: number;
  retrieval_ms?: number;
  load_ms?: number;
  first_token_ms?: number | null;
  generation_ms?: number;
  total_ms?: number;
  tokens_per_second?: number | null;
  warnings?: string[];
}

export type Options = Defaults;

export type StreamEvent =
  | { type: 'status'; text: string }
  | { type: 'token'; text: string }
  | { type: 'reset' }
  | { type: 'final'; answer: Answer }
  | { type: 'error'; message: string };

export type JobKind = 'scrape' | 'update' | 'index' | 'rebuild';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // Not JSON; keep the status line.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  status: (refresh = false) => request<Status>(`/api/status${refresh ? '?refresh=true' : ''}`),
  errors: () => request<{ errors: { url: string; error: string }[] }>('/api/errors'),
  startJob: (kind: JobKind, limit: number | null) =>
    request<JobState>('/api/jobs', { method: 'POST', body: JSON.stringify({ kind, limit }) }),
  cancelJob: () => request<JobState>('/api/jobs/cancel', { method: 'POST' }),
  backup: () => request<{ path: string }>('/api/backup', { method: 'POST' }),
  restore: (archive: string, destination: string) =>
    request<{ message: string }>('/api/restore', {
      method: 'POST',
      body: JSON.stringify({ archive, destination }),
    }),
};

/** Stream an answer as newline-delimited JSON events. */
export async function ask(
  body: {
    question: string;
    history: { role: 'user' | 'assistant'; content: string }[];
    options: Options;
    search_only: boolean;
  },
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
) {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`The local API returned ${response.status}`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let newline: number;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as StreamEvent);
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as StreamEvent);
}
