import { AlertTriangle, CheckCircle2, CircleSlash, Clock } from "lucide-react";

import { Badge } from "@/components/ui";
import { INVOICE_STATUS_TONE, PAYMENT_STATUS_TONE, PO_STATUS_TONE } from "@/lib/format";
import type { InvoiceStatus, PaymentStatus, POStatus, StockStatus } from "@/lib/types";

// Status colour is always paired with an icon and a label, never colour alone.
export function StockBadge({ status }: { status: StockStatus }) {
  if (status === "out")
    return (
      <Badge tone="critical">
        <CircleSlash className="h-3 w-3" aria-hidden /> Out of stock
      </Badge>
    );
  if (status === "low")
    return (
      <Badge tone="warning">
        <AlertTriangle className="h-3 w-3" aria-hidden /> Low
      </Badge>
    );
  return (
    <Badge tone="good">
      <CheckCircle2 className="h-3 w-3" aria-hidden /> Healthy
    </Badge>
  );
}

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return <Badge tone={INVOICE_STATUS_TONE[status]}>{status}</Badge>;
}

export function PaymentBadge({ status, overdue }: { status: PaymentStatus; overdue?: boolean }) {
  if (overdue)
    return (
      <Badge tone="critical">
        <Clock className="h-3 w-3" aria-hidden /> Overdue
      </Badge>
    );
  const Icon = status === "paid" ? CheckCircle2 : status === "partial" ? Clock : AlertTriangle;
  return (
    <Badge tone={PAYMENT_STATUS_TONE[status]}>
      <Icon className="h-3 w-3" aria-hidden /> {status}
    </Badge>
  );
}

export function POStatusBadge({ status }: { status: POStatus }) {
  return <Badge tone={PO_STATUS_TONE[status]}>{status}</Badge>;
}
