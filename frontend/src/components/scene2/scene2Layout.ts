// 场景二专属布局。禁止 import 任何 scene1/* 内容。
// 修改本文件不会影响 S1。
import type { TranslationKeys } from "../../i18n/translations";

export interface Scene2Group {
  key: "visual" | "text" | "risk";
  titleKey: keyof TranslationKeys;
  descriptionKey: keyof TranslationKeys;
  filterLabelKey: keyof TranslationKeys;
  dims: string[];
}

export const SCENE2_GROUPS: Scene2Group[] = [
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
];

export function normalizeScene2Dim(dim: string): string {
  return dim.replace(/_.*/, "");
}

export function scene2DimensionLabelKey(dim: string): keyof TranslationKeys {
  return `dim_${normalizeScene2Dim(dim)}` as keyof TranslationKeys;
}