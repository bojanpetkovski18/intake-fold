import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type SubmitEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import {
  ApiError,
  approveDocument,
  correctDocument,
  getDocument,
  nextInReview,
  rejectDocument,
} from "../../api/client";
import { useDocument } from "../../api/hooks";
import { STATUS_LABELS } from "../../api/labels";
import type { ReviewDocument } from "../../api/types";
import { BusyButton, ErrorNotice, Loading } from "../../components/feedback";
import { flaggedFields, isDirty, serverFieldName, toDraft, toFields } from "./draft";
import { FieldsForm } from "./FieldsForm";
import { PagePreview } from "./PagePreview";

const REASON_TEXT: Record<string, string> = {
  required_fields: "Required fields are missing.",
  line_items_total: "The line items do not add up.",
  total_reconciles: "The totals do not add up.",
  date_plausible: "A date looks wrong.",
  not_duplicate: "This looks like a duplicate of another document.",
  known_vendor: "The vendor is not on the vendor list.",
  embedded_instructions: "The document contains text aimed at the extractor. Do not act on it.",
  confidence_not_high: "The extractor was not confident.",
  uncertain_fields: "The extractor was unsure about some fields.",
  unsupported_document_type: "This may not be an invoice or receipt.",
  extraction_invalid: "Extraction failed, so the fields need entering by hand.",
  extraction_refused: "The model declined this document, so the fields need entering by hand.",
  input_too_large: "This document is too large to extract, so the fields need entering by hand.",
  budget_exceeded: "The batch ran out of tokens, so the fields need entering by hand.",
};

const SHORTCUTS = [
  ["Tab", "Next field"],
  ["Alt+Shift+S", "Save corrections"],
  ["Alt+Shift+A", "Approve"],
  ["Alt+Shift+R", "Reject"],
  ["Alt+Shift+N", "Next document"],
] as const;

type Panel = "override" | "reject" | null;

