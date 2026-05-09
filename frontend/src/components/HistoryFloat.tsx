import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { listAuditTasks, deleteAuditTask, type TaskSummary } from "../api/audit";
import { useI18n } from "../i18n/I18nContext";

interface HistoryFloatProps {
  onSelect: (task: TaskSummary) => void;
  limit?: number;
}

export default function HistoryFloat({ onSelect, limit = 30 }: HistoryFloatProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<TaskSummary[]>([]);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [scenarioFilter, setScenarioFilter] = useState<"all" | "s1" | "s2">("all");
  const nav = useNavigate();

  const statusStyle: Record<string, { color: string; bg: string; label: string }> = {
    pending: { color: "#92400e", bg: "#fef3c7", label: t.pending },
    running: { color: "#1d4ed8", bg: "#dbeafe", label: t.running },
    done:    { color: "#15803d", bg: "#dcfce7", label: t.done },
    failed:  { color: "#b91c1c", bg: "#fee2e2", label: t.failed },
  };

  const load = useCallback(() => {
    listAuditTasks(limit).then(r => setHistory(r.data.tasks)).catch(() => {});
  }, [limit]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);

  const handleDelete = async (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    setDeleting(taskId);
    try {
      await deleteAuditTask(taskId);
      setHistory(prev => prev.filter(task => task.task_id !== taskId));
    } catch {
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div style={{ position: "fixed", bottom: 32, right: 32, zIndex: 1000 }}>
      {open && (
        <div style={{ position: "absolute", bottom: 56, right: 0, width: 300, maxHeight: 420, background: "#fff", borderRadius: 12, boxShadow: "0 8px 32px rgba(0,0,0,0.18)", border: "1px solid #e5e7eb", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #f1f5f9", display: "flex", alignItems: "center", justifyContent: "space-between", background: "#f8fafc" }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: "#1e293b" }}>{t.history_title}</span>
            <button onClick={load} style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 16 }} title={t.refresh}>↻</button>
          </div>
          <div style={{ display: "flex", gap: 4, padding: "8px 12px", borderBottom: "1px solid #f1f5f9" }}>
            {(["all", "s1", "s2"] as const).map(key => (
              <button
                key={key}
                onClick={() => setScenarioFilter(key)}
                style={{
                  flex: 1, padding: "4px 8px", fontSize: 11, borderRadius: 6,
                  border: "1px solid", cursor: "pointer", fontWeight: 600,
                  borderColor: scenarioFilter === key ? "#2563eb" : "#e5e7eb",
                  background: scenarioFilter === key ? "#eff6ff" : "#fff",
                  color: scenarioFilter === key ? "#1d4ed8" : "#6b7280",
                }}
              >
                {key === "all" ? t.filter_all : key === "s1" ? t.scenario_1 : t.scenario_2}
              </button>
            ))}
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {(() => {
              const visible = scenarioFilter === "all" ? history : history.filter(item => item.scenario === scenarioFilter);
              if (visible.length === 0) return <p style={{ padding: 20, textAlign: "center", color: "#9ca3af", fontSize: 13 }}>{t.no_history}</p>;
              return visible.map(taskItem => {
              const isDel = deleting === taskItem.task_id;
              const sStyle = statusStyle[taskItem.status] ?? { color: "#6b7280", bg: "#f1f5f9", label: taskItem.status };
              return (
                <div
                  key={taskItem.task_id}
                  onClick={() => { onSelect(taskItem); setOpen(false); }}
                  style={{ padding: "10px 16px", borderBottom: "1px solid #f8fafc", cursor: "pointer", opacity: isDel ? 0.4 : 1, transition: "opacity 0.2s" }}
                  onMouseEnter={e => (e.currentTarget.style.background = "#f8fafc")}
                  onMouseLeave={e => (e.currentTarget.style.background = "")}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 4 }}>{taskItem.file_name || t.unknown_file}</div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600, color: sStyle.color, background: sStyle.bg }}>{sStyle.label}</span>
                        <span style={{ fontSize: 11, color: "#94a3b8" }}>{taskItem.scenario === "s1" ? t.scenario_1 : t.scenario_2}</span>
                        <span style={{ fontSize: 11, color: "#cbd5e1", marginLeft: "auto" }}>{fmt(taskItem.created_at)}</span>
                      </div>
                      {taskItem.status === "running" && (
                        <div style={{ marginTop: 5, background: "#e2e8f0", borderRadius: 4, height: 3 }}>
                          <div style={{ width: `${Math.round((taskItem.progress / taskItem.total) * 100)}%`, background: "#3b82f6", borderRadius: 4, height: "100%", transition: "width 0.4s" }} />
                        </div>
                      )}
                    </div>
                    <button onClick={e => handleDelete(e, taskItem.task_id)} disabled={isDel} title={t.delete} style={{ flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "#9ca3af", fontSize: 15, padding: "2px 4px", borderRadius: 4, lineHeight: 1, transition: "color 0.15s" }} onMouseEnter={e => (e.currentTarget.style.color = "#dc2626")} onMouseLeave={e => (e.currentTarget.style.color = "#9ca3af")}>
                      {isDel ? "…" : "🗑"}
                    </button>
                  </div>
                </div>
              );
            });
            })()}
          </div>
          <div style={{ padding: "8px 16px", borderTop: "1px solid #f1f5f9", textAlign: "center" }}>
            <button onClick={() => nav("/history")} style={{ background: "none", border: "none", color: "#2563eb", cursor: "pointer", fontSize: 13 }}>{t.history_title} →</button>
          </div>
        </div>
      )}
      <button onClick={() => setOpen(value => !value)} style={{ width: 48, height: 48, borderRadius: "50%", background: open ? "#1d4ed8" : "#2563eb", border: "none", color: "#fff", cursor: "pointer", boxShadow: "0 4px 16px rgba(37,99,235,0.4)", fontSize: 20, display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.2s" }} title={t.history_title}>
        {open ? "✕" : "🕘"}
      </button>
    </div>
  );
}

function fmt(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
