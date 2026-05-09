import { api } from "./client";

export interface RuleSet {
  rule_set_id: string;
  config: Record<string, unknown>;
}

export const listRules = () => api.get<{ rule_sets: RuleSet[] }>("/api/rules");
export const getRuleSet = (id: string) => api.get<RuleSet>(`/api/rules/${id}`);
export const createRuleSet = (rule_set_id: string, config: Record<string, unknown>) =>
  api.post("/api/rules", { rule_set_id, config });
export const deleteRuleSet = (id: string) => api.delete(`/api/rules/${id}`);
