// 场景一结果面板。禁止 import scene2/* 相关模块。
import { useState } from "react";
import { AuditResult } from "../../api/audit";
import VerdictBadge from "../VerdictBadge";
import { useI18n } from "../../i18n/I18nContext";
import {
  SCENE1_GROUPS,
  normalizeScene1Dim,
  scene1DimensionLabelKey,
} from "./scene1Layout";

const sevColor: Record<string, string> = { high: "#dc2626", medium: "#d97706", low: "#16a34a" };
const sevBg: Record<string, string> = { high: "#fef2f2", medium: "#fffbeb", low: "#f0fdf4" };

type Severity = "high" | "medium" | "low";

interface IssueItem {
  dim: string;
  dimName: string;
  description: string;
  evidence: string;
  section_path: string;
  severity: Severity;
}

interface DimIssueGroup {
  dim: string;
  dimName: string;
  items: IssueItem[];
  severity: Severity;
}

interface ModuleGroup {
  key: string;
  dims: string[];
  groups: DimIssueGroup[];
}

function getDimName(t: ReturnType<typeof useI18n>["t"], dim: string, providedName?: string): string {
  if (providedName) return providedName;
  const key = scene1DimensionLabelKey(dim);
  const val = t[key];
  return typeof val === "string" ? val : normalizeScene1Dim(dim);
}

function groupByModule(result: AuditResult, t: ReturnType<typeof useI18n>["t"]): ModuleGroup[] {
  return SCENE1_GROUPS.map(group => {
    const dimSet = new Set(group.dims);
    const groups: DimIssueGroup[] = Object.entries(result.dimensions)
      .filter(([dim]) => dimSet.has(normalizeScene1Dim(dim)))
      .map(([dim, dimResult]) => {
        const short = normalizeScene1Dim(dim);
        const items: IssueItem[] = dimResult.findings.map(f => ({
          dim: short,
          dimName: dimResult.name || getDimName(t, dim),
          description: f.description,
          evidence: f.evidence || "",
          section_path: f.section_path || short,
          severity: f.severity as Severity,
        }));
        const maxSev: Severity = items.length > 0
          ? (items.some(i => i.severity === "high") ? "high" : items[0].severity)
          : "low";
        return { dim: short, dimName: getDimName(t, dim), items, severity: maxSev };
      });
    return { key: group.key, dims: [...group.dims], groups };
  });
}

function scoreOf(result: AuditResult, codes: string[]): number {
  return Object.entries(result.dimensions)
    .filter(([key]) => codes.includes(normalizeScene1Dim(key)))
    .reduce((s, [, v]) => s + (v.score ?? 0), 0);
}

const GROUP_MAX = { content: 60, deep: 36, template: 36 };

function norm100(raw: number, max: number): number {
  return max > 0 ? Math.round(raw / max * 100) : 0;
}

