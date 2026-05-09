import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listAuditTasks, deleteAuditTask, type TaskSummary } from "../api/audit";
import { useI18n } from "../i18n/I18nContext";

const STATUS_STYLE = (t: ReturnType<typeof useI18n>["t"]) => ({
  pending:  { color: "#92400e", label: t.pending },
  running:  { color: "#1d4ed8", label: t.running },
  done:     { color: "#15803d", label: t.done },
  failed:   { color: "#b91c1c", label: t.failed },
});

export default function HistoryPage() {
  const nav = useNavigate();
  const { t } = useI18n();
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [scenarioTab, setScenarioTab] = useState<"all" | "s1" | "s2">("all");

  const load = () => {
    setLoading(true);
    setError("");
    listAuditTasks(100)
      .then(r => setTasks(r.data.tasks))
      .catch(() => setError(t.loading))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [t]);

  const handleDelete = async (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    if (!confirm(t.confirm_delete)) return;
    setDeleting(taskId);
    try {
      await deleteAuditTask(taskId);
      setTasks(prev => prev.filter(task => task.task_id !== taskId));
    } catch {
      alert(t.delete_fail);
    } finally {
      setDeleting(null);
    }
  };

  const handleClick = (task: TaskSummary) => {
    if (task.status === "done") nav(`/results/${task.task_id}`);
    else nav(`/audit/${task.task_id}`);
  };

  const headers = [t.col_filename, t.col_scenario, t.col_status, t.col_progress, t.col_submit_time, t.col_finish_time, t.col_actions, ""];
  const styles = STATUS_STYLE(t);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{t.history_title}</h1>
        <button onClick={load} style={{ background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 6, padding: "6px 16px", cursor: "pointer", fontSize: 13 }}>
          {t.refresh}
        </button>
      </div>

      {loading && <p style={{ color: "#6b7280" }}>{t.loading}</p>}
      {error && <p style={{ color: "#dc2626" }}>{error}</p>}

      {!loading && tasks.length > 0 && (
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {(["all", "s1", "s2"] as const).map(key => {
            const count = key === "all" ? tasks.length : tasks.filter(item => item.scenario === key).length;
            return (
              <button
                key={key}
                onClick={() => setScenarioTab(key)}
                style={{
                  padding: "6px 16px", borderRadius: 6, fontSize: 13, fontWeight: 600,
                  border: "1px solid",
                  borderColor: scenarioTab === key ? "#2563eb" : "#e5e7eb",
                  background: scenarioTab === key ? "#eff6ff" : "#fff",
                  color: scenarioTab === key ? "#1d4ed8" : "#6b7280",
                  cursor: "pointer",
                }}
              >
                {key === "all" ? t.filter_all : key === "s1" ? t.scenario_1 : t.scenario_2} ({count})
              </button>
            );
          })}
        </div>
      )}

      {!loading && !error && tasks.length === 0 && (
        <div style={{ textAlign: "center", padding: 64, color: "#9ca3af" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <p>{t.no_history}<a href="/upload" style={{ color: "#2563eb" }}>{t.go_upload}</a></p>
        </div>
      )}

      {tasks.length > 0 && (
        <div style={{ background: "#fff", borderRadius: 8, overflow: "hidden", border: "1px solid #e5e7eb" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f9fafb" }}>
                {headers.map((h, i) => (
                  <th key={i} style={{ padding: "10px 16px", textAlign: "left", fontSize: 13, color: "#6b7280", fontWeight: 600, borderBottom: "1px solid #e5e7eb" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tasks.filter(task => scenarioTab === "all" || task.scenario === scenarioTab).map(task => {
                const s = styles[task.status] ?? { color: "#6b7280", label: task.status };
                const isDel = deleting === task.task_id;
                return (
                  <tr
                    key={task.task_id}
                    style={{ borderTop: "1px solid #f1f5f9", cursor: "pointer", transition: "background 0.1s", opacity: isDel ? 0.4 : 1 }}
                    onMouseEnter={e => (e.currentTarget.style.background = "#f8fafc")}
                    onMouseLeave={e => (e.currentTarget.style.background = "")}
                    onClick={() => handleClick(task)}
                  >
                    <td style={{ padding: "12px 16px", fontSize: 14, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {task.file_name || <span style={{ color: "#9ca3af" }}>{t.unknown_file}</span>}
                    </td>
                    <td style={{ padding: "12px 16px", fontSize: 13 }}>
                      {task.scenario === "s1" ? t.scenario_1 : t.scenario_2}
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ display: "inline-block", padding: "2px 10px", borderRadius: 12, fontSize: 12, fontWeight: 600, color: s.color, background: s.color + "18" }}>
                        {s.label}
                      </span>
                      {task.status === "failed" && task.error && (
                        <div style={{ fontSize: 11, color: "#dc2626", marginTop: 2, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.error}</div>
                      )}
                    </td>
                    <td style={{ padding: "12px 16px", fontSize: 13, color: "#6b7280" }}>
                      {task.status === "running" ? `${task.progress} / ${task.total}` : task.status === "done" ? `${task.total} / ${task.total}` : "—"}
                    </td>
                    <td style={{ padding: "12px 16px", fontSize: 13, color: "#6b7280" }}>{fmt(task.created_at)}</td>
                    <td style={{ padding: "12px 16px", fontSize: 13, color: "#6b7280" }}>{fmt(task.finished_at)}</td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ color: "#2563eb", fontSize: 13, fontWeight: 500 }}>
                        {task.status === "done" ? t.view_result : task.status === "running" ? t.view_progress : "—"}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }} onClick={e => e.stopPropagation()}>
                      <button
                        onClick={e => handleDelete(e, task.task_id)}
                        disabled={isDel}
                        style={{ background: "none", border: "1px solid #fecaca", color: "#dc2626", borderRadius: 6, padding: "3px 10px", cursor: "pointer", fontSize: 12 }}
                        onMouseEnter={e => (e.currentTarget.style.background = "#fef2f2")}
                        onMouseLeave={e => (e.currentTarget.style.background = "none")}
                      >
                        {isDel ? t.deleting : t.delete}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function fmt(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}