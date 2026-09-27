import type { InvoiceStatus, MovementType, PaymentMethod, PaymentStatus, POStatus } from "./types";

export function formatDate(value: string | null | undefined, timeZone?: string): string {
  if (!value) return "—";
  // Plain dates (YYYY-MM-DD) are already shop-local; do not shift them through a timezone.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  return new Date(value).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone });
}

export function formatDateTime(value: string | null | undefined, timeZone?: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });
}

/** Today's date (YYYY-MM-DD) in the shop timezone. */
export function todayIn(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(),
  );
}

export function addDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

export const METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: "Cash",
  upi: "UPI",
  card: "Card",
  bank_transfer: "Bank transfer",
  credit: "Credit (khata)",
};

export const MOVEMENT_LABEL: Record<MovementType, string> = {
  opening: "Opening balance",
  purchase_receipt: "Purchase receipt",
  sale: "Sale",
  return: "Return",
  manual_increase: "Manual increase",
  manual_decrease: "Manual decrease",
  damage: "Damage",
  correction: "Correction",
};

export const INVOICE_STATUS_TONE: Record<InvoiceStatus, "neutral" | "good" | "critical" | "info"> = {
  draft: "neutral",
  posted: "info",
  cancelled: "critical",
};

export const PAYMENT_STATUS_TONE: Record<PaymentStatus, "good" | "warning" | "critical"> = {
  paid: "good",
  partial: "warning",
  unpaid: "critical",
};

export const PO_STATUS_TONE: Record<POStatus, "neutral" | "info" | "warning" | "good" | "critical"> = {
  draft: "neutral",
  sent: "info",
  partial: "warning",
  received: "good",
  cancelled: "critical",
};

export const STATES: [string, string][] = [
  ["01", "Jammu & Kashmir"], ["02", "Himachal Pradesh"], ["03", "Punjab"], ["04", "Chandigarh"],
  ["05", "Uttarakhand"], ["06", "Haryana"], ["07", "Delhi"], ["08", "Rajasthan"], ["09", "Uttar Pradesh"],
  ["10", "Bihar"], ["11", "Sikkim"], ["12", "Arunachal Pradesh"], ["13", "Nagaland"], ["14", "Manipur"],
  ["15", "Mizoram"], ["16", "Tripura"], ["17", "Meghalaya"], ["18", "Assam"], ["19", "West Bengal"],
  ["20", "Jharkhand"], ["21", "Odisha"], ["22", "Chhattisgarh"], ["23", "Madhya Pradesh"], ["24", "Gujarat"],
  ["26", "Dadra & Nagar Haveli and Daman & Diu"], ["27", "Maharashtra"], ["29", "Karnataka"], ["30", "Goa"],
  ["31", "Lakshadweep"], ["32", "Kerala"], ["33", "Tamil Nadu"], ["34", "Puducherry"],
  ["35", "Andaman & Nicobar Islands"], ["36", "Telangana"], ["37", "Andhra Pradesh"], ["38", "Ladakh"],
];

export function stateName(code: string | null | undefined): string {
  return STATES.find(([c]) => c === code)?.[1] ?? code ?? "—";
}
