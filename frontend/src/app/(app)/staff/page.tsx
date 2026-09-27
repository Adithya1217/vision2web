"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorBanner, Field, Input, Modal, PageHeader, Pagination, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { useSubmitter } from "@/lib/hooks";
import type { Page, Role, User } from "@/lib/types";

const ROLE_HELP: Record<Role, string> = {
  owner: "Everything, including staff, shop settings, GST and profit reports",
  manager: "Products, stock, sales, customers, suppliers, purchase orders and reports",
  staff: "Billing, payments, customer lookup and stock operations",
};

export default function StaffPage() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const list = useQuery({ queryKey: ["users", page], queryFn: () => api.get<Page<User>>("/users", { page, page_size: 25 }) });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.patch<User>(`/users/${id}`, body),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast(`Updated ${u.full_name}`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Failed", "error"),
  });
  return (
    <>
      <PageHeader
        title="Staff"
        subtitle="Everyone signs in with their own account. Actions are recorded against the person who did them."
        actions={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" /> Add person
          </Button>
        }
      />
      <Card>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Role</Th>
                  <Th className="hidden md:table-cell">Last sign-in</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {list.data?.items.map((u) => (
                  <tr key={u.id}>
                    <Td>
                      <p className="font-medium">{u.full_name}</p>
                      <p className="text-xs text-ink-3">{u.email}</p>
                    </Td>
                    <Td>
                      <Select
                        value={u.role}
                        disabled={u.id === me?.user.id}
                        onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value } })}
                        className="h-8 w-auto"
                        aria-label={`Role of ${u.full_name}`}
                      >
                        <option value="owner">Owner</option>
                        <option value="manager">Manager</option>
                        <option value="staff">Staff</option>
                      </Select>
                    </Td>
                    <Td className="hidden text-ink-2 md:table-cell">{formatDateTime(u.last_login_at, me?.shop.timezone)}</Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        {u.is_active ? <Badge tone="good">Active</Badge> : <Badge>Disabled</Badge>}
                        {u.id !== me?.user.id && (
                          <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                            {u.is_active ? "Disable" : "Enable"}
                          </Button>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </Card>
      {adding && <AddUserModal onClose={() => setAdding(false)} />}
    </>
  );
}

function AddUserModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [f, setF] = useState({ full_name: "", email: "", password: "", role: "staff" as Role });
  const save = useMutation({
    mutationFn: () => api.post<User>("/users", f, submitter.keyFor(f)),
    onSuccess: (u) => {
      submitter.done();
      qc.invalidateQueries({ queryKey: ["users"] });
      toast(`Added ${u.full_name}`);
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Add person"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!f.full_name || !f.email || f.password.length < 8}>
            Add
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <div className="flex flex-col gap-3">
        <Field label="Full name">{(id) => <Input id={id} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />}</Field>
        <Field label="Email">{(id) => <Input id={id} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />}</Field>
        <Field label="Temporary password" hint="At least 8 characters">
          {(id) => <Input id={id} type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />}
        </Field>
        <Field label="Role" hint={ROLE_HELP[f.role]}>
          {(id) => (
            <Select id={id} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
              <option value="staff">Staff</option>
              <option value="manager">Manager</option>
              <option value="owner">Owner</option>
            </Select>
          )}
        </Field>
      </div>
    </Modal>
  );
}
