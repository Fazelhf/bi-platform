import api from "./client";
import type { OtpChallenge, TwoFactorStatus } from "@/types";

/**
 * Account security — currently just two-step login (ورود دو مرحله‌ای).
 *
 * Enrolling is deliberately three calls, not one: the server sends a code to
 * the number being enrolled and only switches 2FA on once that code comes
 * back, so a mistyped digit costs a retry instead of locking the account out.
 */
export const securityApi = {
  async status(): Promise<TwoFactorStatus> {
    const { data } = await api.get("/auth/2fa/");
    return data;
  },
  /** Send a code to `phone`; the account password is re-checked here. */
  async start(phone: string, password: string): Promise<OtpChallenge> {
    const { data } = await api.post("/auth/2fa/start/", { phone, password });
    return data;
  },
  async confirm(challenge: string, code: string): Promise<TwoFactorStatus> {
    const { data } = await api.post("/auth/2fa/confirm/", { challenge, code });
    return data;
  },
  async resend(challenge: string): Promise<OtpChallenge> {
    const { data } = await api.post("/auth/2fa/resend/", {
      challenge,
      purpose: "enable",
    });
    return data;
  },
  async disable(password: string): Promise<TwoFactorStatus> {
    const { data } = await api.post("/auth/2fa/disable/", { password });
    return data;
  },
};

/**
 * Ways into an account that don't need the password. All of these are called
 * while signed out, so they go through `api` without a token — the challenge
 * and the reset permit are the only things carried between steps.
 */
export const recoveryApi = {
  /** ورود با کد پیامکی — `identifier` is a username or a mobile number. */
  async otpLoginStart(identifier: string): Promise<OtpChallenge> {
    const { data } = await api.post("/auth/otp-login/start/", { identifier });
    return data;
  },
  async otpLoginVerify(challenge: string, code: string) {
    const { data } = await api.post("/auth/otp-login/verify/", { challenge, code });
    return data as { access: string; refresh: string };
  },

  /** فراموشی رمز — code first, then the new password. */
  async resetStart(identifier: string): Promise<OtpChallenge> {
    const { data } = await api.post("/auth/password-reset/start/", { identifier });
    return data;
  },
  async resetVerify(challenge: string, code: string): Promise<string> {
    const { data } = await api.post("/auth/password-reset/verify/", { challenge, code });
    return data.reset_token as string;
  },
  /** Sets the password and signs the user in, so there is no second login. */
  async resetConfirm(resetToken: string, password: string) {
    const { data } = await api.post("/auth/password-reset/confirm/", {
      reset_token: resetToken,
      password,
    });
    return data as { access: string; refresh: string };
  },

  /** Same endpoint for every code box; `purpose` picks the challenge kind. */
  async resend(challenge: string, purpose: "otp_login" | "reset"): Promise<OtpChallenge> {
    const { data } = await api.post("/auth/2fa/resend/", { challenge, purpose });
    return data;
  },
};

/** The Persian message the API sent, or a sensible fallback. */
export function apiMessage(err: any, fallback = "خطایی رخ داد. دوباره تلاش کنید."): string {
  const data = err?.response?.data;
  if (!data) return fallback;
  if (typeof data === "string") return data;
  if (data.detail) return String(data.detail);
  const first = Object.values(data)[0];
  if (Array.isArray(first)) return String(first[0]);
  return first ? String(first) : fallback;
}
