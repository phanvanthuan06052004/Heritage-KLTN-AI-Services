import { Source } from "./types";

export const fileIcons: Record<string, string> = {
  pdf: "picture_as_pdf",
  docx: "description",
  xlsx: "table_chart",
  csv: "table_chart",
  txt: "article",
  md: "article",
  pptx: "slideshow",
};

export function getFileExt(source: Source): string {
  const name = source.file_name || "";
  return name.split(".").pop()?.toLowerCase() || "";
}
