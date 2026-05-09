import { useState, useCallback, useEffect, useRef } from "react";
import { uploadFile, startAudit, getAuditTask, getAuditTaskResult, type AuditTask, type TaskSummary } from "../api/audit";
import { api } from "../api/client";
import { useI18n } from "../i18n/I18nContext";
import Scene1ResultPanel from "../components/scene1/Scene1ResultPanel";
import Scene2ResultPanel from "../components/scene2/Scene2ResultPanel";
import HistoryFloat from "../components/HistoryFloat";
import type { Scenario } from "../config/resultLayouts";

function DocPreview({ fileName }: { fileName: string }) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { t } = useI18n();

  useEffect(() => {
    if (!fileName) return;
    setLoading(true);
    setError("");
    setPdfUrl(null);
    const timer = setTimeout(async () => {
      try {
        const r = await api.get<Blob>(`/api/upload/pdf/${encodeURIComponent(fileName)}`, { responseType: "blob" });
        setPdfUrl(URL.createObjectURL(r.data));
      } catch { setError(t.loading); }
      finally { setLoading(false); }
    }, 1500);
    return () => { clearTimeout(timer); if (pdfUrl) URL.revokeObjectURL(pdfUrl); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileName]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "10px 16px", borderBottom: "1px solid #e5e7eb", background: "#f8fafc", flexShrink: 0, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13 }}>📄</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{fileName}</span>
      </div>
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        {loading && (
          <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, color: "#6b7280" }}>
            <div style={{ width: 32, height: 32, borderRadius: "50%", border: "3px solid #e5e7eb", borderTopColor: "#2563eb", animation: "spin 1s linear infinite" }} />
            <span style={{ fontSize: 13 }}>{t.uploading_hint}</span>
          </div>
        )}
        {!loading && error && (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#9ca3af", fontSize: 13 }}>{error}</div>
        )}
        {!loading && pdfUrl && <iframe src={pdfUrl} style={{ width: "100%", height: "100%", border: "none" }} title="Document Preview" />}
      </div>
    </div>
  );
}

