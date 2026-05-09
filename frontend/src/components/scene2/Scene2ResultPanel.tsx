// 场景二结果面板。禁止 import scene1/* 相关模块。
import { useState } from "react";
import { AuditResult } from "../../api/audit";
import VerdictBadge from "../VerdictBadge";
import DonutChart from "../DonutChart";
import { useI18n } from "../../i18n/I18nContext";
import {
  SCENE2_GROUPS,
  normalizeScene2Dim,
  scene2DimensionLabelKey,
} from "./scene2Layout";

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
}

interface ModuleGroup {
  key: string;
  label: string;
  groups: DimIssueGroup[];
}

const LEGACY_S2_DIM_LABELS: Record<string, string> = {
  I1_evacuation_route: "I1 紧急疏散路线示意图",
  I2_assembly_point: "I2 紧急集合点示意图",
  I3_material: "I3 应急处置物资示意图",
  I4_entry_route: "I4 进场路线示意图",
  I5_hca_aerial: "I5 高后果区影像示意图",
  I6_approval_page: "I6 审批签字扫描页",
  L1_format: "L1 格式合规性",
  L2_standards: "L2 标准遵从性",
  L3_semantic: "L3 语义逻辑一致性",
  L4_risk_identification: "L4 风险点识别完整性",
  L5_emergency_measures: "L5 应急措施完整性",
  L6_professional: "L6 专业性审核",
};

function isLegacyScene2Result(result: AuditResult): boolean {
  const keys = Object.keys(result.dimensions ?? {});
  return keys.some((key) => key in LEGACY_S2_DIM_LABELS);
}

function parseSectionPath(path: string): number[] {
  if (!path) return [0, 0, 0];
  const upper = path.toUpperCase();
  if (upper === "ROOT" || upper === "") return [0, 0, 0];
  const nums = upper.split(/\.|\/|!/).filter(t => /^\d+$/.test(t)).map(Number);
  while (nums.length < 3) nums.push(0);
  return [nums[0] ?? 0, nums[1] ?? 0, nums[2] ?? 0];
}

function getDimName(
  t: ReturnType<typeof useI18n>["t"],
  dim: string,
  providedName?: string,
  isLegacyMode = false,
): string {
  if (providedName) return providedName;
  if (isLegacyMode && LEGACY_S2_DIM_LABELS[dim]) return LEGACY_S2_DIM_LABELS[dim];
  const key = scene2DimensionLabelKey(dim);
  const val = t[key];
  return typeof val === "string" ? val : normalizeScene2Dim(dim);
}

function groupByModule(
  result: AuditResult,
  t: ReturnType<typeof useI18n>["t"],
  isLegacyMode = false,
): ModuleGroup[] {
  return SCENE2_GROUPS
    .map(group => {
      const dimSet = new Set(group.dims);
      const groups: DimIssueGroup[] = Object.entries(result.dimensions)
        .filter(([dim]) => dimSet.has(normalizeScene2Dim(dim)))
        .map(([dim, dimResult]) => {
          const sortedFindings = [...dimResult.findings].sort((a, b) => {
            const aSeq = parseSectionPath(a.section_path || "");
            const bSeq = parseSectionPath(b.section_path || "");
            for (let i = 0; i < 3; i++) {
              if (aSeq[i] !== bSeq[i]) return aSeq[i] - bSeq[i];
            }
            return 0;
          });
          return {
            dim,
            dimName: getDimName(t, dim, dimResult.name, isLegacyMode),
            items: sortedFindings.map(f => ({
              dim,
              dimName: getDimName(t, dim, dimResult.name, isLegacyMode),
              description: f.description,
              evidence: f.evidence || "",
              section_path: f.section_path || dim,
              severity: f.severity as Severity,
            })),
          };
        });
      return {
        key: group.key,
        label: t[group.filterLabelKey] as string,
        groups,
      };
    });
}

