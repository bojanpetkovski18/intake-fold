import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type SubmitEvent } from "react";
import { uploadDocuments } from "../api/client";
import type { UploadedFile } from "../api/types";
import { BusyButton, ErrorNotice } from "../components/feedback";

const ACCEPTED = "application/pdf,image/png,image/jpeg";

function outcome(file: UploadedFile): string {
  if (file.code) return file.detail ?? "This file was refused.";
  return file.deduplicated ? "Already uploaded." : "Queued.";
}

export function UploadPanel() {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<File[]>([]);
  const [progress, setProgress] = useState<number | null>(null);
  const [results, setResults] = useState<UploadedFile[]>([]);
  const [failure, setFailure] = useState<unknown>(null);
  const uploading = progress !== null;

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected.length === 0) {
      input.current?.focus();
      return;
    }
    setFailure(null);
    setResults([]);
    setProgress(0);
    try {
      const result = await uploadDocuments(selected, setProgress);
      setResults(result.files);
      setSelected([]);
      if (input.current) input.current.value = "";
      await client.invalidateQueries({ queryKey: ["documents"] });
    } catch (error) {
      setFailure(error);
    } finally {
      setProgress(null);
    }
  }

  const refused = results.filter((file) => file.code).length;
  return (
    <section className="panel" aria-labelledby="upload-heading">
      <h2 id="upload-heading">Upload</h2>
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label htmlFor="files">Invoices and receipts (PDF, PNG or JPEG)</label>
        <input
          id="files"
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED}
          onChange={(event) => {
            setSelected(Array.from(event.target.files ?? []));
          }}
        />
        <BusyButton type="submit" className="primary" busy={uploading} busyLabel="Uploading">
          Upload
        </BusyButton>
      </form>
      {uploading && (
        <progress value={progress} max={1} aria-label="Upload progress">
          {Math.round(progress * 100)}%
        </progress>
      )}
      {failure !== null && <ErrorNotice error={failure} />}
      {results.length > 0 && (
        <>
          <p role="status">
            {results.length - refused} of {results.length} accepted.
          </p>
          <ul className="file-results">
            {results.map((file, index) => (
              <li key={`${file.filename}-${String(index)}`} className={file.code ? "refused" : ""}>
                <span className="filename">{file.filename}</span>: {outcome(file)}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