function Workspace({ document: initial }: { document: ReviewDocument }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [document, setDocument] = useState(initial);
  const [draft, setDraft] = useState(() => toDraft(initial.fields));
  const [panel, setPanel] = useState<Panel>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<{ text: string } | null>(null);
  const [view, setView] = useState<"fields" | "preview">("fields");
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  const reviewable = document.status === "needs_review";
  const failedRules = document.ruleResults.filter((rule) => rule.outcome === "fail");
  const conflict = error instanceof ApiError && error.status === 409;
  const notes = flaggedFields(document);
  if (error instanceof ApiError) {
    for (const item of error.fieldErrors) {
      notes.set(serverFieldName(item.field), item.message);
    }
  }

  useEffect(() => {
    if (panel) reasonRef.current?.focus();
  }, [panel]);

  useEffect(() => {
    if (message) statusRef.current?.focus();
  }, [message]);

  function openPanel(next: Exclude<Panel, null>) {
    opener.current = globalThis.document.activeElement as HTMLElement | null;
    setReason("");
    setPanel(next);
  }

  function closePanel() {
    setPanel(null);
    opener.current?.focus();
  }

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function saved(): Promise<ReviewDocument> {
    if (!isDirty(draft, document)) return document;
    const updated = await correctDocument(document.id, document.version, toFields(draft));
    setDocument(updated);
    setDraft(toDraft(updated.fields));
    return updated;
  }

  function save() {
    void run(async () => {
      await saved();
      setMessage({ text: "Corrections saved. The rules have been run again." });
    });
  }

  async function goToNext(flash?: string) {
    await client.invalidateQueries({ queryKey: ["documents"] });
    const next = await nextInReview(document.id);
    await navigate(next ? `/documents/${next}` : "/", { state: { flash } });
  }

  function approve() {
    void run(async () => {
      const current = await saved();
      if (current.ruleResults.some((rule) => rule.outcome === "fail")) {
        openPanel("override");
        return;
      }
      await approveDocument(current.id, current.version, null);
      await goToNext(`${current.filename} was approved.`);
    });
  }

  function submitPanel(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim()) {
      reasonRef.current?.focus();
      return;
    }
    void run(async () => {
      const current = await saved();
      if (panel === "override") {
        await approveDocument(current.id, current.version, reason);
        await goToNext(`${current.filename} was approved with an override.`);
      } else {
        await rejectDocument(current.id, current.version, reason);
        await goToNext(`${current.filename} was rejected.`);
      }
    });
  }

  function reload() {
    void run(async () => {
      const fresh = await getDocument(document.id);
      client.setQueryData(["document", document.id], fresh);
      setDocument(fresh);
      setDraft(toDraft(fresh.fields));
      setPanel(null);
    });
  }

  // Registered on each render, so the handlers always see the current draft and version.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!event.altKey || !event.shiftKey) return;
      if (event.code === "KeyN") {
        event.preventDefault();
        void run(() => goToNext());
        return;
      }
      if (!reviewable) return;
      if (event.code === "KeyS") {
        event.preventDefault();
        save();
      } else if (event.code === "KeyA") {
        event.preventDefault();
        approve();
      } else if (event.code === "KeyR") {
        event.preventDefault();
        openPanel("reject");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  });

  return (
    <>
      <div className="review-heading">
        <h1>{document.filename}</h1>
        <span className={`status status-${document.status}`}>{STATUS_LABELS[document.status]}</span>
      </div>
      <p ref={statusRef} role="status" tabIndex={-1} className="status-message">
        {message?.text}
      </p>
      {document.statusReasons.length > 0 && (
        <ul className="reasons" aria-label="Why this document needs review">
          {document.statusReasons.map((code) => (
            <li key={code}>{REASON_TEXT[code] ?? code}</li>
          ))}
        </ul>
      )}
      {failedRules.length === 0 && reviewable && (
        <p className="muted">No rule has failed. Check the document, then approve or reject it.</p>
      )}
      {!reviewable && <p className="muted">This document is finished, so it cannot be changed.</p>}
      {error !== null && <ErrorNotice error={error} />}
      {conflict && (
        <p>
          <button type="button" onClick={reload}>
            Reload this document
          </button>
        </p>
      )}
      <div className="view-switch" role="group" aria-label="Show">
        {(["fields", "preview"] as const).map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={view === name}
            onClick={() => {
              setView(name);
            }}
          >
            {name === "fields" ? "Fields" : "Preview"}
          </button>
        ))}
      </div>
      <div className="review-grid" data-view={view}>
        <section className="preview-pane" aria-label="Document preview">
          <PagePreview
            documentId={document.id}
            filename={document.filename}
            pageCount={document.pageCount}
          />
        </section>
        <section className="review-fields" aria-label="Extracted fields">
          <FieldsForm draft={draft} setDraft={setDraft} notes={notes} readOnly={!reviewable} />
          {reviewable && (
            <div className="review-actions">
              <BusyButton type="button" busy={busy} busyLabel="Saving" onClick={save}>
                Save corrections
              </BusyButton>
              <BusyButton type="button" className="primary" busy={busy} onClick={approve}>
                Approve
              </BusyButton>
              <BusyButton
                type="button"
                busy={busy}
                onClick={() => {
                  openPanel("reject");
                }}
              >
                Reject
              </BusyButton>
            </div>
          )}
          {panel && (
            <form
              className="reason-panel"
              onSubmit={submitPanel}
              onKeyDown={(event) => {
                if (event.key === "Escape") closePanel();
              }}
            >
              <label htmlFor="reason">
                {panel === "override"
                  ? "A rule failed. Why approve anyway?"
                  : "Why is this document rejected?"}
              </label>
              <textarea
                id="reason"
                ref={reasonRef}
                rows={3}
                required
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
              />
              <div className="review-actions">
                <BusyButton type="submit" className="primary" busy={busy}>
                  {panel === "override" ? "Approve with override" : "Reject document"}
                </BusyButton>
                <button type="button" onClick={closePanel}>
                  Cancel
                </button>
              </div>
            </form>
          )}
          <div className="shortcuts">
            <strong>Keyboard shortcuts</strong>
            <dl>
              {SHORTCUTS.map(([keys, action]) => (
                <div key={keys}>
                  <dt>
                    <kbd>{keys}</kbd>
                  </dt>
                  <dd>{action}</dd>
                </div>
              ))}
            </dl>
          </div>
          <BusyButton
            type="button"
            busy={busy}
            onClick={() => {
              void run(() => goToNext());
            }}
          >
            Next document
          </BusyButton>
        </section>
      </div>
    </>
  );
}

export function ReviewPage() {
  const { id = "" } = useParams();
  const document = useDocument(id);

  if (document.isPending) {
    return <Loading label="Loading document" />;
  }
  if (document.isError) {
    if (document.error instanceof ApiError && document.error.status === 404) {
      return (
        <>
          <h1>Document not found</h1>
          <p>
            <Link to="/">Back to the inbox</Link>
          </p>
        </>
      );
    }
    return (
      <ErrorNotice
        error={document.error}
        onRetry={() => {
          void document.refetch();
        }}
      />
    );
  }
  // Keyed by document, so moving to the next one starts with a fresh draft.
  return <Workspace key={document.data.id} document={document.data} />;
}
