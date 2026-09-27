"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CircleSlash, FileText, IndianRupee, Package, ShoppingCart, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { RankedBarChart, SalesTrendChart } from "@/components/charts";
import { Card, CardHeader, ErrorBanner, PageHeader, Segmented, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { formatINR } from "@/lib/money";
import type { DashboardSummary, SalesSeries, TopProductRow } from "@/lib/types";

type Period = "daily" | "weekly" | "monthly";
type Metric = "revenue" | "quantity" | "invoice_count";

export default function DashboardPage() {
  const { can } = useAuth();
  const router = useRouter();
  const allowed = can("dashboard.view");
  useEffect(() => {
    if (!allowed) router.replace("/invoices/new");
  }, [allowed, router]);

  const [period, setPeriod] = useState<Period>("daily");
  const [metric, setMetric] = useState<Metric>("revenue");
  const summary = useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: () => api.get<DashboardSummary>("/dashboard/summary"),
    enabled: allowed,
  });
  const trend = useQuery({
    queryKey: ["dashboard", "trend", period],
    queryFn: () => api.get<SalesSeries>("/dashboard/trend", { period }),
    enabled: allowed,
  });
  const top = useQuery({
    queryKey: ["dashboard", "top", metric],
    queryFn: () => api.get<{ rows: TopProductRow[] }>("/dashboard/top-products", { metric, days: 30, limit: 7 }),
    enabled: allowed,
  });

  if (!allowed) return null;
  if (summary.isLoading) return <Spinner />;
  const s = summary.data;

  const metricFormat = (v: string | number) => (metric === "revenue" ? formatINR(String(v)) : String(v));

  return (
    <>
      <PageHeader title="Dashboard" subtitle={s ? `Today, ${formatDate(s.date)} · ${s.timezone}` : undefined} />
      <ErrorBanner error={summary.error} className="mb-4" />
      {s && (
        <>
          <section aria-label="Today" className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile icon={IndianRupee} label="Today's revenue" value={formatINR(s.today.revenue)} note={s.today.returns !== "0.00" ? `after ${formatINR(s.today.returns)} returns` : "net of returns"} href="/invoices" />
            <Tile icon={FileText} label="Invoices today" value={String(s.today.invoice_count)} note={`${s.today.units_sold} units sold`} href="/invoices" />
            <Tile icon={Wallet} label="Khata outstanding" value={formatINR(s.khata.outstanding)} note={`${s.khata.customers_with_balance} customers`} href="/customers?filter=balance" />
            <Tile
              icon={IndianRupee}
              label="Unpaid invoices"
              value={formatINR(s.invoices.unpaid_total)}
              note={s.invoices.overdue_count ? `${formatINR(s.invoices.overdue_total)} overdue (${s.invoices.overdue_count})` : `${s.invoices.unpaid_count} open`}
              tone={s.invoices.overdue_count ? "critical" : undefined}
              href="/invoices"
            />
          </section>
          <section aria-label="Stock and purchasing" className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile icon={AlertTriangle} label="Low stock" value={String(s.stock.low_stock)} note="products at or below alert level" tone={s.stock.low_stock ? "warning" : undefined} href="/products?stock=low" />
            <Tile icon={CircleSlash} label="Out of stock" value={String(s.stock.out_of_stock)} note={`of ${s.stock.active_products} active products`} tone={s.stock.out_of_stock ? "critical" : undefined} href="/products?stock=out" />
            <Tile icon={ShoppingCart} label="Pending purchase orders" value={String(s.purchase_orders.pending_count)} note={`${formatINR(s.purchase_orders.pending_value)} on order`} href="/purchase-orders" />
            <Tile icon={Package} label="Active products" value={String(s.stock.active_products)} href="/products" />
          </section>
        </>
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader
            title="Net sales"
            subtitle={trend.data ? `${formatDate(trend.data.start_date)} – ${formatDate(trend.data.end_date)} · ${formatINR(trend.data.totals.net_sales)}` : undefined}
            actions={
              <Segmented
                label="Trend period"
                value={period}
                onChange={setPeriod}
                options={[
                  { value: "daily", label: "30 days" },
                  { value: "weekly", label: "12 weeks" },
                  { value: "monthly", label: "12 months" },
                ]}
              />
            }
          />
          <div className="p-3">
            <ErrorBanner error={trend.error} />
            {trend.data ? <SalesTrendChart rows={trend.data.series} period={trend.data.period} /> : <Spinner />}
          </div>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader
            title="Top products"
            subtitle="Last 30 days"
            actions={
              <Segmented
                label="Rank by"
                value={metric}
                onChange={setMetric}
                options={[
                  { value: "revenue", label: "Revenue" },
                  { value: "quantity", label: "Units" },
                  { value: "invoice_count", label: "Invoices" },
                ]}
              />
            }
          />
          <div className="p-3">
            <ErrorBanner error={top.error} />
            {top.data ? (
              top.data.rows.length ? (
                <RankedBarChart
                  rows={top.data.rows.map((r) => ({ label: r.product_name, value: r.metric_value, detail: `#${r.rank} · ${r.sku}` }))}
                  valueLabel={metric === "revenue" ? "Net revenue" : metric === "quantity" ? "Units sold" : "Invoices"}
                  format={metricFormat}
                />
              ) : (
                <p className="py-10 text-center text-sm text-ink-3">No sales in the last 30 days.</p>
              )
            ) : (
              <Spinner />
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  note,
  tone,
  href,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  note?: string;
  tone?: "warning" | "critical";
  href?: string;
}) {
  const body = (
    <Card className="h-full p-4 transition-colors hover:border-line-strong">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        <Icon
          className={`h-3.5 w-3.5 ${tone === "critical" ? "text-critical-ink" : tone === "warning" ? "text-warning-ink" : "text-ink-3"}`}
        />
        {label}
      </div>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight">{value}</p>
      {note && <p className={`mt-0.5 text-xs ${tone === "critical" ? "text-critical-ink" : "text-ink-3"}`}>{note}</p>}
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}
