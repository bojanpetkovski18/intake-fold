import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { ReviewFields } from "../../api/types";
import { EMPTY_LINE, type FieldsDraft, type LineDraft } from "./draft";

const SCALAR_FIELDS = [
  ["vendorName", "Vendor", "text"],
  ["invoiceNumber", "Invoice number", "text"],
  ["issueDate", "Issue date", "date"],
  ["dueDate", "Due date", "date"],
  ["currency", "Currency", "text"],
  ["subtotal", "Subtotal", "money"],
  ["taxTotal", "Tax", "money"],
  ["adjustmentsTotal", "Adjustments", "money"],
  ["total", "Total", "money"],
] as const;

const LINE_FIELDS = [
  ["quantity", "quantity"],
  ["unitPrice", "unit price"],
  ["amount", "amount"],
] as const;

interface FieldsFormProps {
  draft: FieldsDraft;
  setDraft: Dispatch<SetStateAction<FieldsDraft>>;
  notes: Map<string, string>;
  readOnly: boolean;
}

export function FieldsForm({ draft, setDraft, notes, readOnly }: FieldsFormProps) {
  const addButton = useRef<HTMLButtonElement>(null);
  const focusLine = useRef<number | null>(null);
  const lineInputs = useRef(new Map<number, HTMLInputElement>());
  const lineNote = notes.get("lineItems");

  useEffect(() => {
    if (focusLine.current !== null) {
      lineInputs.current.get(focusLine.current)?.focus();
      focusLine.current = null;
    }
  });

  function setLine(index: number, field: keyof LineDraft, value: string) {
    setDraft((current) => ({
      ...current,
      lineItems: current.lineItems.map((line, position) =>
        position === index ? { ...line, [field]: value } : line,
      ),
    }));
  }

  return (
    <>
      <div className="field">
        <label htmlFor="documentType">Document type</label>
        <select
          id="documentType"
          value={draft.documentType}
          disabled={readOnly}
          onChange={(event) => {
            const documentType = event.target.value as ReviewFields["documentType"];
            setDraft((current) => ({ ...current, documentType }));
          }}
        >
          <option value="invoice">Invoice</option>
          <option value="receipt">Receipt</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div className="field-grid">
        {SCALAR_FIELDS.map(([name, label, kind]) => {
          const note = notes.get(name);
          return (
            <div key={name} className={note ? "field field-flagged" : "field"}>
              <label htmlFor={name}>{label}</label>
              <input
                id={name}
                type={kind === "date" ? "date" : "text"}
                inputMode={kind === "money" ? "decimal" : undefined}
                autoComplete="off"
                value={draft[name]}
                readOnly={readOnly}
                aria-invalid={note ? true : undefined}
                aria-describedby={note ? `${name}-note` : undefined}
                onChange={(event) => {
                  const { value } = event.target;
                  setDraft((current) => ({ ...current, [name]: value }));
                }}
              />
              {note && (
                <p id={`${name}-note`} className="field-note">
                  {note}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <section aria-labelledby="line-items-heading">
        <h3 id="line-items-heading">Line items</h3>
        {lineNote && <p className="field-note">{lineNote}</p>}
        {draft.lineItems.length === 0 && <p className="muted">No line items.</p>}
        {draft.lineItems.map((line, index) => {
          const number = index + 1;
          return (
            <div className="line-row" key={index}>
              <div className="field line-description">
                <label htmlFor={`line-${String(index)}-description`}>
                  Line {number} description
                </label>
                <input
                  id={`line-${String(index)}-description`}
                  ref={(element) => {
                    if (element) lineInputs.current.set(index, element);
                    else lineInputs.current.delete(index);
                  }}
                  value={line.description}
                  readOnly={readOnly}
                  autoComplete="off"
                  onChange={(event) => {
                    setLine(index, "description", event.target.value);
                  }}
                />
              </div>
              {LINE_FIELDS.map(([field, label]) => {
                const id = `line-${String(index)}-${field}`;
                const note = notes.get(`lineItems.${String(index)}.${field}`);
                return (
                  <div key={field} className={note ? "field field-flagged" : "field"}>
                    <label htmlFor={id}>
                      Line {number} {label}
                    </label>
                    <input
                      id={id}
                      inputMode="decimal"
                      autoComplete="off"
                      value={line[field]}
                      readOnly={readOnly}
                      aria-invalid={note ? true : undefined}
                      aria-describedby={note ? `${id}-note` : undefined}
                      onChange={(event) => {
                        setLine(index, field, event.target.value);
                      }}
                    />
                    {note && (
                      <p id={`${id}-note`} className="field-note">
                        {note}
                      </p>
                    )}
                  </div>
                );
              })}
              {!readOnly && (
                <button
                  type="button"
                  className="line-remove"
                  aria-label={`Remove line ${String(number)}`}
                  onClick={() => {
                    setDraft((current) => ({
                      ...current,
                      lineItems: current.lineItems.filter((_, position) => position !== index),
                    }));
                    // The button is about to disappear, so hand focus somewhere stable.
                    addButton.current?.focus();
                  }}
                >
                  Remove
                </button>
              )}
            </div>
          );
        })}
        {!readOnly && (
          <button
            type="button"
            ref={addButton}
            onClick={() => {
              focusLine.current = draft.lineItems.length;
              setDraft((current) => ({
                ...current,
                lineItems: [...current.lineItems, { ...EMPTY_LINE }],
              }));
            }}
          >
            Add line
          </button>
        )}
      </section>
    </>
  );
}
