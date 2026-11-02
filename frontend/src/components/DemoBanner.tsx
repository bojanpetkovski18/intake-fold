import { useEffect, useRef, useState } from "react";
import { useResetDemo } from "../api/hooks";
import { BusyButton, ErrorNotice } from "./feedback";

interface DemoBannerProps {
  canReset: boolean;
  onReset: (queued: number) => void;
}

export function DemoBanner({ canReset, onReset }: DemoBannerProps) {
  const reset = useResetDemo();
  const [confirming, setConfirming] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);

  // Cancel takes focus first, so a stray Enter cannot erase the demo.
  useEffect(() => {
    if (confirming) {
      cancelButton.current?.focus();
    } else if (returnFocus.current) {
      returnFocus.current = false;
      trigger.current?.focus();
    }
  }, [confirming]);

  function cancel() {
    returnFocus.current = true;
    reset.reset();
    setConfirming(false);
  }

  function confirm() {
    reset.mutate(undefined, {
      onSuccess: ({ queued }) => {
        setConfirming(false);
        onReset(queued);
      },
    });
  }

  return (
    <section className="banner banner-demo" aria-label="Demo mode">
      <p>Demo mode: every vendor, person and document here is fictional.</p>
      {canReset && !confirming && (
        <button
          type="button"
          ref={trigger}
          onClick={() => {
            setConfirming(true);
          }}
        >
          Reset demo data
        </button>
      )}
      {canReset && confirming && (
        <div
          className="demo-confirm"
          role="group"
          aria-labelledby="demo-reset-question"
          onKeyDown={(event) => {
            if (event.key === "Escape") cancel();
          }}
        >
          <p id="demo-reset-question">
            Delete every document, decision and log, and load the demo documents again?
          </p>
          {reset.isError && <ErrorNotice error={reset.error} />}
          <div className="review-actions">
            <BusyButton
              type="button"
              className="primary"
              busy={reset.isPending}
              busyLabel="Resetting"
              onClick={confirm}
            >
              Reset
            </BusyButton>
            <button type="button" ref={cancelButton} onClick={cancel}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