function SummaryCard({ result }: { result: AuditResult }) {
  const { t } = useI18n();
  const dims = Object.values(result.dimensions);
  const passCount = dims.filter(d => d.verdict === "pass").length;
  const totalScore = result.normalized_score ?? dims.reduce((sum, dim) => sum + (dim.score ?? 0), 0);
  const maxScore = 100;
  const allFindings = dims.flatMap(dim => dim.findings);
  const highCount = allFindings.filter(f => f.severity === "high").length;
  const mediumCount = allFindings.filter(f => f.severity === "medium").length;
  const lowCount = allFindings.filter(f => f.severity === "low").length;

  const statusText = result.overall_verdict === "pass"
    ? (highCount > 0 ? t.check_pass_with_issues : t.check_pass)
    : result.overall_verdict === "fail"
      ? t.check_fail
      : t.need_human_review;

  return (
    <div style={{ background: "#f8fafc", borderBottom: "1px solid #e5e7eb", padding: "20px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 16 }}>🗺️</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: "#1e293b" }}>{result.doc_name}</div>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>
            {t.scenario_2_title} · {result.elapsed_seconds.toFixed(1)}s · {statusText}
          </div>
        </div>
        <VerdictBadge verdict={result.overall_verdict} />
        {result.need_human_review && (
          <span style={{ background: "#fef3c7", color: "#92400e", padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600 }}>
            {t.need_human_review}
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: 0, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
        <div style={{ flex: 1, padding: "12px 16px", borderRight: "1px solid #f1f5f9" }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>{t.risk_dist}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <DonutChart high={highCount} medium={mediumCount} low={lowCount} size={56} />
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {highCount > 0   && <span style={{ fontSize: 12, color: "#dc2626", fontWeight: 600 }}>{highCount} {t.serious}</span>}
              {mediumCount > 0 && <span style={{ fontSize: 12, color: "#d97706", fontWeight: 600 }}>{mediumCount} {t.medium}</span>}
              {lowCount > 0    && <span style={{ fontSize: 12, color: "#16a34a", fontWeight: 600 }}>{lowCount} {t.low}</span>}
              {highCount === 0 && mediumCount === 0 && lowCount === 0 && <span style={{ fontSize: 12, color: "#9ca3af" }}>{t.no_issue_found}</span>}
            </div>
          </div>
        </div>
        <div style={{ flex: 1, padding: "12px 16px", borderRight: "1px solid #f1f5f9", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{t.total_score}</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#1e293b" }}>
            {totalScore}<span style={{ fontSize: 12, fontWeight: 400, color: "#9ca3af" }}>/{maxScore}</span>
          </div>
        </div>
        <div style={{ flex: 1, padding: "12px 16px", textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{t.pass_dims}</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#15803d" }}>
            {passCount}<span style={{ fontSize: 12, fontWeight: 400, color: "#9ca3af" }}>/{dims.length}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function DimRow({ group }: { group: DimIssueGroup }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const totalItems = group.items.length;
  const highItems = group.items.filter(item => item.severity === "high").length;
  const sevLabel: Record<Severity, string> = { high: t.serious, medium: t.medium, low: t.low };

  return (
    <div style={{ marginBottom: 6 }}>
      <div
        onClick={() => setOpen(value => !value)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 14px", background: "#f9fafc",
          border: "1px solid #e5e7eb", borderRadius: 8,
          cursor: "pointer", fontSize: 13,
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
          <span style={{ marginLeft: 4, fontSize: 11, color: "#16a34a" }}>✅ {t.no_issue_found}</span>
        )}
      </div>

      {open && (
        <div style={{ padding: "6px 14px 6px 32px", display: "flex", flexDirection: "column", gap: 6 }}>
          {totalItems === 0 ? (
            <div style={{ padding: "12px 16px", color: "#16a34a", fontSize: 13 }}>✅ {t.no_issue_found}</div>
          ) : group.items.map((item, index) => (
            <div
              key={index}
              style={{
                padding: "8px 12px", borderRadius: 6, fontSize: 12,
                background: sevBg[item.severity] ?? "#f9fafb",
                border: `1px solid ${sevColor[item.severity] ?? "#888"}22`,
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 4 }}>
                <span
                  style={{
                    background: sevColor[item.severity] ?? "#888",
                    color: "#fff", padding: "1px 6px", borderRadius: 6,
                    fontSize: 10, fontWeight: 700, flexShrink: 0,
                  }}
                >
                  {sevLabel[item.severity] ?? item.severity}
                </span>
                <span style={{ fontWeight: 600, color: "#374151", fontSize: 12 }}>{item.description}</span>
              </div>
              {item.evidence && <div style={{ color: "#6b7280", fontSize: 11 }}>{t.evidence}：{item.evidence}</div>}
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
  const totalItems = module.groups.reduce((sum, group) => sum + group.items.length, 0);
  const highItems = module.groups.reduce((sum, group) => sum + group.items.filter(item => item.severity === "high").length, 0);

  return (
    <div style={{ marginBottom: 12, border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden" }}>
      <div
        onClick={() => setOpen(value => !value)}
        style={{
          display: "flex", alignItems: "center", gap: 10, padding: "12px 16px",
          background: open ? "#f0f9ff" : "#f8fafc",
          borderBottom: open ? "1px solid #e5e7eb" : "none",
          cursor: "pointer", fontWeight: 700, fontSize: 14, color: "#1e293b",
        }}
      >
        <span style={{ color: "#2563eb", fontSize: 12 }}>{open ? "▼" : "▶"}</span>
        <span>📋 {module.label}</span>
        {totalItems > 0 ? (
          <span style={{ marginLeft: "auto", fontSize: 11, color: "#6b7280" }}>
            {totalItems}{t.items}{highItems > 0 ? `（${t.serious}${highItems}${t.items}）` : ""}
          </span>
        ) : (
          <span style={{ marginLeft: "auto", fontSize: 11, color: "#16a34a" }}>✅ {t.no_issue_found}</span>
        )}
      </div>
      {open && (
        <div style={{ padding: "10px 12px", background: "#fff" }}>
          {module.groups.map(group => <DimRow key={group.dim} group={group} />)}
        </div>
      )}
    </div>
  );
}

type Filter = "all" | "high" | string;

export default function Scene2ResultPanel({ result }: { result: AuditResult }) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<Filter>("all");
  const legacyMode = isLegacyScene2Result(result);
  const modules = groupByModule(result, t, legacyMode);

  const filteredModules = filter === "all"
    ? modules
    : filter === "high"
      ? modules
          .map(module => ({
            ...module,
            groups: module.groups
              .map(group => ({ ...group, items: group.items.filter(item => item.severity === "high") }))
              .filter(group => group.items.length > 0),
          }))
          .filter(module => module.groups.length > 0)
      : modules.filter(module => module.key === filter);

  const filterItems = [
    { key: "all", label: t.filter_all },
    { key: "high", label: t.filter_serious },
    ...modules.map(module => ({ key: module.key, label: module.label })),
  ];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", background: "#fff" }}>
      <SummaryCard result={result} />

      <div style={{ padding: "10px 16px", borderBottom: "1px solid #f1f5f9", display: "flex", gap: 8 }}>
        {legacyMode && (
          <span
            style={{
              fontSize: 11,
              color: "#92400e",
              background: "#fef3c7",
              border: "1px solid #fcd34d",
              borderRadius: 999,
              padding: "4px 10px",
              marginRight: 6,
              alignSelf: "center",
            }}
          >
            Legacy S2
          </span>
        )}
        {filterItems.map(item => (
          <button
            key={item.key}
            onClick={() => setFilter(item.key)}
            style={{
              padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 500,
              border: "1px solid",
              borderColor: filter === item.key ? "#2563eb" : "#e5e7eb",
              background: filter === item.key ? "#eff6ff" : "#fff",
              color: filter === item.key ? "#1d4ed8" : "#6b7280",
              cursor: "pointer",
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>
          {t.problem_list}
        </div>
        {filteredModules.map(module => <ModuleSection key={module.key} module={module} />)}
      </div>

      <div style={{ padding: "12px 16px", borderTop: "1px solid #f1f5f9", display: "flex", gap: 10 }}>
        <button style={{ flex: 1, padding: "10px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          {t.export_pdf}
        </button>
        <button style={{ flex: 1, padding: "10px", background: "#fff", color: "#374151", border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          {t.export_annotated}
        </button>
      </div>
    </div>
  );
}