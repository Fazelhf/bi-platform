import type { AxiosResponse } from "axios";

/**
 * Save a binary response as a file.
 *
 * The filename comes from the server, RFC 5987 encoded, because a Persian
 * name does not survive a plain `filename=` header — and a folder of files
 * called `export.xlsx (3)` is the reason the name matters.
 */
export function saveAsFile(res: AxiosResponse<Blob>, fallback: string): void {
  const disp = String(res.headers["content-disposition"] ?? "");
  const match = /filename\*=UTF-8''([^;]+)/.exec(disp);
  const name = match ? decodeURIComponent(match[1]) : fallback;

  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