function SummaryCard({ result }: { result: AuditResult }) {
  const { t } = useI18n();
  const dims = Object.values(result.dimensions);
  const passCount = dims.filter(d => d.verdict === "pass").length;
  const totalScore = result.overall_score ?? 0;
  const maxScore = 100;

  const rawContent = scoreOf(result, ["C1", "C2", "C3", "C4", "C5"]);
  const rawDeep    = scoreOf(result, ["E1", "E2", "L2"]);
  const rawTmpl    = scoreOf(result, ["T1", "T2", "T3"]);
  const contentScore = norm100(rawContent, GROUP_MAX.content);
  const deepScore    = norm100(rawDeep, GROUP_MAX.deep);
  const tmplScore    = norm100(rawTmpl, GROUP_MAX.template);

  const allFindings = dims.flatMap(d => d.findings);
  const highCount   = allFindings.filter(f => f.severity === "high").length;
  const mediumCount = allFindings.filter(f => f.severity === "medium").length;
  const lowCount    = allFindings.filter(f => f.severity === "low").length;

  const statusText = result.overall_verdict === "pass"
    ? (highCount > 0 ? t.check_pass_with_issues : t.check_pass)
    : result.overall_verdict === "fail"
      ? t.check_fail
      : t.need_human_review;

  return (
    <div style={{ background: "#f8fafc", borderBottom: "1px solid #e5e7eb", padding: "20px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 16 }}>📄</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: "#1e293b" }}>{result.doc_name}</div>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>{t.audit_complete} · {result.elapsed_seconds.toFixed(1)}s · {statusText}</div>
        </div>
        <VerdictBadge verdict={result.overall_verdict} />
        {result.need_human_review && (
          <span style={{ background: "#fef3c7", color: "#92400e", padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600 }}>{t.need_human_review}</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 0, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
        <div style={{ flex: 1, padding: "12px 16px", borderRight: "1px solid #f1f5f9" }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>{t.risk_dist}</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {highCount > 0   && <span style={{ fontSize: 14, fontWeight: 800, color: "#dc2626" }}>🔴 {highCount}</span>}
            {mediumCount > 0  && <span style={{ fontSize: 14, fontWeight: 800, color: "#d97706" }}>🟡 {mediumCount}</span>}
            {lowCount > 0    && <span style={{ fontSize: 14, fontWeight: 800, color: "#16a34a" }}>🟢 {lowCount}</span>}
            {highCount === 0 && mediumCount === 0 && lowCount === 0 && <span style={{ fontSize: 13, color: "#9ca3af" }}>{t.no_problem}</span>}
          </div>
        </div>
        <div style={{ flex: 1, padding: "12px 16px", borderRight: "1px solid #f1f5f9", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{t.total_score}</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#1e293b" }}>{totalScore}<span style={{ fontSize: 12, fontWeight: 400, color: "#9ca3af" }}>/{maxScore}</span></div>
        </div>
        <div style={{ flex: 2, padding: "12px 16px", display: "flex", gap: 0 }}>
          <div style={{ flex: 1, textAlign: "center", borderRight: "1px solid #f1f5f9" }}>
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>{t.module_content}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#1e293b" }}>{contentScore}</div>
          </div>
          <div style={{ flex: 1, textAlign: "center", borderRight: "1px solid #f1f5f9" }}>
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>{t.module_deep}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#1e293b" }}>{deepScore}</div>
          </div>
          <div style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>{t.module_template}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#1e293b" }}>{tmplScore}</div>
          </div>
        </div>
        <div style={{ flex: 1, padding: "12px 16px", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{t.pass_dims}</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#15803d" }}>{passCount}<span style={{ fontSize: 12, fontWeight: 400, color: "#9ca3af" }}>/{dims.length}</span></div>
        </div>
      </div>
    </div>
  );
}

function DimRow({ group }: { group: DimIssueGroup }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const totalItems = group.items.length;
  const highItems  = group.items.filter(i => i.severity === "high").length;
  const sevLabel: Record<Severity, string> = { high: t.serious, medium: t.medium, low: t.low };

  return (
    <div style={{ marginBottom: 6 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 14px",
          background: "#f9fafb",
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          cursor: "pointer",
          fontSize: 13,
        }}
      >
        <span style={{ color: "#9ca3af", fontSize: 11 }}>{open ? "▼" : "▶"}</span>
        <span style={{ fontWeight: 600, color: "#374151" }}>[{group.dim}] {group.dimName}</span>
        {totalItems > 0 ? (
          <>
            <span style={{ marginLeft: 4, fontSize: 11, color: "#6b7280" }}>{totalItems}{t.items}</span>
            {highItems > 0 && (
              <span style={{ marginLeft: 4, background: "#dc2626", color: "#fff", padding: "1px 6px", borderRadius: 8, fontSize: 10, fontWeight: 700 }}>
                {t.serious}{highItems}{t.items}
              </span>
            )}
          </>
        ) : (
          <span style={{ marginLeft: 4, fontSize: 11, color: "#16a34a" }}>✅ {t.no_problem}</span>
        )}
      </div>

      {open && totalItems > 0 && (
        <div style={{ padding: "6px 14px 6px 32px", display: "flex", flexDirection: "column", gap: 6 }}>
          {group.items.map((item, i) => (
            <div key={i} style={{
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: 12,
              background: sevBg[item.severity] ?? "#f9fafb",
              border: `1px solid ${sevColor[item.severity] ?? "#888"}22`,
            }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 4 }}>
                <span style={{
                  background: sevColor[item.severity] ?? "#888",
                  color: "#fff", padding: "1px 6px", borderRadius: 6,
                  fontSize: 10, fontWeight: 700, flexShrink: 0,
                }}>{sevLabel[item.severity] ?? item.severity}</span>
                <span style={{ fontWeight: 600, color: "#374151", fontSize: 12 }}>{item.description}</span>
              </div>
              {item.evidence && (
                <div style={{ color: "#6b7280", fontSize: 11 }}>{t.evidence}：{item.evidence}</div>
              )}
              {item.section_path && item.section_path !== item.dim && (
                <div style={{ color: "#9ca3af", fontSize: 11, marginTop: 2 }}>{t.position}：{item.section_path}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModuleSection({ module }: { module: ModuleGroup }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(true);
  const totalItems = module.groups.reduce((s, g) => s + g.items.length, 0);
  const highItems  = module.groups.reduce((s, g) => s + g.items.filter(i => i.severity === "high").length, 0);

  const moduleLabels: Record<string, string> = {
    content:  t.module_content,
    deep:     t.module_deep,
    template: t.module_template,
  };
  const label = moduleLabels[module.key] ?? module.key;

  return (
    <div style={{ marginBottom: 12, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden" }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "12px 16px",
          background: open ? "#f0f9ff" : "#f8fafc",
          borderBottom: open ? "1px solid #e5e7eb" : "none",
          cursor: "pointer",
          fontWeight: 700,
          fontSize: 14,
          color: "#1e293b",
        }}
      >
        <span style={{ color: "#2563eb", fontSize: 12 }}>{open ? "▼" : "▶"}</span>
        <span>📋 {label}</span>
        {totalItems > 0 ? (
          <span style={{ marginLeft: "auto", fontSize: 11, color: "#6b7280" }}>
            {totalItems}{t.items}{highItems > 0 ? `（${t.serious}${highItems}${t.items}）` : ""}
          </span>
        ) : (
          <span style={{ marginLeft: "auto", fontSize: 11, color: "#16a34a" }}>✅ {t.check_pass}</span>
        )}
      </div>
      {open && (
        <div style={{ padding: "10px 12px", background: "#fff" }}>
          {module.groups.map(g => <DimRow key={g.dim} group={g} />)}
        </div>
      )}
    </div>
  );
}

type Filter = "all" | "high" | "content" | "deep" | "template";

export default function Scene1ResultPanel({ result }: { result: AuditResult }) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<Filter>("all");
  const modules = groupByModule(result, t);

  const filteredModules = filter === "all" ? modules
    : filter === "high" ? modules.map(m => ({
        ...m,
        groups: m.groups.map(g => ({
          ...g,
          items: g.items.filter(i => i.severity === "high"),
        })).filter(g => g.items.length > 0),
      })).filter(m => m.groups.length > 0)
    : modules.filter(m => m.key === filter);

  const filterLabels: Filter[] = ["all", "high", "content", "deep", "template"];
  const filterText: Record<Filter, string> = {
    all:      t.filter_all,
    high:     t.filter_serious,
    content:  t.filter_content,
    deep:     t.filter_deep,
    template: t.filter_template,
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", background: "#fff" }}>
      <SummaryCard result={result} />

      <div style={{ padding: "10px 16px", borderBottom: "1px solid #f1f5f9", display: "flex", gap: 8 }}>
        {filterLabels.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: "4px 12px",
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 500,
              border: "1px solid",
              borderColor: filter === f ? "#2563eb" : "#e5e7eb",
              background: filter === f ? "#eff6ff" : "#fff",
              color: filter === f ? "#1d4ed8" : "#6b7280",
              cursor: "pointer",
            }}
          >
            {filterText[f]}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>
          {t.problem_list}
        </div>
        {filteredModules.map(m => <ModuleSection key={m.key} module={m} />)}
      </div>

      <div style={{ padding: "12px 16px", borderTop: "1px solid #f1f5f9", display: "flex", gap: 10 }}>
        <button style={{
          flex: 1, padding: "10px", background: "#2563eb", color: "#fff",
          border: "none", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer",
        }}>
          {t.export_pdf}
        </button>
        <button style={{
          flex: 1, padding: "10px", background: "#fff", color: "#374151",
          border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer",
        }}>
          {t.export_annotated}
        </button>
      </div>
    </div>
  );
}