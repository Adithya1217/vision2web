"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Modal, PageHeader, Pagination, SearchInput, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STATES } from "@/lib/format";
import { useDebounced, useSubmitter } from "@/lib/hooks";
import type { Page, Supplier } from "@/lib/types";

export default function SuppliersPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("active");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Supplier | null | undefined>(undefined);
  const search = useDebounced(q);
  const params = { q: search, status, page, page_size: 25 };
  const list = useQuery({ queryKey: ["suppliers", params], queryFn: () => api.get<Page<Supplier>>("/suppliers", params) });
  return (
    <>
      <PageHeader
        title="Suppliers"
        actions={
          can("suppliers.write") && (
            <Button variant="primary" onClick={() => setEditing(null)}>
              <Plus className="h-4 w-4" /> Add supplier
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Name, phone or GSTIN" />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-auto" aria-label="Status">
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="all">All</option>
          </Select>
        </div>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.items.length ? (
          <EmptyState title="No suppliers" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Supplier</Th>
                  <Th className="hidden sm:table-cell">Contact</Th>
                  <Th className="hidden md:table-cell">GSTIN</Th>
                  <Th>Status</Th>
                  <Th>
                    <span className="sr-only">Actions</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((s) => (
                  <tr key={s.id}>
                    <Td className="font-medium">{s.name}</Td>
                    <Td className="hidden text-ink-2 sm:table-cell">{[s.contact_person, s.phone].filter(Boolean).join(" · ") || "—"}</Td>
                    <Td className="hidden text-ink-2 md:table-cell">{s.gstin ?? "—"}</Td>
                    <Td>{s.is_active ? <Badge tone="good">Active</Badge> : <Badge>Inactive</Badge>}</Td>
                    <Td className="text-right">
                      {can("suppliers.write") && (
                        <Button size="sm" variant="ghost" onClick={() => setEditing(s)} aria-label={`Edit ${s.name}`}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      {editing !== undefined && <SupplierModal supplier={editing} onClose={() => setEditing(undefined)} />}
    </>
  );
}

function SupplierModal({ supplier, onClose }: { supplier: Supplier | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [f, setF] = useState({
    name: supplier?.name ?? "",
    contact_person: supplier?.contact_person ?? "",
    phone: supplier?.phone ?? "",
    email: supplier?.email ?? "",
    gstin: supplier?.gstin ?? "",
    state_code: supplier?.state_code ?? "",
    address: supplier?.address ?? "",
    is_active: supplier?.is_active ?? true,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        name: f.name,
        contact_person: f.contact_person || null,
        phone: f.phone || null,
        email: f.email || null,
        gstin: f.gstin ? f.gstin.toUpperCase() : null,
        state_code: f.state_code || null,
        address: f.address || null,
      };
      if (supplier) body.is_active = f.is_active;
      const key = submitter.keyFor(body);
      return supplier ? api.patch(`/suppliers/${supplier.id}`, body, key) : api.post("/suppliers", body, key);
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries({ queryKey: ["suppliers"] });
      toast("Supplier saved");
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={supplier ? `Edit ${supplier.name}` : "Add supplier"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} disabled={!f.name} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Name">{(id) => <Input id={id} value={f.name} onChange={set("name")} />}</Field>
        <Field label="Contact person">{(id) => <Input id={id} value={f.contact_person} onChange={set("contact_person")} />}</Field>
        <Field label="Phone">{(id) => <Input id={id} value={f.phone} onChange={set("phone")} />}</Field>
        <Field label="Email">{(id) => <Input id={id} value={f.email} onChange={set("email")} />}</Field>
        <Field label="GSTIN">{(id) => <Input id={id} value={f.gstin} onChange={set("gstin")} maxLength={15} />}</Field>
        <Field label="State">
          {(id) => (
            <Select id={id} value={f.state_code} onChange={set("state_code")}>
              <option value="">—</option>
              {STATES.map(([c, n]) => (
                <option key={c} value={c}>
                  {c} · {n}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Address" className="sm:col-span-2">
          {(id) => <Input id={id} value={f.address} onChange={set("address")} />}
        </Field>
        {supplier && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.is_active} onChange={(e) => setF((x) => ({ ...x, is_active: e.target.checked }))} className="accent-[var(--accent)]" />
            Active
          </label>
        )}
      </div>
    </Modal>
  );
}
