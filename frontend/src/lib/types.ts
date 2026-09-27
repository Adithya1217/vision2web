export type Money = string;
export type Role = "owner" | "manager" | "staff";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Shop {
  id: number;
  name: string;
  legal_name: string | null;
  gstin: string | null;
  state_code: string;
  address: string | null;
  phone: string | null;
  timezone: string;
  currency: string;
  invoice_prefix: string;
  credit_note_prefix: string;
  po_prefix: string;
  default_credit_days: number;
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Me {
  user: User;
  shop: Shop;
  permissions: string[];
}

export interface Category {
  id: number;
  name: string;
}

export type StockStatus = "healthy" | "low" | "out";

export interface Product {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  category: Category | null;
  hsn_code: string | null;
  unit: string;
  sale_price: Money;
  cost_price: Money | null;
  gst_rate: Money;
  quantity: number;
  low_stock_threshold: number;
  reorder_quantity: number;
  is_active: boolean;
  stock_status: StockStatus;
  created_at: string;
  updated_at: string;
}

export type MovementType =
  | "opening"
  | "purchase_receipt"
  | "sale"
  | "return"
  | "manual_increase"
  | "manual_decrease"
  | "damage"
  | "correction";

export interface StockMovement {
  id: number;
  product_id: number;
  product_name: string;
  sku: string;
  movement_type: MovementType;
  quantity_delta: number;
  balance_after: number;
  reason: string | null;
  reference_type: string | null;
  reference_id: number | null;
  unit_cost: Money | null;
  created_by: number | null;
  created_at: string;
}

export interface Customer {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  gstin: string | null;
  state_code: string | null;
  address: string | null;
  credit_limit: Money | null;
  is_active: boolean;
  created_at: string;
  balance: Money;
  overdue_amount: Money;
}

export type PaymentMethod = "cash" | "upi" | "card" | "bank_transfer" | "credit";
export type InvoiceStatus = "draft" | "posted" | "cancelled";
export type PaymentStatus = "unpaid" | "partial" | "paid";

export interface InvoiceItem {
  id: number;
  line_no: number;
  product_id: number;
  product_name: string;
  sku: string;
  hsn_code: string | null;
  unit: string;
  quantity: number;
  unit_price: Money;
  gst_rate: Money;
  gross_amount: Money;
  discount_amount: Money;
  taxable_value: Money;
  cgst_amount: Money;
  sgst_amount: Money;
  igst_amount: Money;
  line_total: Money;
  returned_quantity: number;
}

export interface Payment {
  id: number;
  invoice_id: number;
  invoice_number: string | null;
  customer_id: number | null;
  credit_note_id: number | null;
  kind: "receipt" | "refund";
  method: PaymentMethod;
  amount: Money;
  reference: string | null;
  paid_at: string;
  created_by: number | null;
}

export interface CreditNote {
  id: number;
  number: string;
  invoice_id: number;
  invoice_number: string | null;
  customer_id: number | null;
  reason: string;
  restock: boolean;
  note_date: string;
  issued_at: string;
  taxable_total: Money;
  cgst_total: Money;
  sgst_total: Money;
  igst_total: Money;
  total: Money;
  refund_amount: Money;
  refund_method: PaymentMethod | null;
  items: { id: number; invoice_item_id: number; product_name: string; sku: string; quantity: number; line_total: Money }[];
}

export interface InvoiceSummary {
  id: number;
  number: string | null;
  status: InvoiceStatus;
  customer_id: number | null;
  customer_name: string | null;
  invoice_date: string | null;
  due_date: string | null;
  grand_total: Money;
  amount_paid: Money;
  credited_total: Money;
  balance_due: Money;
  payment_status: PaymentStatus;
  is_overdue: boolean;
  created_at: string;
  posted_at: string | null;
}

export interface Invoice extends InvoiceSummary {
  supply_type: "intra_state" | "inter_state";
  place_of_supply: string;
  notes: string | null;
  subtotal: Money;
  discount_total: Money;
  taxable_total: Money;
  cgst_total: Money;
  sgst_total: Money;
  igst_total: Money;
  credit_amount: Money;
  created_by: number | null;
  posted_by: number | null;
  items: InvoiceItem[];
  payments: Payment[];
  credit_notes: CreditNote[];
}

export interface LedgerEntry {
  id: number;
  entry_type: "invoice" | "payment" | "credit_note" | "refund";
  description: string;
  debit: Money;
  credit: Money;
  running_balance: Money;
  invoice_id: number | null;
  payment_id: number | null;
  credit_note_id: number | null;
  occurred_at: string;
}

export interface Ledger {
  customer: Customer;
  entries: LedgerEntry[];
  total_entries: number;
  balance: Money;
  invoice_outstanding: Money;
  overdue_amount: Money;
  oldest_overdue_date: string | null;
  reconciled: boolean;
  open_invoices: InvoiceSummary[];
}

export interface Supplier {
  id: number;
  name: string;
  contact_person: string | null;
  phone: string | null;
  email: string | null;
  gstin: string | null;
  state_code: string | null;
  address: string | null;
  is_active: boolean;
  created_at: string;
}

export type POStatus = "draft" | "sent" | "partial" | "received" | "cancelled";

export interface POItem {
  id: number;
  product_id: number;
  product_name: string;
  sku: string;
  ordered_quantity: number;
  received_quantity: number;
  unit_cost: Money;
  gst_rate: Money;
  line_subtotal: Money;
  line_tax: Money;
  line_total: Money;
}

export interface PurchaseOrder {
  id: number;
  number: string;
  supplier_id: number;
  supplier_name: string | null;
  status: POStatus;
  order_date: string;
  expected_date: string | null;
  subtotal: Money;
  tax_total: Money;
  total: Money;
  created_at: string;
  notes?: string | null;
  sent_at?: string | null;
  cancelled_at?: string | null;
  items?: POItem[];
}

export interface SalesPoint {
  period_start: string;
  period_end: string;
  invoice_count: number;
  units_sold: number;
  gross_sales: Money;
  returns: Money;
  net_sales: Money;
  taxable_value: Money;
  tax: Money;
}

export interface SalesSeries {
  start_date: string;
  end_date: string;
  timezone: string;
  period: "day" | "week" | "month";
  series: SalesPoint[];
  totals: Omit<SalesPoint, "period_start" | "period_end">;
}

export interface TopProductRow {
  rank: number;
  metric_value: Money | number;
  product_id: number;
  sku: string;
  product_name: string;
  units_sold: number;
  net_units: number;
  invoice_count: number;
  net_sales: Money;
}

export interface DashboardSummary {
  date: string;
  timezone: string;
  today: { revenue: Money; gross_sales: Money; returns: Money; invoice_count: number; units_sold: number };
  stock: { out_of_stock: number; low_stock: number; active_products: number };
  purchase_orders: { pending_count: number; pending_value: Money };
  khata: { outstanding: Money; customers_with_balance: number };
  invoices: { unpaid_total: Money; unpaid_count: number; overdue_total: Money; overdue_count: number };
}
