import { useEffect, useState } from "react";
import { listRules, createRuleSet, deleteRuleSet, type RuleSet } from "../api/rules";
import { useI18n } from "../i18n/I18nContext";

export default function RulesPage() {
  const { t } = useI18n();
  const [rules, setRules] = useState<RuleSet[]>([]);
  const [newId, setNewId] = useState("");
  const [newConfig, setNewConfig] = useState('{\n  "E1_engineer_per_km": 100,\n  "E1_section_km_gas": 30\n}');
  const [error, setError] = useState("");

  const load = () => listRules().then(r => setRules(r.data.rule_sets));
  useEffect(() => { load(); }, []);

  const create = async () => {
    setError("");
    try {
      const config = JSON.parse(newConfig);
      await createRuleSet(newId, config);
      setNewId(""); load();
    } catch {
      setError(t.json_error);
    }
  };

  const del = async (id: string) => {
    await deleteRuleSet(id);
    load();
  };

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>{t.rules_title}</h1>
      <div style={{ background: "#fff", borderRadius: 8, padding: 24, marginBottom: 24 }}>
        {rules.map(r => (
          <div key={r.rule_set_id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: "1px solid #e5e7eb" }}>
            <span style={{ fontWeight: 600, width: 160 }}>{r.rule_set_id}</span>
            <span style={{ flex: 1, fontSize: 12, color: "#6b7280", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {JSON.stringify(r.config)}
            </span>
            {r.rule_set_id !== "default" && (
              <button onClick={() => del(r.rule_set_id)} style={{ background: "none", border: "1px solid #e5e7eb", padding: "4px 10px", borderRadius: 4, color: "#dc2626" }}>{t.delete}</button>
            )}
          </div>
        ))}
      </div>
      <div style={{ background: "#fff", borderRadius: 8, padding: 24 }}>
        <h3 style={{ marginBottom: 16 }}>{t.new_rule_set}</h3>
        <input placeholder={t.rule_set_id} value={newId} onChange={e => setNewId(e.target.value)} style={{ width: "100%", padding: "8px 12px", border: "1px solid #ddd", borderRadius: 4, marginBottom: 12 }} />
        <textarea value={newConfig} onChange={e => setNewConfig(e.target.value)} rows={6} style={{ width: "100%", padding: "8px 12px", border: "1px solid #ddd", borderRadius: 4, fontFamily: "monospace", marginBottom: 12 }} />
        {error && <p style={{ color: "red", marginBottom: 8 }}>{error}</p>}
        <button onClick={create} style={{ background: "#2563eb", color: "#fff", border: "none", padding: "10px 24px", borderRadius: 6 }}>{t.create}</button>
      </div>
    </div>
  );
}