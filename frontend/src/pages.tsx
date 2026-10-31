import { Link } from "react-router";

export function InboxPage() {
  return (
    <>
      <h1>Inbox</h1>
      <p className="muted">Uploaded documents will appear here.</p>
    </>
  );
}

export function MetricsPage() {
  return (
    <>
      <h1>Metrics</h1>
      <p className="muted">No documents have been processed yet.</p>
    </>
  );
}

export function NotFoundPage() {
  return (
    <>
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the inbox</Link>
      </p>
    </>
  );
}
