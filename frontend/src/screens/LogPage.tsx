import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { ApiError, getDeliveries, getRunLog } from "../api/client";
import type { AuditEventView, DeliveryView, RunStepView } from "../api/types";
import { ErrorNotice, Loading } from "../components/feedback";

const ACTION_TEXT: Record<string, string> = {
  document_uploaded: "Uploaded",
  document_routed: "Routed by the rules",
  field_corrected: "Corrected",
  document_approved: "Approved",
  document_rejected: "Rejected",
  job_requeued: "Requeued",
};

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" });

function when(value: string | null): string {
  return value ? timeFormat.format(new Date(value)) : "Not finished";
}

function show(value: string | number | null): string {
  return value === null ? "None" : String(value);
}

function Steps({ steps }: { steps: RunStepView[] }) {
  if (steps.length === 0) {
    return <p className="muted">No steps have run yet.</p>;
  }
  return (
    <table className="records">
      <thead>
        <tr>
          <th scope="col">Step</th>
          <th scope="col">Result</th>
          <th scope="col">Started</th>
          <th scope="col">Took</th>
          <th scope="col">Extractor</th>
          <th scope="col">Tokens in / out</th>
          <th scope="col">Estimated cost (USD)</th>
        </tr>
      </thead>
      <tbody>
        {steps.map((step, index) => (
          <tr key={`${step.step}-${String(step.attempt)}-${String(index)}`}>
            <th scope="row">
              {step.step} <span className="muted">(attempt {step.attempt})</span>
            </th>
            <td data-label="Result">
              {step.status}
              {step.errorCode ? `: ${step.errorCode}` : ""}
            </td>
            <td data-label="Started">{when(step.startedAt)}</td>
            <td data-label="Took">
              {step.durationMs === null ? "Running" : `${String(step.durationMs)} ms`}
            </td>
            <td data-label="Extractor">
              {step.extractor ? `${step.extractor}${step.model ? `, ${step.model}` : ""}` : "None"}
            </td>
            <td data-label="Tokens in / out">
              {step.inputTokens === null
                ? "None"
                : `${String(step.inputTokens)} / ${show(step.outputTokens)}`}
            </td>
            <td data-label="Estimated cost (USD)">{step.estimatedCostUsd ?? "None"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Events({ events }: { events: AuditEventView[] }) {
  if (events.length === 0) {
    return <p className="muted">Nothing has been recorded yet.</p>;
  }
  return (
    <ol className="trail">
      {events.map((event, index) => (
        <li key={index}>
          <strong>{ACTION_TEXT[event.action] ?? event.action}</strong>
          {event.field && (
            <>
              {" "}
              <code>{event.field}</code>: {event.oldValue ?? "empty"} to {event.newValue ?? "empty"}
            </>
          )}
          {!event.field && event.newValue && <> ({event.newValue})</>}
          <div className="muted">
            {event.actorName ?? "System"}, {when(event.createdAt)}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Deliveries({ deliveries }: { deliveries: DeliveryView[] }) {
  if (deliveries.length === 0) {
    return <p className="muted">No deliveries. A document is delivered once it is approved.</p>;
  }
  return (
    <ul className="trail">
      {deliveries.map((delivery) => (
        <li key={`${delivery.target}-${delivery.eventId}`}>
          <strong>{delivery.target}</strong>: {delivery.status}
          <ol>
            {delivery.attempts.map((attempt) => (
              <li key={attempt.attempt}>
                Attempt {attempt.attempt}: {show(attempt.statusCode)}
                {attempt.errorCode ? ` (${attempt.errorCode})` : ""}, {show(attempt.durationMs)} ms
              </li>
            ))}
          </ol>
        </li>
      ))}
    </ul>
  );
}

export function LogPage() {
  const { id = "" } = useParams();
  const log = useQuery({ queryKey: ["run-log", id], queryFn: () => getRunLog(id) });
  const deliveries = useQuery({ queryKey: ["deliveries", id], queryFn: () => getDeliveries(id) });

  if (log.isPending || deliveries.isPending) {
    return <Loading label="Loading the document log" />;
  }
  const failure = log.error ?? deliveries.error;
  if (failure) {
    if (failure instanceof ApiError && failure.status === 404) {
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
        error={failure}
        onRetry={() => {
          void log.refetch();
          void deliveries.refetch();
        }}
      />
    );
  }
  return (
    <>
      <h1>Document log</h1>
      <p>
        <Link to={`/documents/${id}`}>Back to the document</Link>
      </p>
      <section aria-labelledby="steps-heading">
        <h2 id="steps-heading">Run steps</h2>
        <Steps steps={log.data?.steps ?? []} />
      </section>
      <section aria-labelledby="trail-heading">
        <h2 id="trail-heading">Audit trail</h2>
        <Events events={log.data?.events ?? []} />
      </section>
      <section aria-labelledby="deliveries-heading">
        <h2 id="deliveries-heading">Deliveries</h2>
        <Deliveries deliveries={deliveries.data ?? []} />
      </section>
    </>
  );
}
