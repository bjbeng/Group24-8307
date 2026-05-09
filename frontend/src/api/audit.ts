import { api, WS_BASE } from "./client";

export interface DimensionSummary {
  dimension: string;
  verdict: string;
  findings_count: number;
  score: number | null;
  confidence: number | null;
}

export interface AuditSummary {
  doc_id?: string;
  doc_name?: string;
  overall_verdict?: string;
  overall_score?: number;
  need_human_review?: boolean;
  elapsed_seconds?: number;
  dimensions_completed?: number;
  dimension_summaries: DimensionSummary[];
}

export interface AuditTask {
  task_id: string;
  scenario: "s1" | "s2";
  mode: string;
  status: "pending" | "running" | "done" | "failed";
  progress: number;
  total: number;
  summary?: AuditSummary | null;
  result_ready?: boolean;
  result?: AuditResult | null;
  error?: string;
}

export interface AuditResult {
  doc_id: string;
  doc_name: string;
  scenario?: "s1" | "s2";
  overall_verdict: string;
  overall_score: number;
  raw_score?: number;
  max_score?: number;
  normalized_score?: number;
  need_human_review: boolean;
  dimensions: Record<string, DimensionResult>;
  elapsed_seconds: number;
}

export interface DimensionResult {
  dimension: string;
  name?: string;
  verdict: string;
  score: number | null;
  confidence: number;
  findings: Finding[];
  details: string;
}

export interface Finding {
  severity: "high" | "medium" | "low";
  description: string;
  evidence: string;
  rule_id?: string;
  section_path?: string;
  anchor_text?: string;
  category?: string;
}

export const uploadFile = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<{ file_id: string; path: string; size: number; file_hash: string }>("/api/upload", form);
};

export const listFiles = () =>
  api.get<{ files: Array<{ name: string; size: number; suffix: string }> }>("/api/upload");

export interface TaskSummary {
  task_id: string;
  file_name: string;
  scenario: "s1" | "s2";
  mode: string;
  status: "pending" | "running" | "done" | "failed";
  progress: number;
  total: number;
  created_at: string;
  finished_at: string;
  error: string;
}

export const listAuditTasks = (limit = 50) =>
  api.get<{ tasks: TaskSummary[]; total: number }>(`/api/history?limit=${limit}`);

export const deleteAuditTask = (taskId: string) =>
  api.delete<{ ok: boolean }>(`/api/history/${taskId}`);

export const startAudit = (
  fileName: string,
  ruleSetId?: string,
  scenario: "s1" | "s2" = "s1"
) =>
  api.post<{ task_id: string }>("/api/audit/start", {
    file_name: fileName,
    rule_set_id: ruleSetId,
    scenario,
  });

export const getAuditTask = (taskId: string, includeResult = false) =>
  api.get<AuditTask>(`/api/audit/${taskId}?include_result=${includeResult ? "true" : "false"}`);

export const getAuditTaskSummary = (taskId: string) =>
  api.get<AuditTask>(`/api/audit/${taskId}/summary`);

export const getAuditTaskResult = (taskId: string) =>
  api.get<AuditTask>(`/api/audit/${taskId}/result`);

export const getAuditReport = (taskId: string) =>
  api.get<string>(`/api/audit/${taskId}/download/report`, {
    responseType: "text",
  });

export const startBatch = (
  fileNames: string[],
  scenario: "s1" | "s2" = "s1",
  mode?: string
) =>
  api.post<{ task_ids: string[]; total: number; scenario: "s1" | "s2"; mode: string }>("/api/audit/batch", {
    file_names: fileNames,
    scenario,
    ...(mode ? { mode } : {}),
  });

export function createAuditWebSocket(taskId: string): WebSocket {
  // 从 VITE_WS_BASE 读取 WebSocket 地址，不 hardcode
  return new WebSocket(`${WS_BASE}/ws/audit/${taskId}`);
}
