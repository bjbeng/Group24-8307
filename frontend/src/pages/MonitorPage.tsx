import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "../api/client";
import { api } from "../api/client";
import { useI18n } from "../i18n/I18nContext";

interface TraceEvent {
  task_id: string;
  stage: string;
  status: string;
  ts: number;
  doc_id: string;
  dimension: string;
  model: string;
  duration_ms: number;
  tokens_in: number;
  tokens_out: number;
  error: string;
}

interface MonitorSummary {
  ts: number;
  analyzed_events: number;
  stats: {
    stage_avg_ms: Record<string, number>;
    error_count: number;
    models_used: string[];
    total_tokens_in: number;
    total_tokens_out: number;
  };
  llm_analysis: {
    health: string;
    summary: string;
    bottleneck: string | null;
    cost_estimate_usd: number;
    recommendations: string[];
  };
  monitor_latency_ms: number;
  model: string;
}

export default function MonitorPage() {
  const { t } = useI18n();
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [summary, setSummary] = useState<MonitorSummary | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<{ events: TraceEvent[] }>("/api/monitor/traces?limit=50")
      .then(r => setEvents(r.data.events.reverse()))
      .catch(() => {});
    api.get<MonitorSummary>("/api/monitor/summary")
      .then(r => { if (r.data && r.data.ts) setSummary(r.data); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/api/monitor/ws`);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = e => {
      const msg = JSON.parse(e.data);
      if (msg.type === "trace") {
        setEvents(prev => [...prev.slice(-199), msg.event]);
        setTimeout(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }), 50);
      } else if (msg.type === "monitor_summary") {
        setSummary(msg.summary);
      }
    };
    return () => ws.close();
  }, []);

  const health = summary?.llm_analysis?.health ?? "unknown";
  const healthColor = { healthy: "#16a34a", degraded: "#d97706", critical: "#dc2626", unknown: "#6b7280" }[health] ?? "#6b7280";
  const healthLabel = health === "healthy" ? t.healthy : health === "degraded" ? t.degraded : health === "critical" ? t.critical : t.unknown;

  const stageLabel = (stage: string) => {
    const key = `stage_${stage}` as keyof typeof t;
    const val = t[key];
    return typeof val === "string" ? val : stage;
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{t.monitor_title}</h1>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 12px", borderRadius: 20, background: connected ? "#dcfce7" : "#fee2e2", color: connected ? "#16a34a" : "#dc2626", fontSize: 13, fontWeight: 600 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
          {connected ? t.connected : t.not_connected}
        </span>
      </div>

      {summary && (
        <div style={{ background: "#fff", borderRadius: 10, padding: 24, marginBottom: 24, border: `2px solid ${healthColor}22`, boxShadow: "0 1px 4px #0001" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
            <span style={{ background: healthColor + "22", color: healthColor, padding: "4px 14px", borderRadius: 20, fontWeight: 700, fontSize: 14, border: `1px solid ${healthColor}44` }}>
              {healthLabel}
            </span>
            <span style={{ color: "#6b7280", fontSize: 13 }}>
              {t.monitor_llm}：{summary.model} | {t.analyzed_events.replace("{count}", String(summary.analyzed_events))}
            </span>
          </div>
          <p style={{ fontSize: 15, color: "#111827", margin: "0 0 16px", fontWeight: 500 }}>{summary.llm_analysis?.summary}</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
            {[
              { label: t.input_token, value: summary.stats.total_tokens_in.toLocaleString() },
              { label: t.output_token, value: summary.stats.total_tokens_out.toLocaleString() },
              { label: t.error_count, value: String(summary.stats.error_count) },
              { label: t.api_cost_estimate, value: `$${summary.llm_analysis?.cost_estimate_usd?.toFixed(4) ?? "—"}` },
            ].map(({ label, value }) => (
              <div key={label} style={{ background: "#f8fafc", borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>{value}</div>
              </div>
            ))}
          </div>
          {summary.llm_analysis?.bottleneck && (
            <div style={{ background: "#fffbeb", borderRadius: 6, padding: "8px 12px", fontSize: 13, color: "#92400e", marginBottom: 12 }}>
              ⚡ {t.bottleneck_stage}：<strong>{stageLabel(summary.llm_analysis.bottleneck)}</strong>
              ({t.avg_time} {summary.stats.stage_avg_ms[summary.llm_analysis.bottleneck]?.toFixed(0)}ms)
            </div>
          )}
          {summary.llm_analysis?.recommendations?.length > 0 && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#374151", marginBottom: 6 }}>{t.recommendations}:</div>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: "#4b5563" }}>
                {summary.llm_analysis.recommendations.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {summary?.stats.stage_avg_ms && Object.keys(summary.stats.stage_avg_ms).length > 0 && (
        <div style={{ background: "#fff", borderRadius: 10, padding: 20, marginBottom: 24, boxShadow: "0 1px 4px #0001" }}>
          <h3 style={{ margin: "0 0 16px", fontSize: 15 }}>{t.stage_avg_time}</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {Object.entries(summary.stats.stage_avg_ms).sort((a, b) => b[1] - a[1]).map(([stage, ms]) => {
              const max = Math.max(...Object.values(summary.stats.stage_avg_ms));
              return (
                <div key={stage} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 140, fontSize: 12, color: "#6b7280", flexShrink: 0 }}>{stageLabel(stage)}</div>
                  <div style={{ flex: 1, background: "#f1f5f9", borderRadius: 4, height: 20, overflow: "hidden" }}>
                    <div style={{ width: `${(ms / max) * 100}%`, background: ms > 5000 ? "#ef4444" : ms > 2000 ? "#f59e0b" : "#3b82f6", height: "100%", borderRadius: 4, transition: "width 0.3s" }} />
                  </div>
                  <div style={{ width: 70, fontSize: 12, color: "#374151", textAlign: "right", flexShrink: 0 }}>{ms.toFixed(0)} ms</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div style={{ background: "#fff", borderRadius: 10, padding: 20, boxShadow: "0 1px 4px #0001" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>{t.event_stream}</h3>
          <button onClick={() => setEvents([])} style={{ fontSize: 12, color: "#6b7280", background: "none", border: "1px solid #e5e7eb", borderRadius: 4, padding: "4px 10px", cursor: "pointer" }}>{t.clear}</button>
        </div>
        <div ref={listRef} style={{ height: 360, overflowY: "auto", fontFamily: "monospace", fontSize: 12 }}>
          {events.length === 0 ? (
            <p style={{ color: "#9ca3af", textAlign: "center", marginTop: 48 }}>{t.waiting_events}</p>
          ) : (
            events.map((ev, i) => (
              <div key={i} style={{ padding: "5px 8px", borderRadius: 4, marginBottom: 2, background: ev.status === "error" ? "#fef2f2" : ev.status === "done" ? "#f0fdf4" : "#f8fafc", borderLeft: `3px solid ${ev.status === "error" ? "#ef4444" : ev.status === "done" ? "#22c55e" : "#94a3b8"}`, display: "flex", gap: 10, alignItems: "baseline" }}>
                <span style={{ color: "#9ca3af", flexShrink: 0 }}>{new Date(ev.ts * 1000).toLocaleTimeString("zh-CN")}</span>
                <span style={{ color: "#6b7280", flexShrink: 0 }}>{stageLabel(ev.stage)}</span>
                {ev.dimension && <span style={{ color: "#7c3aed" }}>[{ev.dimension}]</span>}
                {ev.model && <span style={{ color: "#0369a1" }}>{ev.model}</span>}
                {ev.duration_ms > 0 && <span style={{ color: "#374151" }}>{ev.duration_ms.toFixed(0)}ms</span>}
                {ev.tokens_in > 0 && <span style={{ color: "#065f46" }}>↑{ev.tokens_in} ↓{ev.tokens_out}</span>}
                {ev.error && <span style={{ color: "#dc2626" }}>{ev.error}</span>}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}