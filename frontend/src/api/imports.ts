/**
 * ورود اکسل — the shared check-then-confirm import for فروش ۲ and مالی.
 * Every import has a sample workbook (with a «راهنما» sheet), a check that
 * saves nothing, and a confirm that writes the valid rows.
 */
import api from "./client";

export type ImportStatus = "new" | "changed" | "same" | "error";

export interface ImportParam {
  name: string;
  label: string;
  kind: "month" | "select";
  options: { value: number | string; label: string }[] | null;
}

export interface ImporterInfo {
  key: string;
  title: string;
  section: string;
  description: string;
  columns: { name: string; required: boolean; kind: string; help: string; choices: string[] | null }[];
  params: ImportParam[];
}

export interface ImportResult {
  title: string;
  counts: Record<ImportStatus, number>;
  written: number | null;
  columns: string[];
  rows: { n: number; sheet: string; values: Record<string, unknown>; status: ImportStatus; message: string }[];
}

export const importsApi = {
  list: (section?: string) =>
    api.get<ImporterInfo[]>("/imports/", { params: section ? { section } : {} }).then((r) => r.data),
  async template(key: string) {
    const r = await api.get(`/imports/${key}/template/`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `نمونه-${key}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  },
  run: (key: string, file: File, params: Record<string, string | number>, confirm = false) => {
    const fd = new FormData();
    fd.append("file", file);
    for (const [k, v] of Object.entries(params)) fd.append(k, String(v));
    if (confirm) fd.append("confirm", "1");
    return api.post<ImportResult>(`/imports/${key}/run/`, fd).then((r) => r.data);
  },
};
