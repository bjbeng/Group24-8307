import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { getAuditTask, getAuditTaskResult, getAuditReport, type AuditResult, type DimensionResult } from "../api/audit";
import { useI18n } from "../i18n/I18nContext";
import VerdictBadge from "../components/VerdictBadge";
import Scene1ResultPanel from "../components/scene1/Scene1ResultPanel";
import Scene2ResultPanel from "../components/scene2/Scene2ResultPanel";
import { getDimensionLabelKey, inferScenarioFromResult } from "../config/resultLayouts";

const severityColor: Record<string, string> = { high: "#dc2626", medium: "#d97706", low: "#16a34a" };
const severityBg: Record<string, string> = { high: "#fef2f2", medium: "#fffbeb", low: "#f0fdf4" };

function getDimName(t: ReturnType<typeof useI18n>["t"], dim: DimensionResult): string {
  if (dim.name) return dim.name;
  const key = getDimensionLabelKey(dim.dimension);
  const val = t[key];
  return typeof val === "string" ? val : dim.dimension;
}

function DimCard({ dim, t }: { dim: DimensionResult; t: ReturnType<typeof useI18n>["t"] }) {
  const [open, setOpen] = useState(false);
  const label = getDimName(t, dim);

  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, marginBottom: 12, overflow: "hidden" }}>
      <div onClick={() => setOpen(value => !value)} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", background: "#f9fafb", cursor: "pointer" }}>
        <VerdictBadge verdict={dim.verdict} />
        <span style={{ fontWeight: 600 }}>[{dim.dimension}] {label}</span>
        <span style={{ marginLeft: "auto", color: "#6b7280", fontSize: 13 }}>{t.score_col}: {dim.score ?? "—"} | {t.confidence_col}: {dim.confidence}%</span>
        <span style={{ color: "#9ca3af" }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "12px 16px" }}>
          {dim.details && <p style={{ marginBottom: 12, color: "#374151" }}>{dim.details}</p>}
          {dim.findings.length === 0 ? <p style={{ color: "#9ca3af", fontSize: 13 }}>{t.no_problem}</p> : (
            <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
              {dim.findings.map((finding, index) => (
                <li key={index} style={{ padding: "8px 12px", background: severityBg[finding.severity] ?? "#f9fafb", borderRadius: 6 }}>
                  <strong style={{ color: severityColor[finding.severity] ?? "#6b7280" }}>[{finding.severity}]</strong> {finding.description}
                  {finding.evidence && <p style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>{t.evidence}：{finding.evidence}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}


export default function ResultsPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { t } = useI18n();
  const [result, setResult] = useState<AuditResult | null>(null);
  const [activeTab, setActiveTab] = useState<"report" | "details">("report");
  const [mdReport, setMdReport] = useState<string>("");
  const [loadingMd, setLoadingMd] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    getAuditTask(taskId).then(response => {
      if (response.data.result) {
        setResult(response.data.result);
        return;
      }
      if (response.data.result_ready) {
        getAuditTaskResult(taskId).then(full => setResult(full.data.result ?? null));
      }
    });
  }, [taskId]);

  const loadMdReport = () => {
    if (!taskId || mdReport) return;
    setLoadingMd(true);
    getAuditReport(taskId)
      .then(response => setMdReport(response.data as string))
      .catch(() => setMdReport(t.report_load_fail as string))
      .finally(() => setLoadingMd(false));
  };

  useEffect(() => {
    if (activeTab === "report") loadMdReport();
  }, [activeTab, t]);

  if (!result) return <p style={{ padding: 24 }}>{t.loading}</p>;

  const dims = Object.values(result.dimensions);
  const scenario = inferScenarioFromResult(result);
  const reportView = scenario === "s2"
    ? <Scene2ResultPanel result={result} />
    : <Scene1ResultPanel result={result} />;

  return (
    <div style={{ padding: "0 24px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{t.results_title}</h1>
        <VerdictBadge verdict={result.overall_verdict} />
        {result.need_human_review && (
          <span style={{ background: "#fef3c7", color: "#92400e", padding: "2px 10px", borderRadius: 12, fontSize: 13 }}>{t.need_human_review}</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 0, borderBottom: "2px solid #e5e7eb", marginBottom: 24 }}>
        {([ ["report", "audit_report"], ["details", "dimension_details"] ] as const).map(([tab, labelKey]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{ padding: "8px 20px", border: "none", borderBottom: activeTab === tab ? "2px solid #2563eb" : "2px solid transparent", background: "none", cursor: "pointer", fontWeight: activeTab === tab ? 600 : 400, color: activeTab === tab ? "#2563eb" : "#6b7280", marginBottom: -2, fontSize: 14 }}
          >
            {t[labelKey] as string}
          </button>
        ))}
      </div>

      {activeTab === "report" && (
        loadingMd ? <p style={{ color: "#6b7280" }}>{t.loading_report}</p> :
        mdReport ? (
          <div style={{ background: "#fff", borderRadius: 8, padding: "24px 28px", border: "1px solid #e5e7eb" }}>
            <ReactMarkdown>{mdReport}</ReactMarkdown>
          </div>
        ) : (
          reportView
        )
      )}

      {activeTab === "details" && (
        <div style={{ background: "#fff", borderRadius: 8, padding: 20, border: "1px solid #e5e7eb" }}>
          <h2 style={{ marginTop: 0, marginBottom: 16 }}>{t.dimension_details}</h2>
          {dims.map(dim => <DimCard key={dim.dimension} dim={dim} t={t} />)}
        </div>
      )}
    </div>
  );
}
