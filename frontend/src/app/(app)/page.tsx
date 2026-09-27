"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CircleSlash, FileText, IndianRupee, Package, ShoppingCart, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { RankedBarChart, SalesTrendChart } from "@/components/charts";
import { Card, CardHeader, EmptyState, ErrorBanner, PageHeader, Segmented, Spinner, Sprite } from "@/components/ui";
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
          <section aria-label="Today" className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4 lg:gap-6">
            <Tile icon={IndianRupee} surface="butter" label="Today's revenue" value={formatINR(s.today.revenue)} note={s.today.returns !== "0.00" ? `after ${formatINR(s.today.returns)} returns` : "net of returns"} href="/invoices" />
            <Tile icon={FileText} label="Invoices today" value={String(s.today.invoice_count)} note={`${s.today.units_sold} units sold`} href="/invoices" />
            <Tile icon={Wallet} surface="lavender" label="Khata outstanding" value={formatINR(s.khata.outstanding)} note={`${s.khata.customers_with_balance} customers`} href="/customers?filter=balance" />
            <Tile
              icon={IndianRupee}
              label="Unpaid invoices"
              value={formatINR(s.invoices.unpaid_total)}
              note={s.invoices.overdue_count ? `${formatINR(s.invoices.overdue_total)} overdue (${s.invoices.overdue_count})` : `${s.invoices.unpaid_count} open`}
              tone={s.invoices.overdue_count ? "critical" : undefined}
              href="/invoices"
            />
          </section>
          <section aria-label="Stock and purchasing" className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4 lg:gap-6">
            <Tile icon={AlertTriangle} label="Low stock" value={String(s.stock.low_stock)} note="products at or below alert level" tone={s.stock.low_stock ? "warning" : undefined} href="/products?stock=low" />
            <Tile icon={CircleSlash} label="Out of stock" value={String(s.stock.out_of_stock)} note={`of ${s.stock.active_products} active products`} tone={s.stock.out_of_stock ? "critical" : undefined} href="/products?stock=out" />
            <Tile icon={ShoppingCart} surface="sky" label="Pending purchase orders" value={String(s.purchase_orders.pending_count)} note={`${formatINR(s.purchase_orders.pending_value)} on order`} href="/purchase-orders" />
            <Tile icon={Package} label="Active products" value={String(s.stock.active_products)} href="/products" />
          </section>
        </>
      )}
      <div className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-5">
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
          <div className="p-4 sm:p-6">
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
          <div className="p-4 sm:p-6">
            <ErrorBanner error={top.error} />
            {top.data ? (
              top.data.rows.length ? (
                <RankedBarChart
                  rows={top.data.rows.map((r) => ({ label: r.product_name, value: r.metric_value, detail: `#${r.rank} · ${r.sku}` }))}
                  valueLabel={metric === "revenue" ? "Net revenue" : metric === "quantity" ? "Units sold" : "Invoices"}
                  format={metricFormat}
                />
              ) : (
                <EmptyState title="No sales in the last 30 days" hint="Record an invoice and the leaderboard fills up." />
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

// Full class names so Tailwind can see them at build time.
const SURFACE = { butter: "bg-butter", sky: "bg-sky", lavender: "bg-lavender" } as const;

function Tile({
  icon: Icon,
  label,
  value,
  note,
  tone,
  surface,
  href,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  note?: string;
  tone?: "warning" | "critical";
  surface?: "butter" | "sky" | "lavender";
  href?: string;
}) {
  // Stockpile: pink = warning (paired with the alert sprite / word), otherwise the tile's own pastel.
  const pastel = tone ? "bg-pink" : surface ? SURFACE[surface] : "";
  const body = (
    <div className={`h-full border-[3px] border-line-strong p-4 shadow-md ${pastel ? `${pastel} text-on-pastel` : "bg-surface"} ${href ? "px-press" : ""}`}>
      <div className="flex items-center gap-1.5 font-mono text-xs font-semibold uppercase tracking-[0.04em]">
        {tone === "warning" ? <Sprite name="alert" size={12} className="animate-pulse" /> : <Icon className="h-3.5 w-3.5" />}
        {label}
      </div>
      <p className="mt-3 truncate font-pixel text-xs leading-7 sm:text-base xl:text-lg">{value}</p>
      {note && <p className="mt-1 font-mono text-xs opacity-80">{note}</p>}
    </div>
  );
  return href ? (
    <Link href={href} className="block h-full">
      {body}
    </Link>
  ) : (
    body
  );
}

