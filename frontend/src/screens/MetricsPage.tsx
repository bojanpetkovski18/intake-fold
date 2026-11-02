import { useQuery } from "@tanstack/react-query";
import { getMetrics } from "../api/client";
import type { MetricsRow } from "../api/types";
import { ErrorNotice, Loading } from "../components/feedback";

/** Shares arrive as exact decimal strings, such as "0.4000". Shown, never computed with. */
function percent(share: string): string {
  const [whole = "0", fraction = ""] = share.split(".");
  const digits = `${whole}${fraction.padEnd(4, "0")}`.replace(/^0+(?=\d{3})/, "");
  const padded = digits.padStart(3, "0");
  return `${padded.slice(0, -2)}.${padded.slice(-2)}%`;
}

function seconds(value: string | null): string {
  return value === null ? "No timing" : `${value} s`;
}

function label(extractor: string): string {
  if (extractor === "mock") return "Mock (plumbing test, not accuracy)";
  if (extractor === "none") return "Not extracted";
  return extractor;
}

function Row({ row }: { row: MetricsRow }) {
  return (
    <tr>
      <th scope="row">{label(row.extractor)}</th>
      <td data-label="Processed">{row.processed}</td>
      <td data-label="Auto-approved">
        {percent(row.autoApprovedShare)} ({row.autoApproved})
      </td>
      <td data-label="Sent to review">
        {percent(row.reviewShare)} ({row.wentToReview})
      </td>
      <td data-label="Failed">
        {percent(row.failureShare)} ({row.failed})
      </td>
      <td data-label="Average time">{seconds(row.averageSeconds)}</td>
    </tr>
  );
}

export function MetricsPage() {
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: getMetrics });

  return (
    <>
      <h1>Metrics</h1>
      <p className="muted">
        Each extractor is counted separately, and evaluation runs are left out. Average time runs
        from upload to the end of the last pipeline step, so time spent in review is not included.
      </p>
      {metrics.isPending && <Loading label="Loading metrics" />}
      {metrics.isError && (
        <ErrorNotice
          error={metrics.error}
          onRetry={() => {
            void metrics.refetch();
          }}
        />
      )}
      {metrics.isSuccess && metrics.data.rows.length === 0 && (
        <p>No documents have been processed yet, so there is nothing to measure.</p>
      )}
      {metrics.isSuccess && metrics.data.rows.length > 0 && (
        <table className="records">
          <thead>
            <tr>
              <th scope="col">Extractor</th>
              <th scope="col">Processed</th>
              <th scope="col">Auto-approved</th>
              <th scope="col">Sent to review</th>
              <th scope="col">Failed</th>
              <th scope="col">Average time</th>
            </tr>
          </thead>
          <tbody>
            {metrics.data.rows.map((row) => (
              <Row key={row.extractor} row={row} />
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
