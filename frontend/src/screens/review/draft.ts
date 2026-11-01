import type { LineItemFields, ReviewDocument, ReviewFields } from "../../api/types";

/** What the inputs hold: strings, with "" for empty. Money is never parsed to number. */
export type LineDraft = Record<keyof LineItemFields, string>;

export interface FieldsDraft {
  documentType: ReviewFields["documentType"];
  vendorName: string;
  invoiceNumber: string;
  issueDate: string;
  dueDate: string;
  currency: string;
  subtotal: string;
  taxTotal: string;
  adjustmentsTotal: string;
  total: string;
  lineItems: LineDraft[];
}

export const EMPTY_LINE: LineDraft = { description: "", quantity: "", unitPrice: "", amount: "" };

export function toDraft(fields: ReviewFields | null): FieldsDraft {
  return {
    documentType: fields?.documentType ?? "invoice",
    vendorName: fields?.vendorName ?? "",
    invoiceNumber: fields?.invoiceNumber ?? "",
    issueDate: fields?.issueDate ?? "",
    dueDate: fields?.dueDate ?? "",
    currency: fields?.currency ?? "",
    subtotal: fields?.subtotal ?? "",
    taxTotal: fields?.taxTotal ?? "",
    adjustmentsTotal: fields?.adjustmentsTotal ?? "",
    total: fields?.total ?? "",
    lineItems: (fields?.lineItems ?? []).map((line) => ({
      description: line.description,
      quantity: line.quantity ?? "",
      unitPrice: line.unitPrice ?? "",
      amount: line.amount ?? "",
    })),
  };
}

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function toFields(draft: FieldsDraft): ReviewFields {
  return {
    documentType: draft.documentType,
    vendorName: orNull(draft.vendorName),
    invoiceNumber: orNull(draft.invoiceNumber),
    issueDate: orNull(draft.issueDate),
    dueDate: orNull(draft.dueDate),
    currency: orNull(draft.currency),
    subtotal: orNull(draft.subtotal),
    taxTotal: orNull(draft.taxTotal),
    adjustmentsTotal: orNull(draft.adjustmentsTotal),
    total: orNull(draft.total),
    lineItems: draft.lineItems.map((line) => ({
      description: line.description,
      quantity: orNull(line.quantity),
      unitPrice: orNull(line.unitPrice),
      amount: orNull(line.amount),
    })),
  };
}

export function isDirty(draft: FieldsDraft, document: ReviewDocument): boolean {
  return JSON.stringify(draft) !== JSON.stringify(toDraft(document.fields));
}

/** Rule failures by field name, so each input can show why it is flagged. */
export function flaggedFields(document: ReviewDocument): Map<string, string> {
  const flagged = new Map<string, string>();
  for (const rule of document.ruleResults) {
    for (const field of rule.fields) {
      flagged.set(field, rule.detail ?? "This field failed a check.");
    }
  }
  for (const field of document.uncertainFields) {
    if (!flagged.has(field)) {
      flagged.set(field, "The extractor was not sure about this field.");
    }
  }
  return flagged;
}

/** Turns body.fields.lineItems.0.amount into lineItems.0.amount. */
export function serverFieldName(location: string): string {
  return location.replace(/^body\.fields\./, "");
}
