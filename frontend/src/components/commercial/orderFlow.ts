import type { OrderStatus } from "@/api/commercial";

/**
 * جریان سفارش خرید داخلی.
 *
 * The server only lets an order move forward (PurchaseOrder.FLOW); this is the
 * same order, with the words the department uses for each step's button.
 */
export const ORDER_STEPS: { status: OrderStatus; label: string; action: string }[] = [
  { status: "pending", label: "در انتظار تایید", action: "" },
  { status: "buying", label: "در حال خرید", action: "تایید شد، خرید انجام شود" },
  { status: "shipped", label: "ارسال شده", action: "تامین‌کننده ارسال کرد" },
  { status: "delivered", label: "تحویل شد", action: "تحویل انبار شد" },
];

export const ORDER_STATUS_CLASS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  buying: "bg-sky-100 text-sky-700",
  shipped: "bg-violet-100 text-violet-700",
  delivered: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-500",
};

/** Position on the ORDER_STEPS bar; -1 for a cancelled order. */
export const orderStepIndex = (status: OrderStatus) =>
  ORDER_STEPS.findIndex((s) => s.status === status);

/** The step after this one, or null when there is nothing left to do. */
export function nextOrderStep(status: OrderStatus) {
  const i = ORDER_STEPS.findIndex((s) => s.status === status);
  if (i < 0 || i === ORDER_STEPS.length - 1) return null;
  return ORDER_STEPS[i + 1];
}

/** Whether the order is still on its way (and so may still be cancelled). */
export const isLiveOrder = (status: OrderStatus) =>
  status !== "delivered" && status !== "cancelled";
