import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getAuditTask, createAuditWebSocket, type AuditTask } from "../api/audit";
import { useI18n } from "../i18n/I18nContext";
import ProgressBar from "../components/ProgressBar";

export default function AuditStatusPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const nav = useNavigate();
  const { t } = useI18n();
  const [task, setTask] = useState<AuditTask | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const doneRef = useRef(false);

  const handleDone = (status: string) => {
    if (doneRef.current) return;
    doneRef.current = true;
    wsRef.current?.close();
    if (status === "done") nav(`/results/${taskId}`);
  };

  useEffect(() => {
    if (!taskId) return;
    getAuditTask(taskId).then(r => {
      setTask(r.data);
      if (r.data.status === "done" || r.data.status === "failed") handleDone(r.data.status);
    });
    const ws = createAuditWebSocket(taskId);
    wsRef.current = ws;
    ws.onmessage = e => {
      const msg = JSON.parse(e.data);
      if (msg.type === "progress") {
        setLog(prev => [...prev, `✓ ${msg.dimension}: ${msg.verdict}`]);
        setTask(prev => prev ? { ...prev, progress: (prev.progress ?? 0) + 1 } : prev);
      } else if (msg.type === "status") {
        setTask(prev => prev ? { ...prev, status: msg.status, progress: msg.progress, total: msg.total, error: msg.error } : prev);
        if (msg.status === "done" || msg.status === "failed") handleDone(msg.status);
      }
    };
    const poll = setInterval(async () => {
      const r = await getAuditTask(taskId);
      setTask(r.data);
      if (r.data.status === "done" || r.data.status === "failed") {
        clearInterval(poll);
        handleDone(r.data.status);
      }
    }, 3000);
    return () => { clearInterval(poll); ws.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  if (!task) return <p style={{ padding: 32 }}>{t.loading}</p>;

  const pct = task.total > 0 ? Math.round((task.progress / task.total) * 100) : 0;
  const statusLabel = task.status === "pending" ? t.waiting : task.status === "running" ? t.running : task.status === "done" ? t.done : t.failed;

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>{t.audit_in_progress_title}</h1>

      <div style={{ background: "#fff", borderRadius: 8, padding: 24, marginBottom: 16, border: "1px solid #e5e7eb" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 12 }}>
          <span style={{ color: "#6b7280", fontSize: 13, fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {taskId}
          </span>
          <span style={{ padding: "2px 12px", borderRadius: 12, fontSize: 12, fontWeight: 600, background: task.status === "running" ? "#dbeafe" : task.status === "done" ? "#dcfce7" : "#fee2e2", color: task.status === "running" ? "#1d4ed8" : task.status === "done" ? "#15803d" : "#b91c1c" }}>
            {statusLabel}
          </span>
        </div>
        <ProgressBar value={task.progress} max={task.total} />
        <p style={{ marginTop: 8, color: "#6b7280", fontSize: 13 }}>
          {task.progress} / {task.total} {t.dimension_complete.replace("{pct}", String(pct))}
        </p>
      </div>

      {task.status === "failed" && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <p style={{ color: "#b91c1c", fontWeight: 600, marginBottom: 4 }}>{t.audit_failed_title}</p>
          <p style={{ color: "#dc2626", fontSize: 13, fontFamily: "monospace" }}>{task.error || "—"}</p>
          <button onClick={() => nav("/upload")} style={{ marginTop: 12, background: "#dc2626", color: "#fff", border: "none", padding: "8px 20px", borderRadius: 6, cursor: "pointer" }}>
            {t.return_reupload}
          </button>
        </div>
      )}

      <div style={{ background: "#fff", borderRadius: 8, padding: 24, border: "1px solid #e5e7eb" }}>
        <h3 style={{ marginBottom: 12, fontSize: 15 }}>{t.live_log}</h3>
        {log.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#9ca3af" }}>
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#3b82f6", animation: "pulse 1.5s infinite" }} />
            {task.status === "pending" ? t.waiting_dispatch : task.status === "running" ? t.audit_running_wait : t.no_log}
          </div>
        ) : (
          <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {log.map((l, i) => <li key={i} style={{ fontSize: 13, color: "#374151", fontFamily: "monospace" }}>{l}</li>)}
          </ul>
        )}
      </div>

      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }`}</style>
    </div>
  );
}