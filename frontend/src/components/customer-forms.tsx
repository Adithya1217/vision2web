"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useState } from "react";

import { Button, ErrorBanner, Field, Input, Modal, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STATES } from "@/lib/format";
import { useDebounced, useSubmitter } from "@/lib/hooks";
import { formatINR, isMoney } from "@/lib/money";
import type { Customer, Page } from "@/lib/types";

export function CustomerPicker({ value, onChange }: { value: Customer | null; onChange: (c: Customer | null) => void }) {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const search = useDebounced(q, 200);
  const results = useQuery({
    queryKey: ["customers", "picker", search],
    queryFn: () => api.get<Page<Customer>>("/customers", { q: search, page_size: 8 }),
    enabled: open,
  });
  if (value)
    return (
      <div className="flex flex-col gap-1">
        <span className="text-[13px] font-semibold leading-4 text-ink">Customer</span>
        <div className="flex h-9 items-center justify-between rounded-sm border-2 border-line-strong bg-butter-soft px-3 text-sm">
          <span className="truncate">
            {value.name} {value.phone && <span className="text-ink-3">· {value.phone}</span>}
          </span>
          <button className="text-xs text-info hover:underline" onClick={() => onChange(null)}>
            Change
          </button>
        </div>
        {value.balance !== "0.00" && <span className="text-xs text-ink-3">Khata balance {formatINR(value.balance)}</span>}
      </div>
    );
  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-[13px] font-semibold leading-4 text-ink">Customer</span>
      <div className="flex gap-1">
        <Input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Walk-in (search name or phone)"
          aria-label="Customer"
        />
        {can("customers.write") && (
          <Button variant="secondary" onClick={() => setAdding(true)} aria-label="Add customer">
            <UserPlus className="h-4 w-4" />
          </Button>
        )}
      </div>
      {open && (
        <ul className="absolute top-full z-20 mt-1 max-h-64 w-full overflow-auto rounded-sm border-2 border-line-strong bg-surface shadow-md">
          {results.data?.items.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="flex w-full justify-between px-3 py-2 text-left text-sm hover:bg-lavender-soft"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(c);
                  setQ("");
                  setOpen(false);
                }}
              >
                <span>{c.name}</span>
                <span className="text-xs text-ink-3">{c.phone}</span>
              </button>
            </li>
          ))}
          {results.data?.items.length === 0 && <li className="px-3 py-2 text-sm text-ink-3">No customers found</li>}
        </ul>
      )}
      <CustomerFormModal
        open={adding}
        onClose={() => setAdding(false)}
        onSaved={(c) => {
          onChange(c);
          setAdding(false);
        }}
      />
    </div>
  );
}

export function CustomerFormModal({
  open,
  onClose,
  onSaved,
  customer,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (c: Customer) => void;
  customer?: Customer;
}) {
  const submitter = useSubmitter();
  const qc = useQueryClient();
  const [f, setF] = useState({
    name: customer?.name ?? "",
    phone: customer?.phone ?? "",
    email: customer?.email ?? "",
    gstin: customer?.gstin ?? "",
    state_code: customer?.state_code ?? "",
    address: customer?.address ?? "",
    credit_limit: customer?.credit_limit ?? "",
  });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = {
      name: f.name,
      phone: f.phone || null,
      email: f.email || null,
      gstin: f.gstin ? f.gstin.toUpperCase() : null,
      state_code: f.state_code || null,
      address: f.address || null,
      credit_limit: f.credit_limit || null,
    };
    try {
      const key = submitter.keyFor(body);
      const c = customer
        ? await api.patch<Customer>(`/customers/${customer.id}`, body, key)
        : await api.post<Customer>("/customers", body, key);
      submitter.done();
      qc.invalidateQueries({ queryKey: ["customers"] });
      onSaved(c);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={customer ? `Edit ${customer.name}` : "Add customer"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} loading={busy} disabled={!f.name || (!!f.credit_limit && !isMoney(f.credit_limit))}>
            Save
          </Button>
        </>
      }
    >
      <ErrorBanner error={error} className="mb-3" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Name">{(id) => <Input id={id} value={f.name} onChange={set("name")} />}</Field>
        <Field label="Phone">{(id) => <Input id={id} value={f.phone} onChange={set("phone")} inputMode="tel" />}</Field>
        <Field label="GSTIN (B2B)">{(id) => <Input id={id} value={f.gstin} onChange={set("gstin")} maxLength={15} />}</Field>
        <Field label="State">
          {(id) => (
            <Select id={id} value={f.state_code} onChange={set("state_code")}>
              <option value="">Same as shop</option>
              {STATES.map(([c, n]) => (
                <option key={c} value={c}>
                  {c} · {n}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Credit limit (₹)" hint="Blank = no limit">
          {(id) => <Input id={id} value={f.credit_limit} onChange={set("credit_limit")} inputMode="decimal" />}
        </Field>
        <Field label="Email">{(id) => <Input id={id} value={f.email} onChange={set("email")} type="email" />}</Field>
        <Field label="Address" className="sm:col-span-2">
          {(id) => <Input id={id} value={f.address} onChange={set("address")} />}
        </Field>
      </div>
    </Modal>
  );
}
