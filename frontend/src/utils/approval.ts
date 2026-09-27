/**
 * Wording for the approval flow, shared by every entry sheet.
 *
 * A کارشناس's submission goes to their department manager; a manager's own
 * submission is final as sent. The CEO is not a step in the chain.
 */
import { useAuthStore } from "@/stores/auth";

/** Does this account's submission need nobody else's approval? */
export function submitsFinal(): boolean {
  return !!useAuthStore().me?.can_approve;
}

/** The footer hint beside the submit button. */
export function submitHint(): string {
  return submitsFinal()
    ? "با ارسال، اطلاعات تأیید و مستقیم وارد داشبورد می‌شود."
    : "پس از تکمیل، برای تأیید مدیر بخش ارسال کنید.";
}

/** The toast after a successful submit. */
export function submittedMessage(): string {
  return submitsFinal() ? "ثبت و تأیید شد." : "برای تأیید مدیر بخش ارسال شد.";
}
