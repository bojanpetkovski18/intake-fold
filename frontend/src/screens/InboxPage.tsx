import { Link, useSearchParams } from "react-router";
import { useDocuments } from "../api/hooks";
import { STATUS_LABELS } from "../api/labels";
import { DOCUMENT_STATUSES, type DocumentStatus } from "../api/types";
import { BusyButton, ErrorNotice, Loading } from "../components/feedback";
import { UploadPanel } from "./UploadPanel";

function isStatus(value: string | null): value is DocumentStatus {
  return DOCUMENT_STATUSES.some((status) => status === value);
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function DocumentList({ status }: { status: DocumentStatus | null }) {
  const documents = useDocuments(status);

  if (documents.isPending) {
    return <Loading label="Loading documents" />;
  }
  if (documents.isError) {
    return (
      <ErrorNotice
        error={documents.error}
        onRetry={() => {
          void documents.refetch();
        }}
      />
    );
  }
  const items = documents.data.pages.flatMap((page) => page.items);
  if (items.length === 0) {
    return (
      <p className="muted">
        {status
          ? `No documents are ${STATUS_LABELS[status].toLowerCase()}.`
          : "No documents yet. Upload one to get started."}
      </p>
    );
  }
  return (
    <>
      <table className="records">
        <thead>
          <tr>
            <th scope="col">File</th>
            <th scope="col">Status</th>
            <th scope="col">Pages</th>
            <th scope="col">Received</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <th scope="row" className="filename">
                <Link to={`/documents/${item.id}`}>{item.filename}</Link>
              </th>
              <td data-label="Status">
                <span className={`status status-${item.status}`}>{STATUS_LABELS[item.status]}</span>
              </td>
              <td data-label="Pages">{item.pageCount ?? "Unknown"}</td>
              <td data-label="Received">{dateFormat.format(new Date(item.receivedAt))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {documents.hasNextPage && (
        <BusyButton
          type="button"
          busy={documents.isFetchingNextPage}
          busyLabel="Loading more"
          onClick={() => {
            void documents.fetchNextPage();
          }}
        >
          Load more
        </BusyButton>
      )}
    </>
  );
}

export function InboxPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("status");
  const status = isStatus(requested) ? requested : null;

  return (
    <>
      <h1>Inbox</h1>
      <UploadPanel />
      <section aria-labelledby="documents-heading">
        <div className="section-heading">
          <h2 id="documents-heading">Documents</h2>
          <label>
            Status{" "}
            <select
              value={status ?? ""}
              onChange={(event) => {
                setParams(event.target.value ? { status: event.target.value } : {});
              }}
            >
              <option value="">All</option>
              {DOCUMENT_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {STATUS_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <DocumentList status={status} />
      </section>
    </>
  );
}
