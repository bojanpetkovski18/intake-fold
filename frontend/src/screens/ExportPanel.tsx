import { useState, type SubmitEvent } from "react";
import { exportInvoices } from "../api/client";
import { BusyButton, ErrorNotice } from "../components/feedback";

const FILENAME = "approved-invoices.csv";

// Fetched rather than linked, so a refused export shows its reason here instead of
// downloading the error as a file.
function save(text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = FILENAME;
  link.click();
  URL.revokeObjectURL(url);
}

export function ExportPanel() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [message, setMessage] = useState("");

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setFailure(null);
    setMessage("");
    try {
      save(await exportInvoices(from, to));
      setMessage(`Saved ${FILENAME}.`);
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="export-heading">
      <h2 id="export-heading">Export</h2>
      <p className="muted">Approved invoices as CSV, one row per line item. Dates are in UTC.</p>
      <form
        className="export-form"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label>
          Approved from{" "}
          <input
            type="date"
            value={from}
            onChange={(event) => {
              setFrom(event.target.value);
            }}
          />
        </label>
        <label>
          Approved to{" "}
          <input
            type="date"
            value={to}
            onChange={(event) => {
              setTo(event.target.value);
            }}
          />
        </label>
        <BusyButton type="submit" busy={busy} busyLabel="Exporting">
          Export CSV
        </BusyButton>
      </form>
      {failure !== null && <ErrorNotice error={failure} />}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
