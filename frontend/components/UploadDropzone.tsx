"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type DragEvent } from "react";

import { api, errorMessage, MAX_UPLOAD_BYTES } from "@/lib/api";

const ACCEPT =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; fileName: string }
  | { kind: "error"; message: string };

function validate(file: File): string | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".doc")) return "Old .doc files aren't supported. Save it as PDF or DOCX.";
  if (!name.endsWith(".pdf") && !name.endsWith(".docx")) return "Upload a PDF or DOCX file.";
  if (file.size > MAX_UPLOAD_BYTES) return "The file is larger than 5 MB.";
  if (file.size === 0) return "The file is empty.";
  return null;
}

export function UploadDropzone() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const busy = state.kind === "uploading";

  async function handleFile(file: File | undefined) {
    if (!file || busy) return;
    const problem = validate(file);
    if (problem) {
      setState({ kind: "error", message: problem });
      return;
    }
    setState({ kind: "uploading", fileName: file.name });
    try {
      const resume = await api.uploadResume(file);
      router.push(`/resume/${resume.id}`);
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    } finally {
      if (inputRef.current) inputRef.current.value = ""; // allow re-selecting the same file
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    void handleFile(event.dataTransfer.files[0]);
  }

  return (
    <div className="space-y-3">
      <label
        htmlFor="resume-file"
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-busy={busy}
        className={[
          "flex min-h-48 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-600",
          dragging
            ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40"
            : "border-zinc-300 bg-white hover:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-500",
          busy ? "cursor-wait opacity-80" : "",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          id="resume-file"
          type="file"
          accept={ACCEPT}
          disabled={busy}
          className="sr-only"
          onChange={(event) => void handleFile(event.target.files?.[0])}
        />
        {busy ? (
          <>
            <span
              aria-hidden
              className="size-6 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-600"
            />
            <p className="font-medium">Reading {state.fileName}…</p>
            <p className="text-sm text-zinc-500">This usually takes 5–15 seconds.</p>
          </>
        ) : (
          <>
            <p className="font-medium">
              Drop your resume here, or <span className="text-emerald-700 underline dark:text-emerald-400">choose a file</span>
            </p>
            <p className="text-sm text-zinc-500">PDF or DOCX, up to 5 MB</p>
          </>
        )}
      </label>
      {state.kind === "error" && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
          {state.message}
        </p>
      )}
      <p className="text-xs text-zinc-500">
        Your email address and phone number are removed before anything is stored or sent to the
        AI model, and the resume is deleted automatically after 24 hours.
      </p>
    </div>
  );
}
