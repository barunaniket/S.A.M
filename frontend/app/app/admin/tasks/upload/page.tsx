"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { FileDropZone } from "@/components/common/FileDropZone";
import { Card } from "@/components/ui/card";
import { getToken } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type UploadResponse = {
  success: boolean;
  pending_id: number;
  tasks: unknown[];
  needs_review: boolean;
};

async function uploadTasksFile(file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/tasks/bulk-upload`, {
    method: "POST",
    body: fd,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  const body = await res.json();
  if (!res.ok || !body?.success) {
    throw new Error(body?.detail ?? body?.message ?? "Upload failed");
  }
  return body;
}

function UploadInner() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onFile = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const res = await uploadTasksFile(file);
      router.push(`/app/admin/tasks/${res.pending_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Upload task assignments</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Drop a spreadsheet, PDF, Word doc, image of a printed sheet, or voice
          memo. S.A.M. will extract the assignments and let you review before
          notifying anyone.
        </p>
      </header>
      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </Card>
      )}
      <FileDropZone onFile={onFile} disabled={busy} hint="Drop the task list here" />
      {busy && (
        <p className="text-sm text-muted-foreground">
          Parsing… (LLM extraction may take a few seconds.)
        </p>
      )}
    </div>
  );
}

export default function TasksUploadPage() {
  return (
    <RoleGuard allow={["ADMIN"]}>
      <UploadInner />
    </RoleGuard>
  );
}
