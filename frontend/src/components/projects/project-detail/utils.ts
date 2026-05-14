import { ProjectSource } from "./types";

export const WIKI_TYPE_TABS = ["all", "entity", "concept", "topic", "source"] as const;

export const fileIcons: Record<string, string> = {
  pdf: "picture_as_pdf",
  docx: "description",
  xlsx: "table_chart",
  csv: "table_chart",
  txt: "article",
  md: "article",
  pptx: "slideshow",
};

export function getFileExt(s: ProjectSource): string {
  const name = s.file_name || "";
  return name.split(".").pop()?.toLowerCase() || "";
}
