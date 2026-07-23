import { reactive } from "vue";

export type ToastType = "success" | "error" | "info";
interface Toast { id: number; type: ToastType; text: string }
interface Dialog {
  open: boolean;
  mode: "confirm" | "prompt";
  title: string;
  message: string;
  placeholder: string;
  value: string;
  danger: boolean;
  resolve: ((v: string | boolean | null) => void) | null;
}

const state = reactive({
  toasts: [] as Toast[],
  dialog: {
    open: false, mode: "confirm", title: "", message: "",
    placeholder: "", value: "", danger: false, resolve: null,
  } as Dialog,
});

let seq = 0;

function push(type: ToastType, text: string) {
  const id = ++seq;
  state.toasts.push({ id, type, text });
  window.setTimeout(() => {
    const i = state.toasts.findIndex((t) => t.id === id);
    if (i !== -1) state.toasts.splice(i, 1);
  }, 4000);
}

export const toast = {
  success: (t: string) => push("success", t),
  error: (t: string) => push("error", t),
  info: (t: string) => push("info", t),
};

/** Promise-based confirm — replaces window.confirm. */
export function confirm(opts: { title?: string; message: string; danger?: boolean }): Promise<boolean> {
  return new Promise((resolve) => {
    Object.assign(state.dialog, {
      open: true, mode: "confirm", title: opts.title ?? "تأیید",
      message: opts.message, danger: !!opts.danger, value: "",
      resolve: (v: any) => resolve(!!v),
    });
  });
}

/** Promise-based prompt — replaces window.prompt. Returns text or null. */
export function prompt(opts: { title?: string; message?: string; placeholder?: string; value?: string }): Promise<string | null> {
  return new Promise((resolve) => {
    Object.assign(state.dialog, {
      open: true, mode: "prompt", title: opts.title ?? "",
      message: opts.message ?? "", placeholder: opts.placeholder ?? "",
      value: opts.value ?? "", danger: false,
      resolve: (v: any) => resolve(typeof v === "string" ? v : null),
    });
  });
}

export function useUi() {
  return { state };
}
