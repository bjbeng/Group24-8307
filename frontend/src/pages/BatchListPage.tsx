import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAuditTask, startBatch, uploadFile, type AuditTask, type TaskSummary } from "../api/audit";
import { useI18n } from "../i18n/I18nContext";
import HistoryFloat from "../components/HistoryFloat";

type Scenario = "s1" | "s2";

const INITIAL_TOTAL_BY_SCENARIO: Record<Scenario, number> = {
  s1: 11,
  s2: 19,
};

type BatchTaskRow = AuditTask & {
  fileName: string;
};

export default function BatchListPage() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [scenario, setScenario] = useState<Scenario>("s1");
  const [files, setFiles] = useState<File[]>([]);
  const [tasks, setTasks] = useState<BatchTaskRow[]>([]);
  const [status, setStatus] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pollingTaskIds, setPollingTaskIds] = useState<string[]>([]);

  useEffect(() => {
    if (!pollingTaskIds.length) return;

    let cancelled = false;

    const refreshTasks = async () => {
      try {
        const updated = await Promise.all(
          pollingTaskIds.map(id => getAuditTask(id).then(r => r.data))
        );
        if (cancelled) return;

        const taskMap = new Map(updated.map(task => [task.task_id, task]));
        setTasks(prev => prev.map(task => {
          const next = taskMap.get(task.task_id);
          return next ? { ...task, ...next } : task;
        }));

        const activeCount = updated.filter(task => task.status === "pending" || task.status === "running").length;
        if (activeCount === 0) {
          setPollingTaskIds([]);
          setStatus(`${updated.length} ${t.items}`);
          return;
        }
        setStatus(`${activeCount} ${t.running}`);
      } catch (err: unknown) {
        if (cancelled) return;
        setSubmitError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? t.operation_failed);
      }
    };

    void refreshTasks();
    const timer = window.setInterval(refreshTasks, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pollingTaskIds, t]);


  const submit = async () => {
    if (!files.length || submitting) return;

    setSubmitting(true);
    setStatus(t.uploading);
    setSubmitError("");
    setTasks([]);
    setPollingTaskIds([]);

    try {
      await Promise.all(files.map(file => uploadFile(file)));
      setStatus(t.start_batch);
      const res = await startBatch(files.map(file => file.name), scenario);
      const nextTasks: BatchTaskRow[] = res.data.task_ids.map((taskId, index) => ({
        task_id: taskId,
        fileName: files[index]?.name ?? "",
        scenario,
        mode: res.data.mode,
        status: "pending",
        progress: 0,
        total: INITIAL_TOTAL_BY_SCENARIO[scenario],
      }));
      setTasks(nextTasks);
      setPollingTaskIds(res.data.task_ids);
      setStatus(`${res.data.total} ${t.items}`);
    } catch (err: unknown) {
      setSubmitError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? t.operation_failed);
      setStatus("");
    } finally {
      setSubmitting(false);
    }
  };

  const openTask = (task: BatchTaskRow) => {
    if (task.status === "done") {
      nav(`/results/${task.task_id}`);
      return;
    }
    nav(`/audit/${task.task_id}`);
  };

  const handleHistorySelect = (task: TaskSummary) => {
    if (task.status === "done") {
      nav(`/results/${task.task_id}`);
      return;
    }
    nav(`/audit/${task.task_id}`);
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{t.batch_title}</h1>
        <button
          onClick={() => nav("/history")}
          style={{ background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontSize: 13 }}
        >
          {t.history_title}
        </button>
      </div>

      <div style={{ background: "#fff", borderRadius: 8, padding: 24, marginBottom: 24, border: "1px solid #e5e7eb" }}>
        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          {(["s1", "s2"] as Scenario[]).map(s => (
            <button
              key={s}
              onClick={() => setScenario(s)}
              disabled={submitting}
              style={{
                flex: 1,
                padding: "14px 18px",
                borderRadius: 8,
                border: `2px solid ${scenario === s ? "#2563eb" : "#e5e7eb"}`,
                background: scenario === s ? "#eff6ff" : "#fff",
                textAlign: "left",
                cursor: submitting ? "not-allowed" : "pointer",
                opacity: submitting ? 0.7 : 1,
              }}
            >
              <div style={{ fontWeight: 700, color: scenario === s ? "#1d4ed8" : "#374151", marginBottom: 4 }}>
                {s === "s1" ? t.scenario_1_title : t.scenario_2_title}
              </div>
              <div style={{ fontSize: 12, color: "#6b7280" }}>
                {s === "s1" ? t.scenario_1_desc : t.scenario_2_desc}
              </div>
            </button>
          ))}
        </div>

        <input
          type="file"
          multiple
          accept=".doc,.docx,.pdf"
          disabled={submitting}
          onChange={e => setFiles(Array.from(e.target.files ?? []))}
        />
        <p style={{ marginTop: 8, color: "#6b7280", fontSize: 13 }}>
          {t.files_selected.replace("{count}", String(files.length))}
        </p>
        <button
          onClick={submit}
          disabled={!files.length || submitting}
          style={{
            marginTop: 16,
            background: !files.length || submitting ? "#94a3b8" : "#2563eb",
            color: "#fff",
            border: "none",
            padding: "10px 24px",
            borderRadius: 6,
            cursor: !files.length || submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? t.processing : t.start_batch}
        </button>
        {status && <p style={{ marginTop: 12, color: "#2563eb" }}>{status}</p>}
        {submitError && <p style={{ marginTop: 12, color: "#dc2626" }}>{submitError}</p>}
      </div>

      {tasks.length > 0 && (() => {
        const s1Tasks = tasks.filter(task => task.scenario === "s1");
        const s2Tasks = tasks.filter(task => task.scenario === "s2");
        const renderTable = (title: string, list: BatchTaskRow[]) => list.length === 0 ? null : (
        <div key={title} style={{ background: "#fff", borderRadius: 8, padding: 24, border: "1px solid #e5e7eb", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 16 }}>
            <h2 style={{ margin: 0 }}>{title} · {t.task_status}</h2>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 12, color: "#6b7280" }}>
              <span>{t.pending}: {list.filter(item => item.status === "pending").length}</span>
              <span>{t.running}: {list.filter(item => item.status === "running").length}</span>
              <span>{t.done}: {list.filter(item => item.status === "done").length}</span>
              <span>{t.failed}: {list.filter(item => item.status === "failed").length}</span>
            </div>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f9fafb" }}>
                <th style={{ padding: "8px 12px", textAlign: "left" }}>{t.col_filename}</th>
                <th style={{ padding: "8px 12px", textAlign: "left" }}>{t.task_id_col}</th>
                <th style={{ padding: "8px 12px", textAlign: "left" }}>{t.status_col}</th>
                <th style={{ padding: "8px 12px", textAlign: "left" }}>{t.progress_col}</th>
                <th style={{ padding: "8px 12px", textAlign: "left" }}>{t.col_actions}</th>
              </tr>
            </thead>
            <tbody>
              {list.map(task => (
                <tr key={task.task_id} style={{ borderTop: "1px solid #e5e7eb" }}>
                  <td style={{ padding: "10px 12px", fontSize: 14, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {task.fileName}
                  </td>
                  <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 12 }}>
                    {task.task_id.slice(0, 12)}…
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span style={{ color: task.status === "failed" ? "#dc2626" : task.status === "done" ? "#15803d" : task.status === "running" ? "#1d4ed8" : "#92400e" }}>
                      {task.status === "pending" ? t.pending : task.status === "running" ? t.running : task.status === "done" ? t.done : t.failed}
                    </span>
                    {task.status === "failed" && task.error && (
                      <div style={{ marginTop: 4, fontSize: 12, color: "#dc2626", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {task.error}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "10px 12px" }}>{task.progress}/{task.total}</td>
                  <td style={{ padding: "10px 12px" }}>
                    <button
                      onClick={() => openTask(task)}
                      style={{ background: "none", border: "1px solid #cbd5e1", color: "#2563eb", padding: "6px 12px", borderRadius: 6, cursor: "pointer", fontSize: 12 }}
                    >
                      {task.status === "done" ? t.view_result : t.view_progress}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        );
        return (<>
          {renderTable(t.scenario_1_title, s1Tasks)}
          {renderTable(t.scenario_2_title, s2Tasks)}
        </>);
      })()}
      <HistoryFloat onSelect={handleHistorySelect} />
    </div>
  );
}
