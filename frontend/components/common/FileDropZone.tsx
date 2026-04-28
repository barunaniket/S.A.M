"use client";

import { useCallback, useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/utils";

type FileDropZoneProps = {
  onFile: (file: File) => void;
  accept?: string;
  hint?: string;
  disabled?: boolean;
};

/**
 * Generic drag-and-drop file picker. Used by timetable / task / academic
 * calendar upload screens. Single-file at a time.
 */
export function FileDropZone({
  onFile,
  accept = "image/*,audio/*,application/pdf,.docx,.xlsx,.xls,.txt,.md",
  hint = "Drop a file here or click to browse",
  disabled = false,
}: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [hover, setHover] = useState(false);

  const handle = useCallback(
    (file: File | null | undefined) => {
      if (!file || disabled) return;
      onFile(file);
    },
    [onFile, disabled],
  );

  return (
    <div
      onDragOver={(e) => {
        if (disabled) return;
        e.preventDefault();
        setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setHover(false);
        handle(e.dataTransfer.files?.[0]);
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3",
        "rounded-lg border-2 border-dashed p-8 text-center transition-colors",
        hover ? "border-primary bg-primary/5" : "border-border bg-muted/20",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <UploadCloud className="size-8 text-muted-foreground" />
      <p className="text-sm font-medium">{hint}</p>
      <p className="text-xs text-muted-foreground">
        Photos, voice notes, PDFs, Word, Excel and plain text are all OK.
      </p>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept={accept}
        disabled={disabled}
        onChange={(e) => handle(e.target.files?.[0])}
      />
    </div>
  );
}
