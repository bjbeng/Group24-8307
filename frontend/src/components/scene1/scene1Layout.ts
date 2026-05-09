// 场景一专属布局。禁止 import 任何 scene2/* 内容。
// 修改本文件不会影响 S2。
import type { TranslationKeys } from "../../i18n/translations";

export interface Scene1Group {
  key: "content" | "deep" | "template";
  titleKey: keyof TranslationKeys;
  descriptionKey: keyof TranslationKeys;
  filterLabelKey: keyof TranslationKeys;
  dims: string[];
}

export const SCENE1_GROUPS: Scene1Group[] = [
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
];

export function normalizeScene1Dim(dim: string): string {
  return dim.replace(/_.*/, "");
}

export function scene1DimensionLabelKey(dim: string): keyof TranslationKeys {
  return `dim_${normalizeScene1Dim(dim)}` as keyof TranslationKeys;
}
