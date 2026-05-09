import { useI18n } from "../i18n/I18nContext";

const COLORS: Record<string, string> = {
  pass: "#16a34a",
  partial: "#d97706",
  fail: "#dc2626",
  uncertain: "#6b7280",
};

const VERDICT_KEYS: Record<string, "verdict_pass" | "verdict_fail" | "verdict_partial" | "verdict_uncertain"> = {
  pass: "verdict_pass",
  partial: "verdict_partial",
  fail: "verdict_fail",
  uncertain: "verdict_uncertain",
};

export default function VerdictBadge({ verdict }: { verdict: string }) {
  const { t } = useI18n();
  const labelKey = VERDICT_KEYS[verdict] ?? "verdict_uncertain";
  return (
    <span style={{ background: COLORS[verdict] ?? "#888", color: "#fff", padding: "2px 10px", borderRadius: 12, fontSize: 13, fontWeight: 600 }}>
      {t[labelKey] as string}
    </span>
  );
}