export default function UploadPage() {
  const { t } = useI18n();
  const [scenario, setScenario] = useState<Scenario>("s1");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [uploadedName, setUploadedName] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<AuditTask | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showSplit = !!uploadedName;

  useEffect(() => {
    if (!taskId) return;
    pollRef.current = setInterval(async () => {
      const r = await getAuditTask(taskId);
      setTask(prev => ({ ...prev, ...r.data }));
      if ((r.data.status === "done" || r.data.status === "failed") && !r.data.result && r.data.result_ready) {
        const full = await getAuditTaskResult(taskId);
        setTask(full.data);
      }
      if (r.data.status === "done" || r.data.status === "failed") clearInterval(pollRef.current!);
    }, 3000);
    return () => clearInterval(pollRef.current!);
  }, [taskId]);

  const handleFile = useCallback(async (file: File) => {
    setError("");
    setUploading(true);
    setUploadedName(file.name);
    setTaskId(null);
    setTask(null);
    try {
      await uploadFile(file);
      const res = await startAudit(file.name, undefined, scenario);
      setTaskId(res.data.task_id);
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? t.operation_failed);
    } finally {
      setUploading(false);
    }
  }, [scenario, t]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleHistorySelect = (t: TaskSummary) => {
    setUploadedName(t.file_name);
    setTaskId(t.task_id);
    setScenario(t.scenario); // 历史任务的场景决定“问题清单/面板布局”
    getAuditTask(t.task_id).then(r => setTask(r.data));
  };

  if (showSplit) {
    return (
      <div style={{ display: "flex", height: "calc(100vh - 64px)", gap: 0, overflow: "hidden" }}>
        <div style={{ flex: 1, borderRight: "1px solid #2d2d3f", overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <DocPreview fileName={uploadedName} />
        </div>
        <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {!task || task.status === "pending" || task.status === "running" ? (
            <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, color: "#6b7280" }}>
              <div style={{ width: 48, height: 48, borderRadius: "50%", border: "4px solid #dbeafe", borderTopColor: "#2563eb", animation: "spin 1s linear infinite" }} />
              <p style={{ fontWeight: 500 }}>
                {task?.status === "running" ? `${t.audit_in_progress} ${task.progress}/${task.total}` : t.audit_pending}
              </p>
              {task?.summary && (
                <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, padding: "12px 16px", minWidth: 280 }}>
                  <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>Summary</div>
                  <div style={{ fontSize: 13, color: "#1e293b", fontWeight: 600 }}>{task.summary.doc_name || uploadedName}</div>
                  <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
                    {task.summary.overall_verdict || "running"} · {task.summary.dimensions_completed ?? task.progress}/{task.total}
                  </div>
                </div>
              )}
              <button onClick={() => { setUploadedName(""); setTaskId(null); setTask(null); }} style={{ fontSize: 13, color: "#2563eb", background: "none", border: "none", cursor: "pointer" }}>
                {t.re_upload}
              </button>
            </div>
          ) : task.status === "failed" ? (
            <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 32 }}>
              <div style={{ fontSize: 48 }}>❌</div>
              <p style={{ fontWeight: 600, color: "#b91c1c" }}>{t.audit_failed}</p>
              <p style={{ fontSize: 13, color: "#6b7280", textAlign: "center" }}>{task.error}</p>
              <button onClick={() => { setUploadedName(""); setTaskId(null); setTask(null); }} style={{ background: "#dc2626", color: "#fff", border: "none", padding: "8px 20px", borderRadius: 6, cursor: "pointer" }}>
                {t.retry}
              </button>
            </div>
          ) : task.result ? (
            scenario === "s2"
              ? <Scene2ResultPanel result={task.result} />
              : <Scene1ResultPanel result={task.result} />
          ) : null}
        </div>
        <button onClick={() => { setUploadedName(""); setTaskId(null); setTask(null); }} style={{ position: "fixed", top: 16, right: 100, zIndex: 100, background: "#fff", border: "1px solid #e5e7eb", padding: "6px 14px", borderRadius: 6, cursor: "pointer", fontSize: 13, boxShadow: "0 2px 8px rgba(0,0,0,0.08)" }}>
          {t.new_audit}
        </button>
        <HistoryFloat onSelect={handleHistorySelect} />
        <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h1 style={{ marginBottom: 24, marginTop: 0 }}>{t.upload_title}</h1>

      <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
        {(["s1", "s2"] as Scenario[]).map(s => (
          <button key={s} onClick={() => setScenario(s)} style={{ flex: 1, padding: "14px 18px", borderRadius: 8, border: `2px solid ${scenario === s ? "#2563eb" : "#e5e7eb"}`, background: scenario === s ? "#eff6ff" : "#fff", textAlign: "left", cursor: "pointer", transition: "all 0.15s" }}>
            <div style={{ fontWeight: 700, color: scenario === s ? "#1d4ed8" : "#374151", marginBottom: 4 }}>
              {s === "s1" ? t.scenario_1_title : t.scenario_2_title}
            </div>
            <div style={{ fontSize: 12, color: "#6b7280" }}>
              {s === "s1" ? t.scenario_1_desc : t.scenario_2_desc}
            </div>
          </button>
        ))}
      </div>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        style={{ border: `2px dashed ${dragging ? "#2563eb" : "#d1d5db"}`, borderRadius: 12, padding: 56, textAlign: "center", background: dragging ? "#eff6ff" : "#fff", transition: "all 0.2s" }}
      >
        <div style={{ fontSize: 48, marginBottom: 12 }}>{uploading ? "⏳" : "📄"}</div>
        <p style={{ fontSize: 17, color: "#374151", marginBottom: 8 }}>{uploading ? t.uploading : t.drag_or_click}</p>
        <p style={{ color: "#9ca3af", fontSize: 13, marginBottom: 24 }}>{t.supported_formats}</p>
        {!uploading && (
          <label style={{ background: "#2563eb", color: "#fff", padding: "10px 28px", borderRadius: 6, cursor: "pointer", fontWeight: 600 }}>
            {t.go_upload}
            <input type="file" accept=".doc,.docx,.pdf" hidden onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
          </label>
        )}
      </div>

      {error && <p style={{ marginTop: 16, color: "#dc2626" }}>{error}</p>}
      <HistoryFloat onSelect={handleHistorySelect} />
    </div>
  );
}
