"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, ErrorBanner, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STATES } from "@/lib/format";
import { useSubmitter } from "@/lib/hooks";
import type { Shop } from "@/lib/types";

const ZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Asia/Kathmandu", "Asia/Dhaka", "Europe/London", "America/New_York"];

export default function SettingsPage() {
  const { me } = useAuth();
  const shop = me!.shop;
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [f, setF] = useState({
    name: shop.name,
    legal_name: shop.legal_name ?? "",
    gstin: shop.gstin ?? "",
    state_code: shop.state_code,
    address: shop.address ?? "",
    phone: shop.phone ?? "",
    timezone: shop.timezone,
    invoice_prefix: shop.invoice_prefix,
    credit_note_prefix: shop.credit_note_prefix,
    po_prefix: shop.po_prefix,
    default_credit_days: String(shop.default_credit_days),
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f,
        legal_name: f.legal_name || null,
        gstin: f.gstin ? f.gstin.toUpperCase() : null,
        address: f.address || null,
        phone: f.phone || null,
        default_credit_days: Number(f.default_credit_days || 0),
      };
      return api.patch<Shop>("/shop", body, submitter.keyFor(body));
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries({ queryKey: ["me"] });
      toast("Shop settings saved");
    },
  });
  return (
    <>
      <PageHeader title="Shop settings" subtitle="Changes apply to new documents; posted invoices keep their snapshots." />
      <Card className="max-w-3xl">
        <CardHeader title="Business details" />
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
          <Field label="Shop name">{(id) => <Input id={id} value={f.name} onChange={set("name")} />}</Field>
          <Field label="Legal name (on invoices)">{(id) => <Input id={id} value={f.legal_name} onChange={set("legal_name")} />}</Field>
          <Field label="GSTIN">{(id) => <Input id={id} value={f.gstin} onChange={set("gstin")} maxLength={15} />}</Field>
          <Field label="State (decides CGST/SGST vs IGST)">
            {(id) => (
              <Select id={id} value={f.state_code} onChange={set("state_code")}>
                {STATES.map(([c, n]) => (
                  <option key={c} value={c}>
                    {c} · {n}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Address" className="sm:col-span-2">{(id) => <Input id={id} value={f.address} onChange={set("address")} />}</Field>
          <Field label="Phone">{(id) => <Input id={id} value={f.phone} onChange={set("phone")} />}</Field>
          <Field label="Timezone" hint="Used for invoice dates and every report">
            {(id) => (
              <Select id={id} value={f.timezone} onChange={set("timezone")}>
                {Array.from(new Set([f.timezone, ...ZONES])).map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Invoice prefix">{(id) => <Input id={id} value={f.invoice_prefix} onChange={set("invoice_prefix")} />}</Field>
          <Field label="Credit note prefix">{(id) => <Input id={id} value={f.credit_note_prefix} onChange={set("credit_note_prefix")} />}</Field>
          <Field label="Purchase order prefix">{(id) => <Input id={id} value={f.po_prefix} onChange={set("po_prefix")} />}</Field>
          <Field label="Default credit period (days)">
            {(id) => <Input id={id} type="number" min={0} max={365} value={f.default_credit_days} onChange={set("default_credit_days")} />}
          </Field>
        </div>
        <div className="flex items-center justify-end gap-3 border-t border-line px-4 py-3">
          <ErrorBanner error={save.error} className="flex-1" />
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            Save settings
          </Button>
        </div>
      </Card>
    </>
  );
}
