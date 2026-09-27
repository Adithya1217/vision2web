"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Download } from "lucide-react";
import { useMemo, useState } from "react";

import { RankedBarChart, SalesTrendChart, type TrendRow } from "@/components/charts";
import { Button, Card, CardHeader, ErrorBanner, Input, PageHeader, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { addDays, formatDate, METHOD_LABEL, MOVEMENT_LABEL, todayIn } from "@/lib/format";
import { formatINR } from "@/lib/money";
import type { MovementType, PaymentMethod } from "@/lib/types";

type Col = { key: string; label: string; money?: boolean; num?: boolean; render?: (row: Row) => React.ReactNode };
type Row = Record<string, unknown>;

const TABS = [
  { id: "sales", label: "Sales" },
  { id: "top", label: "Top products" },
  { id: "payments", label: "Payments" },
  { id: "invoices", label: "Invoices" },
  { id: "khata", label: "Khata" },
  { id: "inventory", label: "Inventory" },
  { id: "po", label: "Purchases" },
  { id: "gst", label: "GST", perm: "reports.tax" },
  { id: "profit", label: "Profit", perm: "reports.tax" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function ReportsPage() {
  const { me, can } = useAuth();
  const tz = me?.shop.timezone ?? "Asia/Kolkata";
  const today = todayIn(tz);
  const [tab, setTab] = useState<TabId>("sales");
  const [preset, setPreset] = useState("30");
  const [start, setStart] = useState(addDays(today, -29));
  const [end, setEnd] = useState(today);

  const applyPreset = (p: string) => {
    setPreset(p);
    if (p === "today") [setStart, setEnd].forEach((f) => f(today));
    else if (p === "mtd") {
      setStart(today.slice(0, 8) + "01");
      setEnd(today);
    } else if (p === "lastmonth") {
      const firstThis = today.slice(0, 8) + "01";
      const lastPrev = addDays(firstThis, -1);
      setStart(lastPrev.slice(0, 8) + "01");
      setEnd(lastPrev);
    } else if (p !== "custom") {
      setStart(addDays(today, -(Number(p) - 1)));
      setEnd(today);
    }
  };

  const range = { start_date: start, end_date: end };
  const tabs = TABS.filter((t) => !("perm" in t) || can(t.perm));

  return (
    <>
      <PageHeader title="Reports" subtitle={`All dates are in the shop timezone (${tz}); ranges include both ends.`} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={preset} onChange={(e) => applyPreset(e.target.value)} className="w-auto" aria-label="Date range">
          <option value="today">Today</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
          <option value="mtd">Month to date</option>
          <option value="lastmonth">Last month</option>
          <option value="custom">Custom</option>
        </Select>
        <Input type="date" value={start} max={end} onChange={(e) => { setStart(e.target.value); setPreset("custom"); }} className="w-auto" aria-label="Start date" />
        <span className="text-ink-3">to</span>
        <Input type="date" value={end} min={start} onChange={(e) => { setEnd(e.target.value); setPreset("custom"); }} className="w-auto" aria-label="End date" />
      </div>
      <div role="tablist" aria-label="Reports" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
              tab === t.id ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "sales" && <SalesReport range={range} />}
      {tab === "top" && <TopReport range={range} />}
      {tab === "payments" && <PaymentsReport range={range} />}
      {tab === "invoices" && <InvoicesReport range={range} />}
      {tab === "khata" && <KhataReport />}
      {tab === "inventory" && <InventoryReport range={range} />}
      {tab === "po" && <POReport range={range} />}
      {tab === "gst" && <GSTReport range={range} />}
      {tab === "profit" && <ProfitReport range={range} />}
    </>
  );
}

type Range = { start_date: string; end_date: string };

function useReport<T>(path: string, params: Record<string, string | number> = {}) {
  return useQuery({ queryKey: ["report", path, params], queryFn: () => api.get<T>(path, params) });
}

function Loading({ q }: { q: { isLoading: boolean; error: unknown } }) {
  if (q.isLoading) return <Spinner />;
  return <ErrorBanner error={q.error} />;
}

function cell(row: Row, c: Col): React.ReactNode {
  if (c.render) return c.render(row);
  const v = row[c.key];
  if (v === null || v === undefined) return "—";
  if (c.money) return formatINR(String(v));
  return String(v);
}

function toCsv(rows: Row[], cols: Col[]): string {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const lines = [cols.map((c) => esc(c.label)).join(",")];
  for (const r of rows) lines.push(cols.map((c) => esc(String(r[c.key] ?? ""))).join(","));
  return lines.join("\n");
}

function DataTable({ title, subtitle, rows, cols, filename }: { title: string; subtitle?: string; rows: Row[]; cols: Col[]; filename: string }) {
  const download = () => {
    const blob = new Blob([toCsv(rows, cols)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${filename}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        actions={
          rows.length > 0 && (
            <Button size="sm" variant="ghost" onClick={download}>
              <Download className="h-3.5 w-3.5" /> CSV
            </Button>
          )
        }
      />
      {rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-ink-3">No data for this period.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              {cols.map((c) => (
                <Th key={c.key} className={c.money || c.num ? "text-right" : ""}>
                  {c.label}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {rows.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <Td key={c.key} className={c.money || c.num ? "text-right" : ""}>
                    {cell(r, c)}
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function Stats({ items }: { items: { label: string; value: string; note?: string }[] }) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
      {items.map((s) => (
        <Card key={s.label} className="p-4">
          <p className="text-xs text-ink-3">{s.label}</p>
          <p className="mt-1 text-xl font-semibold">{s.value}</p>
          {s.note && <p className="text-xs text-ink-3">{s.note}</p>}
        </Card>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ sales
const GROUPS = [
  ["day", "Day"],
  ["week", "Week"],
  ["month", "Month"],
  ["category", "Category"],
  ["product", "Product"],
  ["customer", "Customer"],
  ["payment_method", "Payment method"],
  ["staff", "Staff member"],
] as const;

function SalesReport({ range }: { range: Range }) {
  const [group, setGroup] = useState<(typeof GROUPS)[number][0]>("day");
  const q = useReport<{ series?: TrendRow[]; totals?: Row; rows?: Row[]; period?: "day" | "week" | "month" }>("/reports/sales", { ...range, group_by: group });
  const isPeriod = group === "day" || group === "week" || group === "month";
  const cols: Col[] = useMemo(() => {
    switch (group) {
      case "category":
        return [
          { key: "category", label: "Category" },
          { key: "units_sold", label: "Units", num: true },
          { key: "returned_units", label: "Returned", num: true },
          { key: "gross_sales", label: "Gross", money: true },
          { key: "returns", label: "Returns", money: true },
          { key: "net_sales", label: "Net", money: true },
        ];
      case "product":
        return [
          { key: "product_name", label: "Product" },
          { key: "sku", label: "SKU" },
          { key: "net_units", label: "Net units", num: true },
          { key: "invoice_count", label: "Invoices", num: true },
          { key: "taxable_value", label: "Taxable", money: true },
          { key: "net_sales", label: "Net sales", money: true },
        ];
      case "customer":
        return [
          { key: "customer_name", label: "Customer" },
          { key: "invoice_count", label: "Invoices", num: true },
          { key: "gross_sales", label: "Gross", money: true },
          { key: "credit_sales", label: "On credit", money: true },
          { key: "returns", label: "Returns", money: true },
          { key: "net_sales", label: "Net", money: true },
        ];
      case "payment_method":
        return [
          { key: "method", label: "Method", render: (r) => METHOD_LABEL[r.method as PaymentMethod] ?? String(r.method) },
          { key: "transactions", label: "Transactions", num: true },
          { key: "receipts", label: "Received", money: true },
          { key: "refunds", label: "Refunded", money: true },
          { key: "net", label: "Net", money: true },
        ];
      case "staff":
        return [
          { key: "name", label: "Staff member" },
          { key: "invoice_count", label: "Invoices", num: true },
          { key: "gross_sales", label: "Sales", money: true },
        ];
      default:
        return [
          { key: "period_start", label: "Period", render: (r) => formatDate(String(r.period_start)) },
          { key: "invoice_count", label: "Invoices", num: true },
          { key: "units_sold", label: "Units", num: true },
          { key: "gross_sales", label: "Gross", money: true },
          { key: "returns", label: "Returns", money: true },
          { key: "tax", label: "GST", money: true },
          { key: "net_sales", label: "Net", money: true },
        ];
    }
  }, [group]);

  return (
    <>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm text-ink-2">Group by</span>
        <Select value={group} onChange={(e) => setGroup(e.target.value as typeof group)} className="w-auto" aria-label="Group by">
          {GROUPS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </Select>
      </div>
      <Loading q={q} />
      {q.data && isPeriod && q.data.series && q.data.totals && (
        <>
          <Stats
            items={[
              { label: "Net sales", value: formatINR(String(q.data.totals.net_sales)) },
              { label: "Gross sales", value: formatINR(String(q.data.totals.gross_sales)), note: `returns ${formatINR(String(q.data.totals.returns))}` },
              { label: "Invoices", value: String(q.data.totals.invoice_count) },
              { label: "Units sold", value: String(q.data.totals.units_sold) },
            ]}
          />
          <Card className="mb-4 p-3">
            <SalesTrendChart rows={q.data.series} period={q.data.period ?? "day"} />
          </Card>
          <DataTable title="Sales by period" subtitle="Includes days with no sales" rows={q.data.series as unknown as Row[]} cols={cols} filename={`sales-${group}`} />
        </>
      )}
      {q.data && !isPeriod && q.data.rows && <DataTable title={`Sales by ${group.replace("_", " ")}`} rows={q.data.rows} cols={cols} filename={`sales-${group}`} />}
    </>
  );
}

function TopReport({ range }: { range: Range }) {
  const [metric, setMetric] = useState("revenue");
  const q = useReport<{ rows: Row[] }>("/reports/top-products", { ...range, metric, limit: 20 });
  const fmt = (v: string | number) => (metric === "revenue" ? formatINR(String(v)) : String(v));
  return (
    <>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm text-ink-2">Rank by</span>
        <Select value={metric} onChange={(e) => setMetric(e.target.value)} className="w-auto" aria-label="Metric">
          <option value="revenue">Net revenue</option>
          <option value="quantity">Units sold</option>
          <option value="invoice_count">Invoice count</option>
        </Select>
      </div>
      <Loading q={q} />
      {q.data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Card className="p-3">
            {q.data.rows.length ? (
              <RankedBarChart rows={q.data.rows.slice(0, 10).map((r) => ({ label: String(r.product_name), value: r.metric_value as string, detail: `rank ${r.rank}` }))} valueLabel={metric} format={fmt} />
            ) : (
              <p className="py-8 text-center text-sm text-ink-3">No sales in this period.</p>
            )}
          </Card>
          <DataTable
            title="Ranking"
            subtitle="Tied values share a rank"
            filename={`top-products-${metric}`}
            rows={q.data.rows}
            cols={[
              { key: "rank", label: "#", num: true },
              { key: "product_name", label: "Product" },
              { key: "net_sales", label: "Net revenue", money: true },
              { key: "net_units", label: "Units", num: true },
              { key: "invoice_count", label: "Invoices", num: true },
            ]}
          />
        </div>
      )}
    </>
  );
}

function PaymentsReport({ range }: { range: Range }) {
  const q = useReport<{ by_method: Row[]; daily: Row[]; total_received: string }>("/reports/payments", range);
  return (
    <>
      <Loading q={q} />
      {q.data && (
        <>
          <Stats items={[{ label: "Net received", value: formatINR(q.data.total_received), note: "receipts minus refunds" }]} />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <DataTable
              title="By method"
              filename="payments-by-method"
              rows={q.data.by_method}
              cols={[
                { key: "method", label: "Method", render: (r) => METHOD_LABEL[r.method as PaymentMethod] },
                { key: "transactions", label: "Count", num: true },
                { key: "receipts", label: "Received", money: true },
                { key: "refunds", label: "Refunded", money: true },
                { key: "net", label: "Net", money: true },
              ]}
            />
            <DataTable
              title="Daily collections"
              filename="payments-daily"
              rows={q.data.daily}
              cols={[
                { key: "date", label: "Date", render: (r) => formatDate(String(r.date)) },
                { key: "net_received", label: "Net received", money: true },
              ]}
            />
          </div>
        </>
      )}
    </>
  );
}

function InvoicesReport({ range }: { range: Range }) {
  const q = useReport<{ rows: Row[]; totals: Row }>("/reports/invoices", range);
  return (
    <>
      <Loading q={q} />
      {q.data && (
        <>
          <Stats
            items={[
              { label: "Invoices", value: String(q.data.totals.count) },
              { label: "Billed", value: formatINR(String(q.data.totals.grand_total)) },
              { label: "Still unpaid", value: formatINR(String(q.data.totals.balance_due)) },
              { label: "Credited", value: formatINR(String(q.data.totals.credited)) },
            ]}
          />
          <DataTable
            title="By status"
            filename="invoices"
            rows={q.data.rows}
            cols={[
              { key: "status", label: "Status" },
              { key: "payment_status", label: "Payment" },
              { key: "count", label: "Count", num: true },
              { key: "grand_total", label: "Billed", money: true },
              { key: "credited", label: "Credited", money: true },
              { key: "balance_due", label: "Unpaid", money: true },
            ]}
          />
        </>
      )}
    </>
  );
}

function KhataReport() {
  const q = useReport<{ rows: Row[]; total_outstanding: string; total_overdue: string; as_of: string }>("/reports/khata");
  return (
    <>
      <Loading q={q} />
      {q.data && (
        <>
          <Stats
            items={[
              { label: "Outstanding", value: formatINR(q.data.total_outstanding), note: `as of ${formatDate(q.data.as_of)}` },
              { label: "Overdue", value: formatINR(q.data.total_overdue) },
              { label: "Customers", value: String(q.data.rows.length) },
            ]}
          />
          <DataTable
            title="Ageing by due date"
            filename="khata-ageing"
            rows={q.data.rows}
            cols={[
              { key: "name", label: "Customer" },
              { key: "balance", label: "Balance", money: true },
              { key: "current", label: "Not due", money: true },
              { key: "1_30", label: "1–30 days", money: true },
              { key: "31_60", label: "31–60", money: true },
              { key: "61_90", label: "61–90", money: true },
              { key: "90_plus", label: "90+", money: true },
            ]}
          />
        </>
      )}
    </>
  );
}

function InventoryReport({ range }: { range: Range }) {
  const val = useReport<{ rows: Row[]; total_value_at_cost: string; total_value_at_sale_price: string; products_missing_cost: number; note: string }>(
    "/reports/inventory-valuation",
  );
  const low = useReport<{ rows: Row[] }>("/reports/low-stock");
  const out = useReport<{ rows: Row[] }>("/reports/out-of-stock");
  const mov = useReport<{ by_type: Row[]; by_product: Row[] }>("/reports/stock-movements", range);
  const alertCols: Col[] = [
    { key: "name", label: "Product" },
    { key: "sku", label: "SKU" },
    { key: "quantity", label: "In stock", num: true },
    { key: "low_stock_threshold", label: "Alert at", num: true },
    { key: "incoming_quantity", label: "On order", num: true },
    { key: "reorder_quantity", label: "Reorder qty", num: true },
  ];
  return (
    <div className="flex flex-col gap-4">
      <Loading q={val} />
      {val.data && (
        <>
          <Stats
            items={[
              { label: "Stock value at cost", value: formatINR(val.data.total_value_at_cost), note: val.data.products_missing_cost ? `${val.data.products_missing_cost} products have no cost price` : undefined },
              { label: "Stock value at sale price", value: formatINR(val.data.total_value_at_sale_price) },
              { label: "Low stock", value: String(low.data?.rows.length ?? "…") },
              { label: "Out of stock", value: String(out.data?.rows.length ?? "…") },
            ]}
          />
          <DataTable
            title="Valuation"
            subtitle={val.data.note}
            filename="inventory-valuation"
            rows={val.data.rows}
            cols={[
              { key: "name", label: "Product" },
              { key: "sku", label: "SKU" },
              { key: "quantity", label: "Qty", num: true },
              { key: "cost_price", label: "Cost", money: true },
              { key: "value_at_cost", label: "Value at cost", money: true },
              { key: "value_at_sale_price", label: "Value at price", money: true },
            ]}
          />
        </>
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {low.data && <DataTable title="Low stock" filename="low-stock" rows={low.data.rows} cols={alertCols} />}
        {out.data && <DataTable title="Out of stock" filename="out-of-stock" rows={out.data.rows} cols={alertCols} />}
      </div>
      {mov.data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <DataTable
            title="Movements by type"
            filename="movements-by-type"
            rows={mov.data.by_type}
            cols={[
              { key: "movement_type", label: "Type", render: (r) => MOVEMENT_LABEL[r.movement_type as MovementType] },
              { key: "movements", label: "Entries", num: true },
              { key: "net_quantity", label: "Net qty", num: true },
            ]}
          />
          <DataTable
            title="Movements by product"
            filename="movements-by-product"
            rows={mov.data.by_product}
            cols={[
              { key: "name", label: "Product" },
              { key: "quantity_in", label: "In", num: true },
              { key: "quantity_out", label: "Out", num: true },
              { key: "net_change", label: "Net", num: true },
            ]}
          />
        </div>
      )}
    </div>
  );
}

function POReport({ range }: { range: Range }) {
  const q = useReport<{
    by_status: Row[];
    ordered_value_excluding_cancelled: string;
    received_value: string;
    received_units: number;
    received_by_supplier: Row[];
    pending_orders: number;
    pending_value: string;
    note: string;
  }>("/reports/purchase-orders", range);
  return (
    <>
      <Loading q={q} />
      {q.data && (
        <>
          <Stats
            items={[
              { label: "Received (purchases)", value: formatINR(q.data.received_value), note: `${q.data.received_units} units` },
              { label: "Ordered", value: formatINR(q.data.ordered_value_excluding_cancelled), note: "excluding cancelled" },
              { label: "Pending orders", value: String(q.data.pending_orders) },
              { label: "Pending value", value: formatINR(q.data.pending_value) },
            ]}
          />
          <p className="mb-3 text-xs text-ink-3">{q.data.note}</p>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <DataTable
              title="Orders by status"
              subtitle="By order date"
              filename="po-status"
              rows={q.data.by_status}
              cols={[
                { key: "status", label: "Status" },
                { key: "count", label: "Orders", num: true },
                { key: "total", label: "Value (incl. GST)", money: true },
              ]}
            />
            <DataTable
              title="Received by supplier"
              filename="po-suppliers"
              rows={q.data.received_by_supplier}
              cols={[
                { key: "name", label: "Supplier" },
                { key: "received_value", label: "Received", money: true },
              ]}
            />
          </div>
        </>
      )}
    </>
  );
}

function GSTReport({ range }: { range: Range }) {
  const q = useReport<{ outward_supplies: Row[]; credit_notes: Row[]; net: Row; net_by_rate: Row[]; source: string }>("/reports/gst", range);
  const cols: Col[] = [
    { key: "gst_rate", label: "Rate %", num: true },
    { key: "supply_type", label: "Supply", render: (r) => (r.supply_type === "intra_state" ? "Intra-state" : "Inter-state") },
    { key: "category", label: "Type" },
    { key: "taxable_value", label: "Taxable", money: true },
    { key: "cgst", label: "CGST", money: true },
    { key: "sgst", label: "SGST", money: true },
    { key: "igst", label: "IGST", money: true },
  ];
  return (
    <>
      <Loading q={q} />
      {q.data && (
        <div className="flex flex-col gap-4">
          <Stats
            items={[
              { label: "Net taxable value", value: formatINR(String(q.data.net.taxable_value)) },
              { label: "CGST", value: formatINR(String(q.data.net.cgst)) },
              { label: "SGST", value: formatINR(String(q.data.net.sgst)) },
              { label: "IGST", value: formatINR(String(q.data.net.igst)) },
            ]}
          />
          <p className="text-xs text-ink-3">Computed from {q.data.source}. Credit notes are subtracted in the period they were issued.</p>
          <DataTable title="Net by rate" filename="gst-net-by-rate" rows={q.data.net_by_rate} cols={cols.filter((c) => !["supply_type", "category"].includes(c.key))} />
          <DataTable title="Outward supplies" filename="gst-outward" rows={q.data.outward_supplies} cols={cols} />
          <DataTable title="Credit notes" filename="gst-credit-notes" rows={q.data.credit_notes} cols={cols} />
        </div>
      )}
    </>
  );
}

function ProfitReport({ range }: { range: Range }) {
  const q = useReport<Row>("/reports/profit", range);
  return (
    <>
      <Loading q={q} />
      {q.data && (
        <>
          <Stats
            items={[
              { label: "Revenue (ex-GST, cost known)", value: formatINR(String(q.data.revenue_with_known_cost)) },
              { label: "Cost of goods sold", value: formatINR(String(q.data.cogs)) },
              { label: "Gross profit", value: formatINR(String(q.data.gross_profit)), note: q.data.margin_percent ? `${q.data.margin_percent}% margin` : undefined },
              {
                label: "Excluded: no cost price",
                value: formatINR(String(q.data.revenue_without_cost)),
                note: `${q.data.lines_without_cost} of ${q.data.total_lines} invoice lines`,
              },
            ]}
          />
          <p className="text-xs text-ink-3">{String(q.data.note)}</p>
        </>
      )}
    </>
  );
}
