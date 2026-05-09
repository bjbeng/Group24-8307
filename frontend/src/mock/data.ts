import { AuditTask, AuditResult, TaskSummary } from "../api/audit";

export const mockTasks: TaskSummary[] = [
  {
    task_id: "task-001",
    file_name: "作业指导书_管道安装_V1.docx",
    scenario: "s1",
    mode: "audit",
    status: "done",
    progress: 11,
    total: 11,
    created_at: "2026-05-03T10:00:00Z",
    finished_at: "2026-05-03T10:00:20Z",
    error: "",
  },
  {
    task_id: "task-002",
    file_name: "应急处置方案_高压区域.docx",
    scenario: "s1",
    mode: "audit",
    status: "done",
    progress: 11,
    total: 11,
    created_at: "2026-05-03T11:30:00Z",
    finished_at: "2026-05-03T11:30:18Z",
    error: "",
  },
];

export const mockAuditResults: Record<string, AuditResult> = {
  "task-001": {
    doc_id: "doc-001",
    doc_name: "作业指导书_管道安装_V1.docx",
    overall_score: 85,
    overall_verdict: "pass",
    need_human_review: false,
    elapsed_seconds: 12.5,
    dimensions: {
      C1: { dimension: "C1", name: "结构完整性", score: 12, verdict: "pass", confidence: 95, findings: [], details: "" },
      C2: { dimension: "C2", name: "内容完整性", score: 10, verdict: "pass", confidence: 88, findings: [], details: "" },
      C3: { dimension: "C3", name: "文字语法", score: 12, verdict: "pass", confidence: 90, findings: [], details: "" },
      C4: { dimension: "C4", name: "引用可追溯", score: 8, verdict: "fail", confidence: 92, findings: [
        { severity: "high", description: "附录A中引用了GB/T21020但未标注年份", evidence: "参见附录A第3节" }
      ], details: "" },
      C5: { dimension: "C5", name: "业务逻辑", score: 10, verdict: "pass", confidence: 85, findings: [], details: "" },
      E1: { dimension: "E1", name: "人员配备", score: 9, verdict: "fail", confidence: 91, findings: [
        { severity: "high", description: "应急人员数量不符合规范要求", evidence: "规范要求至少5人，实际配置3人" }
      ], details: "" },
      E2: { dimension: "E2", name: "应急处置", score: 11, verdict: "pass", confidence: 89, findings: [], details: "" },
      L2: { dimension: "L2", name: "标准遵从", score: 7, verdict: "fail", confidence: 93, findings: [
        { severity: "high", description: "未遵循GB32167相关要求", evidence: "见第4.2节" }
      ], details: "" },
      T1: { dimension: "T1", name: "模板使用", score: 12, verdict: "pass", confidence: 96, findings: [], details: "" },
      T2: { dimension: "T2", name: "格式兼容", score: 12, verdict: "pass", confidence: 98, findings: [], details: "" },
      T3: { dimension: "T3", name: "识别效率", score: 12, verdict: "pass", confidence: 94, findings: [], details: "" },
    },
  },
};

export const mockBatchJobs = [
  { job_id: "job-001", name: "第一批文档审核", total: 10, done: 10, failed: 1, status: "completed" },
  { job_id: "job-002", name: "第二批文档审核", total: 5, done: 3, failed: 0, status: "processing" },
];

export const mockRules = [
  { id: "C1", name: "结构完整性", description: "检查文档核心模块、编号、标题、附录是否完整" },
  { id: "C2", name: "内容完整性", description: "检查TSG31、GBT21246、QSY1217等标准要求的内容是否完整" },
  { id: "C3", name: "文字语法", description: "检查语句通顺性、标点使用、缩略词注释" },
  { id: "C4", name: "引用可追溯", description: "检查附录引用格式、标准号年份标注是否规范" },
  { id: "C5", name: "业务逻辑", description: "检查业务步骤逻辑顺序是否合理" },
];

export function makeMockTask(_fileName: string, result: AuditResult): AuditTask {
  return {
    task_id: result.doc_id,
    scenario: "s1",
    mode: "audit",
    status: "done",
    progress: 11,
    total: 11,
    result,
  };
}
