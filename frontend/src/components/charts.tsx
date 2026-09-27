"use client";

import { Table2, LineChart as LineIcon } from "lucide-react";
import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Table, Td, Th } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { formatINR } from "@/lib/money";

// Chart values are converted to numbers for plotting geometry only. Every figure shown as text is
// formatted from the original decimal string.
const plot = (v: string | number) => (typeof v === "number" ? v : Number(v));

const axisTick = { fill: "var(--ink-3)", fontSize: 11 };

function ChartTooltip({
  active,
  payload,
  label,
  render,
}: {
  active?: boolean;
  payload?: { payload: Record<string, unknown> }[];
  label?: string;
  render: (row: Record<string, unknown>, label?: string) => React.ReactNode;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">{render(payload[0].payload, label)}</div>
  );
}

export interface TrendRow {
  period_start: string;
  period_end: string;
  net_sales: string;
  invoice_count: number;
  units_sold: number;
  returns: string;
}

export function SalesTrendChart({ rows, period }: { rows: TrendRow[]; period: "day" | "week" | "month" }) {
  const [asTable, setAsTable] = useState(false);
  const data = rows.map((r) => ({ ...r, value: plot(r.net_sales) }));
  const tickLabel = (d: string) => {
    const [, m, day] = d.split("-");
    const month = new Date(Date.UTC(2000, Number(m) - 1, 1)).toLocaleString("en-IN", { month: "short", timeZone: "UTC" });
    return period === "month" ? month : `${Number(day)} ${month}`;
  };
  return (
    <div>
      <div className="mb-1 flex justify-end">
        <button
          onClick={() => setAsTable((t) => !t)}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-ink-3 hover:bg-surface-2 hover:text-ink"
          aria-pressed={asTable}
        >
          {asTable ? <LineIcon className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
          {asTable ? "Chart" : "Table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-64 overflow-auto">
          <Table>
            <thead>
              <tr>
                <Th>Period</Th>
                <Th className="text-right">Invoices</Th>
                <Th className="text-right">Units</Th>
                <Th className="text-right">Returns</Th>
                <Th className="text-right">Net sales</Th>
              </tr>
            </thead>
            <tbody className="tabular">
              {rows.map((r) => (
                <tr key={r.period_start}>
                  <Td>{formatDate(r.period_start)}</Td>
                  <Td className="text-right">{r.invoice_count}</Td>
                  <Td className="text-right">{r.units_sold}</Td>
                  <Td className="text-right">{formatINR(r.returns)}</Td>
                  <Td className="text-right">{formatINR(r.net_sales)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : (
        <div className="h-64" role="img" aria-label="Net sales trend">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="salesFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.18} />
                  <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis
                dataKey="period_start"
                tickFormatter={tickLabel}
                tick={axisTick}
                tickLine={false}
                axisLine={{ stroke: "var(--axis)" }}
                minTickGap={24}
              />
              <YAxis
                tick={axisTick}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={(v: number) => formatINR(String(Math.round(v)), { compact: true }).replace(".00", "")}
              />
              <Tooltip
                cursor={{ stroke: "var(--ink-3)", strokeWidth: 1 }}
                content={
                  <ChartTooltip
                    render={(row) => (
                      <>
                        <p className="mb-1 font-medium">
                          {formatDate(String(row.period_start))}
                          {row.period_end !== row.period_start && ` – ${formatDate(String(row.period_end))}`}
                        </p>
                        <p className="tabular">Net sales {formatINR(String(row.net_sales))}</p>
                        <p className="tabular text-ink-2">
                          {String(row.invoice_count)} invoices · {String(row.units_sold)} units
                        </p>
                        {row.returns !== "0.00" && <p className="tabular text-ink-2">Returns {formatINR(String(row.returns))}</p>}
                      </>
                    )}
                  />
                }
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--series-1)"
                strokeWidth={2}
                fill="url(#salesFill)"
                activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2, fill: "var(--series-1)" }}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export function RankedBarChart({
  rows,
  valueLabel,
  format,
}: {
  rows: { label: string; value: string | number; detail?: string }[];
  valueLabel: string;
  format: (v: string | number) => string;
}) {
  const data = rows.map((r) => ({ ...r, plotValue: plot(r.value) }));
  const height = Math.max(120, data.length * 36);
  return (
    <div style={{ height }} role="img" aria-label={`${valueLabel} by product`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 84, left: 0, bottom: 0 }} barCategoryGap={8}>
          <XAxis type="number" hide domain={[0, "dataMax"]} />
          <YAxis
            type="category"
            dataKey="label"
            width={130}
            tick={{ fill: "var(--ink-2)", fontSize: 12 }}
            tickLine={false}
            axisLine={{ stroke: "var(--axis)" }}
            tickFormatter={(s: string) => (s.length > 18 ? s.slice(0, 17) + "…" : s)}
          />
          <Tooltip
            cursor={{ fill: "var(--surface-2)" }}
            content={
              <ChartTooltip
                render={(row) => (
                  <>
                    <p className="mb-1 font-medium">{String(row.label)}</p>
                    <p className="tabular">
                      {valueLabel}: {format(row.value as string | number)}
                    </p>
                    {row.detail ? <p className="text-ink-2">{String(row.detail)}</p> : null}
                  </>
                )}
              />
            }
          />
          <Bar
            dataKey="plotValue"
            fill="var(--series-1)"
            radius={[0, 4, 4, 0]}
            maxBarSize={20}
            isAnimationActive={false}
          >
            <LabelList dataKey="value" position="right" fill="var(--ink-2)" fontSize={11} formatter={(v: unknown) => format(v as string | number)} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
