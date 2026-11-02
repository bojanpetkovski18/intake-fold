import { useEffect, useRef, useState } from "react";
import { useDeadJobs, useRetryJob, useSession } from "../api/hooks";
import { BusyButton, ErrorNotice, Loading } from "../components/feedback";

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function DeadLettersPage() {
  const session = useSession();
  const jobs = useDeadJobs();
  const retry = useRetryJob();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const [message, setMessage] = useState<{ text: string } | null>(null);
  const isAdmin = session.data?.user.role === "admin";

  // The button that had focus disappears with its row. An effect, because the message element
  // cannot take focus until it has rendered: while empty it is display: none.
  useEffect(() => {
    if (message) {
      statusRef.current?.focus();
    }
  }, [message]);

  function requeue(jobId: string, name: string) {
    retry.mutate(jobId, {
      onSuccess: () => {
        setMessage({ text: `${name} was requeued.` });
      },
    });
  }

  return (
    <>
      <h1>Dead letters</h1>
      <p className="muted">Jobs that ran out of attempts or cannot be retried automatically.</p>
      <p ref={statusRef} role="status" tabIndex={-1} className="status-message">
        {message?.text}
      </p>
      {retry.isError && <ErrorNotice error={retry.error} />}
      {jobs.isPending && <Loading label="Loading dead jobs" />}
      {jobs.isError && (
        <ErrorNotice
          error={jobs.error}
          onRetry={() => {
            void jobs.refetch();
          }}
        />
      )}
      {jobs.isSuccess && renderJobs()}
    </>
  );

  // A plain function, not a component: one declared here would remount on each render.
  function renderJobs() {
    const items = jobs.data?.pages.flatMap((page) => page.items) ?? [];
    if (items.length === 0) {
      return <p className="muted">No dead jobs.</p>;
    }
    return (
      <>
        <table className="records">
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Error</th>
              <th scope="col">Attempts</th>
              <th scope="col">Died</th>
              {isAdmin && <th scope="col">Action</th>}
            </tr>
          </thead>
          <tbody>
            {items.map((job) => {
              const name = job.filename ?? job.kind;
              return (
                <tr key={job.id}>
                  <th scope="row" className="filename">
                    {name}
                  </th>
                  <td data-label="Error">{job.lastError ?? "Unknown"}</td>
                  <td data-label="Attempts">
                    {job.attempts} of {job.maxAttempts}
                  </td>
                  <td data-label="Died">{dateFormat.format(new Date(job.updatedAt))}</td>
                  {isAdmin && (
                    <td data-label="Action">
                      <BusyButton
                        type="button"
                        busy={retry.isPending && retry.variables === job.id}
                        busyLabel="Requeuing"
                        aria-label={`Requeue ${name}`}
                        onClick={() => {
                          requeue(job.id, name);
                        }}
                      >
                        Requeue
                      </BusyButton>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
        {jobs.hasNextPage && (
          <BusyButton
            type="button"
            busy={jobs.isFetchingNextPage}
            busyLabel="Loading more"
            onClick={() => {
              void jobs.fetchNextPage();
            }}
          >
            Load more
          </BusyButton>
        )}
      </>
    );
  }
}
