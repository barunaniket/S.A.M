"use client";

import useSWR from "swr";
import { useEffect, useMemo, useState } from "react";
import { CalendarRange, Pencil, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Role =
  | "SUPER_ADMIN"
  | "ADMIN"
  | "FACULTY"
  | "BOOKING_AUTHORITY"
  | "STUDENT";

type User = {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  department: string | null;
  phone_number: string | null;
  office_location: string | null;
  batch: string | null;
  is_onboarded: boolean;
  created_at: string | null;
};

type TimetableEntry = {
  day_of_week: number;
  start_time: string;
  end_time: string;
  subject?: string | null;
  room?: string | null;
  batch?: string | null;
};

type FormState = {
  email: string;
  full_name: string;
  role: Role;
  phone_number: string;
  department: string;
  office_location: string;
  batch: string;
  group_names: string;
};

const TEACHER_ROLES: Role[] = ["FACULTY", "ADMIN", "BOOKING_AUTHORITY"];
const STUDENT_ROLES: Role[] = ["STUDENT"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const blankForm: FormState = {
  email: "",
  full_name: "",
  role: "FACULTY",
  phone_number: "",
  department: "",
  office_location: "",
  batch: "",
  group_names: "",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MembersPage() {
  const { data, error, mutate } = useSWR<{ users: User[] }>(
    "/api/v1/admin/users",
    (path: string) => apiFetch(path),
  );
  const allUsers = data?.users ?? [];

  const [tab, setTab] = useState<"all" | "teachers" | "students">("all");
  const [search, setSearch] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [timetableOf, setTimetableOf] = useState<User | null>(null);
  const [topError, setTopError] = useState<string | null>(null);

  const visible = useMemo(() => {
    let rows = allUsers;
    if (tab === "teachers") {
      rows = rows.filter((u) => TEACHER_ROLES.includes(u.role) || u.role === "SUPER_ADMIN");
    } else if (tab === "students") {
      rows = rows.filter((u) => STUDENT_ROLES.includes(u.role));
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((u) =>
        u.full_name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.department ?? "").toLowerCase().includes(q) ||
        (u.batch ?? "").toLowerCase().includes(q) ||
        (u.office_location ?? "").toLowerCase().includes(q),
      );
    }
    return rows;
  }, [allUsers, tab, search]);

  const onDelete = async (u: User) => {
    if (!confirm(`Delete ${u.full_name} (${u.email})? This is irreversible.`)) return;
    try {
      await apiFetch(`/api/v1/admin/users/${u.id}`, { method: "DELETE" });
      mutate();
    } catch (e) {
      setTopError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Members</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage every teacher and student. Required field for teachers is
            the staff room; for students it&apos;s their batch.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="size-4" /> Add member
          </Button>
        </div>
      </header>

      {(topError || error) && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {topError ?? (error as Error)?.message}
        </Card>
      )}

      {/* Tabs + search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-md bg-muted p-1 text-xs">
          {(["all", "teachers", "students"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={
                "rounded px-3 py-1 transition-colors " +
                (tab === t
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              {t === "all" ? `All (${allUsers.length})` :
               t === "teachers" ? `Teachers (${allUsers.filter(u => TEACHER_ROLES.includes(u.role) || u.role === "SUPER_ADMIN").length})` :
               `Students (${allUsers.filter(u => u.role === "STUDENT").length})`}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, email, dept, batch, room…"
          className="ml-auto w-72 rounded-md border bg-background px-3 py-1.5 text-sm"
        />
      </div>

      {/* Table */}
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="p-2 text-left">Name</th>
              <th className="p-2 text-left">Email</th>
              <th className="p-2 text-left">Role</th>
              <th className="p-2 text-left">Department</th>
              <th className="p-2 text-left">Phone</th>
              <th className="p-2 text-left">Staff room</th>
              <th className="p-2 text-left">Batch</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-8 text-center text-muted-foreground">
                  No members yet — click <b>Add member</b> to start.
                </td>
              </tr>
            ) : (
              visible.map((u) => (
                <tr key={u.id} className="border-t border-border align-top">
                  <td className="p-2 font-medium">{u.full_name}</td>
                  <td className="p-2 text-xs text-muted-foreground">{u.email}</td>
                  <td className="p-2"><RoleBadge role={u.role} /></td>
                  <td className="p-2 text-xs">{u.department ?? "—"}</td>
                  <td className="p-2 text-xs">{u.phone_number ?? "—"}</td>
                  <td className="p-2 text-xs">{u.office_location ?? "—"}</td>
                  <td className="p-2 text-xs">{u.batch ?? "—"}</td>
                  <td className="p-2 text-right">
                    <div className="flex justify-end gap-1">
                      {(TEACHER_ROLES.includes(u.role) || u.role === "SUPER_ADMIN") && (
                        <button
                          title="Edit timetable"
                          onClick={() => setTimetableOf(u)}
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          <CalendarRange className="size-4" />
                        </button>
                      )}
                      <button
                        title="Edit"
                        onClick={() => {
                          setEditing(u);
                          setFormOpen(true);
                        }}
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <Pencil className="size-4" />
                      </button>
                      <button
                        title="Delete"
                        onClick={() => onDelete(u)}
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {formOpen && (
        <FormModal
          existing={editing}
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
          }}
          onSaved={() => {
            setFormOpen(false);
            setEditing(null);
            mutate();
          }}
        />
      )}

      {timetableOf && (
        <TimetableModal
          user={timetableOf}
          onClose={() => setTimetableOf(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function RoleBadge({ role }: { role: Role }) {
  const cls: Record<Role, string> = {
    SUPER_ADMIN:       "bg-purple-500/15 text-purple-700 dark:text-purple-300",
    ADMIN:             "bg-amber-500/15 text-amber-700 dark:text-amber-300",
    FACULTY:           "bg-sky-500/15 text-sky-700 dark:text-sky-300",
    BOOKING_AUTHORITY: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    STUDENT:           "bg-muted text-muted-foreground",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-[10px] font-medium uppercase ${cls[role]}`}>
      {role}
    </span>
  );
}

function FormModal({
  existing,
  onClose,
  onSaved,
}: {
  existing: User | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<FormState>(() =>
    existing
      ? {
          email: existing.email,
          full_name: existing.full_name,
          role: existing.role,
          phone_number: existing.phone_number ?? "",
          department: existing.department ?? "",
          office_location: existing.office_location ?? "",
          batch: existing.batch ?? "",
          group_names: "",
        }
      : { ...blankForm },
  );
  const [timetable, setTimetable] = useState<TimetableEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const isStudent = form.role === "STUDENT";
  const isTeacher = !isStudent;

  const set = <K extends keyof FormState>(key: K, v: FormState[K]) =>
    setForm((p) => ({ ...p, [key]: v }));

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (existing) {
        await apiFetch(`/api/v1/admin/users/${existing.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            full_name: form.full_name || null,
            role: form.role,
            phone_number: form.phone_number || null,
            department: form.department || null,
            office_location: form.office_location || null,
            batch: form.batch || null,
          }),
        });
      } else {
        const groups = form.group_names
          .split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
        await apiFetch("/api/v1/admin/users", {
          method: "POST",
          body: JSON.stringify({
            email: form.email.trim(),
            full_name: form.full_name.trim(),
            role: form.role,
            phone_number: form.phone_number || null,
            department: form.department || null,
            office_location: isTeacher ? form.office_location || null : null,
            batch: isStudent ? form.batch || null : null,
            timetable: timetable.length ? timetable : null,
            group_names: groups.length ? groups : null,
          }),
        });
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={existing ? `Edit ${existing.full_name}` : "Add member"} onClose={onClose}>
      <div className="space-y-4">
        {/* Role tabs */}
        <div className="flex gap-1 rounded-md bg-muted p-1 text-xs">
          {(["FACULTY", "ADMIN", "BOOKING_AUTHORITY", "STUDENT"] as Role[]).map((r) => (
            <button
              key={r}
              onClick={() => set("role", r)}
              className={
                "flex-1 rounded px-2 py-1 transition-colors " +
                (form.role === r
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              {r === "BOOKING_AUTHORITY" ? "Booking" : r}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Full name" required>
            <input
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              className="rounded border bg-background px-2 py-1.5 text-sm w-full"
            />
          </Field>
          <Field label="Email" required>
            <input
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              disabled={!!existing}
              className="rounded border bg-background px-2 py-1.5 text-sm w-full disabled:opacity-60"
            />
          </Field>
          <Field label="Phone">
            <input
              value={form.phone_number}
              onChange={(e) => set("phone_number", e.target.value)}
              placeholder="+91…"
              className="rounded border bg-background px-2 py-1.5 text-sm w-full"
            />
          </Field>
          <Field label="Department">
            <input
              value={form.department}
              onChange={(e) => set("department", e.target.value)}
              placeholder="CSE / ECE / …"
              className="rounded border bg-background px-2 py-1.5 text-sm w-full"
            />
          </Field>

          {isTeacher && (
            <Field label="Staff room" hint="Where they sit between classes">
              <input
                value={form.office_location}
                onChange={(e) => set("office_location", e.target.value)}
                placeholder="Faculty Block, Room 312"
                className="rounded border bg-background px-2 py-1.5 text-sm w-full"
              />
            </Field>
          )}
          {isStudent && (
            <Field label="Batch / class" hint="Used for class cancellation broadcasts">
              <input
                value={form.batch}
                onChange={(e) => set("batch", e.target.value)}
                placeholder="CSE-3A"
                className="rounded border bg-background px-2 py-1.5 text-sm w-full"
              />
            </Field>
          )}
        </div>

        {!existing && (
          <Field label="Add to groups (optional)" hint="Comma-separated names — created on the fly">
            <input
              value={form.group_names}
              onChange={(e) => set("group_names", e.target.value)}
              placeholder="CSE-3A, AI Club"
              className="rounded border bg-background px-2 py-1.5 text-sm w-full"
            />
          </Field>
        )}

        {/* Timetable inline (teachers, create-mode only) */}
        {!existing && isTeacher && (
          <div>
            <div className="mb-1 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Timetable (optional)
              </p>
              <button
                onClick={() =>
                  setTimetable((p) => [
                    ...p,
                    { day_of_week: 0, start_time: "09:00", end_time: "10:00" },
                  ])
                }
                className="text-xs text-primary hover:underline"
              >
                + Add row
              </button>
            </div>
            {timetable.length > 0 && (
              <div className="overflow-hidden rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="p-1.5 text-left">Day</th>
                      <th className="p-1.5 text-left">Start</th>
                      <th className="p-1.5 text-left">End</th>
                      <th className="p-1.5 text-left">Subject</th>
                      <th className="p-1.5 text-left">Room</th>
                      <th className="p-1.5 text-left">Batch</th>
                      <th className="p-1.5"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {timetable.map((t, i) => (
                      <tr key={i} className="border-t border-border">
                        <td className="p-1">
                          <select
                            value={t.day_of_week}
                            onChange={(e) =>
                              setTimetable((p) =>
                                p.map((x, j) =>
                                  j === i
                                    ? { ...x, day_of_week: Number(e.target.value) }
                                    : x,
                                ),
                              )
                            }
                            className="rounded border bg-background px-1 py-0.5"
                          >
                            {DAYS.map((d, idx) => (
                              <option key={d} value={idx}>{d}</option>
                            ))}
                          </select>
                        </td>
                        <td className="p-1">
                          <input
                            type="time"
                            value={t.start_time}
                            onChange={(e) =>
                              setTimetable((p) =>
                                p.map((x, j) =>
                                  j === i ? { ...x, start_time: e.target.value } : x,
                                ),
                              )
                            }
                            className="rounded border bg-background px-1 py-0.5"
                          />
                        </td>
                        <td className="p-1">
                          <input
                            type="time"
                            value={t.end_time}
                            onChange={(e) =>
                              setTimetable((p) =>
                                p.map((x, j) =>
                                  j === i ? { ...x, end_time: e.target.value } : x,
                                ),
                              )
                            }
                            className="rounded border bg-background px-1 py-0.5"
                          />
                        </td>
                        <td className="p-1">
                          <input
                            value={t.subject ?? ""}
                            onChange={(e) =>
                              setTimetable((p) =>
                                p.map((x, j) =>
                                  j === i ? { ...x, subject: e.target.value } : x,
                                ),
                              )
                            }
                            className="rounded border bg-background px-1 py-0.5 w-full"
                          />
                        </td>
                        <td className="p-1">
                          <input
                            value={t.room ?? ""}
                            onChange={(e) =>
                              setTimetable((p) =>
                                p.map((x, j) =>
                                  j === i ? { ...x, room: e.target.value } : x,
                                ),
                              )
                            }
                            className="rounded border bg-background px-1 py-0.5 w-full"
                          />
                        </td>
                        <td className="p-1">
                          <input
                            value={t.batch ?? ""}
                            onChange={(e) =>
                              setTimetable((p) =>
                                p.map((x, j) =>
                                  j === i ? { ...x, batch: e.target.value } : x,
                                ),
                              )
                            }
                            className="rounded border bg-background px-1 py-0.5 w-full"
                          />
                        </td>
                        <td className="p-1 text-right">
                          <button
                            onClick={() =>
                              setTimetable((p) => p.filter((_, j) => j !== i))
                            }
                            className="text-xs text-destructive hover:underline"
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {timetable.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Skip for now and use the calendar icon on the row to set the
                timetable later.
              </p>
            )}
          </div>
        )}

        {err && (
          <p className="text-sm text-destructive">{err}</p>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !form.full_name || !form.email}>
            {busy ? "Saving…" : existing ? "Save changes" : "Create member"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function TimetableModal({ user, onClose }: { user: User; onClose: () => void }) {
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ entries: TimetableEntry[] }>(`/api/v1/admin/users/${user.id}/timetable`)
      .then((d) => {
        // Server returns time as "HH:MM:SS" — trim to "HH:MM" for the input.
        setEntries(
          (d.entries ?? []).map((e) => ({
            ...e,
            start_time: (e.start_time ?? "").slice(0, 5),
            end_time: (e.end_time ?? "").slice(0, 5),
          })),
        );
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setLoaded(true));
  }, [user.id]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await apiFetch(`/api/v1/admin/users/${user.id}/timetable`, {
        method: "POST",
        body: JSON.stringify({ entries }),
      });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Timetable — ${user.full_name}`} onClose={onClose}>
      {!loaded ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {entries.length} entry{entries.length === 1 ? "" : " entries"}.
              Saving replaces the existing timetable.
            </p>
            <button
              onClick={() =>
                setEntries((p) => [
                  ...p,
                  { day_of_week: 0, start_time: "09:00", end_time: "10:00" },
                ])
              }
              className="text-xs text-primary hover:underline"
            >
              + Add row
            </button>
          </div>

          {entries.length > 0 && (
            <div className="overflow-hidden rounded-md border max-h-[55vh] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-muted/80 backdrop-blur text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="p-1.5 text-left">Day</th>
                    <th className="p-1.5 text-left">Start</th>
                    <th className="p-1.5 text-left">End</th>
                    <th className="p-1.5 text-left">Subject</th>
                    <th className="p-1.5 text-left">Room</th>
                    <th className="p-1.5 text-left">Batch</th>
                    <th className="p-1.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((t, i) => (
                    <tr key={i} className="border-t border-border">
                      <td className="p-1">
                        <select
                          value={t.day_of_week}
                          onChange={(e) =>
                            setEntries((p) =>
                              p.map((x, j) =>
                                j === i ? { ...x, day_of_week: Number(e.target.value) } : x,
                              ),
                            )
                          }
                          className="rounded border bg-background px-1 py-0.5"
                        >
                          {DAYS.map((d, idx) => <option key={d} value={idx}>{d}</option>)}
                        </select>
                      </td>
                      <td className="p-1">
                        <input
                          type="time"
                          value={t.start_time}
                          onChange={(e) =>
                            setEntries((p) =>
                              p.map((x, j) =>
                                j === i ? { ...x, start_time: e.target.value } : x,
                              ),
                            )
                          }
                          className="rounded border bg-background px-1 py-0.5"
                        />
                      </td>
                      <td className="p-1">
                        <input
                          type="time"
                          value={t.end_time}
                          onChange={(e) =>
                            setEntries((p) =>
                              p.map((x, j) =>
                                j === i ? { ...x, end_time: e.target.value } : x,
                              ),
                            )
                          }
                          className="rounded border bg-background px-1 py-0.5"
                        />
                      </td>
                      <td className="p-1">
                        <input
                          value={t.subject ?? ""}
                          onChange={(e) =>
                            setEntries((p) =>
                              p.map((x, j) =>
                                j === i ? { ...x, subject: e.target.value } : x,
                              ),
                            )
                          }
                          className="rounded border bg-background px-1 py-0.5 w-full"
                        />
                      </td>
                      <td className="p-1">
                        <input
                          value={t.room ?? ""}
                          onChange={(e) =>
                            setEntries((p) =>
                              p.map((x, j) =>
                                j === i ? { ...x, room: e.target.value } : x,
                              ),
                            )
                          }
                          className="rounded border bg-background px-1 py-0.5 w-full"
                        />
                      </td>
                      <td className="p-1">
                        <input
                          value={t.batch ?? ""}
                          onChange={(e) =>
                            setEntries((p) =>
                              p.map((x, j) =>
                                j === i ? { ...x, batch: e.target.value } : x,
                              ),
                            )
                          }
                          className="rounded border bg-background px-1 py-0.5 w-full"
                        />
                      </td>
                      <td className="p-1 text-right">
                        <button
                          onClick={() =>
                            setEntries((p) => p.filter((_, j) => j !== i))
                          }
                          className="text-xs text-destructive hover:underline"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {entries.length === 0 && (
            <p className="text-sm text-muted-foreground">No entries yet — click <b>+ Add row</b>.</p>
          )}

          {err && <p className="text-sm text-destructive">{err}</p>}

          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button onClick={save} disabled={busy}>
              {busy ? "Saving…" : `Save ${entries.length} entry${entries.length === 1 ? "" : " entries"}`}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">
        {label}
        {required && <span className="text-destructive"> *</span>}
      </span>
      {children}
      {hint && <span className="text-[10px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  // Lock body scroll while open
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4">
      <div className="w-full max-w-3xl rounded-lg border border-border bg-card shadow-lg">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="max-h-[80vh] overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}
