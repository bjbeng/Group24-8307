import { mockTasks, mockAuditResults, mockBatchJobs } from "./data";

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const mockAuditApi = {
  upload: async (file: File) => {
    await delay(500);
    return { data: { task_id: "task-" + Date.now(), doc_name: file.name, status: "pending" } };
  },

  startAudit: async (taskId: string) => {
    await delay(300);
    return { data: { task_id: taskId, status: "processing" } };
  },

  getStatus: async (taskId: string) => {
    await delay(200);
    const task = mockTasks.find((t) => t.task_id === taskId);
    if (!task) return { data: { task_id: taskId, status: "not_found" } };
    if (task.status === "done") {
      return { data: { ...task, results: mockAuditResults[taskId as keyof typeof mockAuditResults] } };
    }
    return { data: { ...task, progress: 60 } };
  },

  getResults: async (taskId: string) => {
    await delay(300);
    return { data: mockAuditResults[taskId as keyof typeof mockAuditResults] || null };
  },

  batchAudit: async (files: File[]) => {
    await delay(800);
    return { data: { job_id: "job-" + Date.now(), total: files.length, done: 0, status: "processing" } };
  },

  getBatchJobs: async () => {
    await delay(200);
    return { data: mockBatchJobs };
  },

  getHistory: async () => {
    await delay(300);
    return { data: mockTasks };
  },
};

export const mockRulesApi = {
  list: async () => {
    await delay(200);
    const { mockRules } = await import("./data");
    return { data: mockRules };
  },
};