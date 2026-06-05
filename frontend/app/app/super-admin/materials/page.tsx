"use client";

import { useState } from "react";
import useSWR from "swr";
import { FileText, Sparkles, Upload as UploadIcon } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";

type Material = {
  id: number;
  subject: string;
  batch?: string | null;
  title: string;
  file_path?: string | null;
  mime_type?: string | null;
  uploaded_by_name?: string | null;
  created_at?: string | null;
};

type BankRow = {
  id: number;
  question: string;
  choices: string[];
  correct_index: number;
  approved_at?: string | null;
};

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

function MaterialsInner() {
  const [subject, setSubject] = useState("");
  const [batch, setBatch] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewSubject, setPreviewSubject] = useState<string | null>(null);

  const { data: list, mutate: refreshList } = useSWR<Material[]>(
    "/api/v1/materials",
    (path: string) => apiFetch<Material[]>(path),
  );

  const { data: bank, mutate: refreshBank } = useSWR<BankRow[]>(
    previewSubject
      ? `/api/v1/materials/bank?subject=${encodeURIComponent(previewSubject)}`
      : null,
    (path: string) => apiFetch<BankRow[]>(path),
  );

  const onUpload = async () => {
    if (!file || !subject.trim()) {
      setError("Subject and file are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("subject", subject);
      if (batch) fd.append("batch", batch);
      if (title) fd.append("title", title);
      fd.append("file", file);
      const token = (typeof window !== "undefined" && localStorage.getItem("sam_jwt")) || "";
      const res = await fetch(`${API}/api/v1/materials`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: fd,
      });
      const body = await res.json();
      if (!res.ok || body?.success === false) {
        throw new Error(body?.detail || body?.message || "Upload failed");
      }
      setFile(null);
      setTitle("");
      refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const onGenerate = async (m: Material) => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/materials/${m.id}/generate-mcqs`, {
        method: "POST",
        body: JSON.stringify({ count: 5 }),
      });
      setPreviewSubject(m.subject);
      refreshBank();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  };

  const onApproveAll = async () => {
    if (!bank || bank.length === 0) return;
    const ids = bank.filter((b) => !b.approved_at).map((b) => b.id);
    if (ids.length === 0) return;
    await apiFetch(`/api/v1/materials/bank/approve`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    refreshBank();
  };

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Course materials</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          PDFs and slides used to generate attendance MCQs. Upload, then click
          <em> Generate </em> to draft 5 questions per material.
        </p>
      </header>

      <Card className="space-y-3 p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground">Subject *</label>
            <Input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="CS201"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Batch</label>
            <Input
              value={batch}
              onChange={(e) => setBatch(e.target.value)}
              placeholder="(any)"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Title</label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="defaults to filename"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">File *</label>
            <input
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              accept=".pdf,.docx,.txt,.md,.pptx"
              className="block w-full text-sm"
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={onUpload} disabled={busy}>
            <UploadIcon className="size-4" />
            {busy ? "Uploading…" : "Upload"}
          </Button>
          {error && <span className="text-sm text-destructive">{error}</span>}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-border bg-muted/40 px-4 py-3 text-sm font-semibold">
          Library ({list?.length ?? 0})
        </div>
        {list && list.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">
            No materials yet — upload one above.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {(list ?? []).map((m) => (
              <li key={m.id} className="flex items-center gap-3 p-3">
                <FileText className="size-4 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{m.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {m.subject}
                    {m.batch ? ` · ${m.batch}` : ""} · uploaded by {m.uploaded_by_name ?? "—"}
                  </div>
                </div>
                <Button size="sm" variant="outline" onClick={() => onGenerate(m)} disabled={busy}>
                  <Sparkles className="size-4" />
                  Generate MCQs
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {previewSubject && bank && (
        <Card className="space-y-3 overflow-hidden">
          <div className="flex items-center justify-between border-b border-border bg-muted/40 px-4 py-3">
            <div className="text-sm font-semibold">
              {previewSubject} — bank ({bank.length})
            </div>
            <Button size="sm" onClick={onApproveAll}>
              Approve all
            </Button>
          </div>
          <ol className="space-y-3 px-4 pb-4 text-sm">
            {bank.map((q, i) => (
              <li key={q.id} className="rounded border border-border p-3">
                <div className="font-medium">
                  Q{i + 1}. {q.question}
                  {q.approved_at && (
                    <span className="ml-2 text-xs text-emerald-600">approved</span>
                  )}
                </div>
                <ul className="mt-2 space-y-0.5">
                  {q.choices.map((c, j) => (
                    <li
                      key={j}
                      className={
                        j === q.correct_index
                          ? "font-medium text-emerald-700"
                          : "text-muted-foreground"
                      }
                    >
                      {String.fromCharCode(65 + j)}. {c}
                      {j === q.correct_index ? " ✓" : ""}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}

export default function MaterialsPage() {
  return (
    <RoleGuard allow={["SUPER_ADMIN", "FACULTY", "ADMIN"]}>
      <MaterialsInner />
    </RoleGuard>
  );
}
