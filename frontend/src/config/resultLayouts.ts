import type { AuditResult } from "../api/audit";
import type { TranslationKeys } from "../i18n/translations";

export type Scenario = "s1" | "s2";
export type TranslationKey = keyof TranslationKeys;

export interface ResultLayoutGroup {
  key: string;
  titleKey: TranslationKey;
  descriptionKey: TranslationKey;
  filterLabelKey: TranslationKey;
  dims: string[];
}

export interface ResultLayout {
  scenario: Scenario;
  groups: ResultLayoutGroup[];
}

const S1_LAYOUT: ResultLayout = {
  scenario: "s1",
  groups: [
    {
      key: "content",
      titleKey: "part1_content_issues",
      descriptionKey: "part1_desc",
      filterLabelKey: "filter_content",
      dims: ["C1", "C2", "C3", "C4", "C5"],
    },
    {
      key: "deep",
      titleKey: "part2_deep_issues",
      descriptionKey: "part2_desc",
      filterLabelKey: "filter_deep",
      dims: ["E1", "E2", "L2"],
    },
    {
      key: "template",
      titleKey: "part3_template_issues",
      descriptionKey: "part3_desc",
      filterLabelKey: "filter_template",
      dims: ["T1", "T2", "T3"],
    },
  ],
};

const S2_LAYOUT: ResultLayout = {
  scenario: "s2",
  groups: [
    {
      key: "visual",
      titleKey: "part1_scene2_visual_issues",
      descriptionKey: "part1_scene2_visual_desc",
      filterLabelKey: "filter_scene2_visual",
      dims: ["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8"],
    },
    {
      key: "text",
      titleKey: "part2_scene2_text_issues",
      descriptionKey: "part2_scene2_text_desc",
      filterLabelKey: "filter_scene2_text",
      dims: ["L1", "L2", "L3", "L4", "L5"],
    },
    {
      key: "risk",
      titleKey: "part3_scene2_risk_issues",
      descriptionKey: "part3_scene2_risk_desc",
      filterLabelKey: "filter_scene2_risk",
      dims: ["L6"],
    },
  ],
};

const LAYOUTS: Record<Scenario, ResultLayout> = {
  s1: S1_LAYOUT,
  s2: S2_LAYOUT,
};

export function inferScenarioFromResult(result: AuditResult & { scenario?: Scenario }): Scenario {
  if (result.scenario === "s1" || result.scenario === "s2") return result.scenario;
  const keys = Object.keys(result.dimensions ?? {});
  return keys.some(key => /^I\d/.test(key)) ? "s2" : "s1";
}

export function getResultLayout(scenario: Scenario): ResultLayout {
  return LAYOUTS[scenario];
}

export function getDimensionLabelKey(dim: string): TranslationKey {
  const normalized = dim.replace(/_.*/, "");
  return `dim_${normalized}` as TranslationKey;
}
