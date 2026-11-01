import type { ButtonHTMLAttributes, MouseEvent } from "react";
import { ApiError } from "../api/client";

interface BusyButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  busy?: boolean;
  busyLabel?: string;
}

/** aria-disabled, not disabled: a disabled button would drop keyboard focus to the page. */
export function BusyButton({
  busy = false,
  busyLabel,
  children,
  onClick,
  ...rest
}: BusyButtonProps) {
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (busy) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  }

  return (
    <button {...rest} aria-disabled={busy} onClick={handleClick}>
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <p className="muted" role="status">
      {label}
    </p>
  );
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const traceId = error instanceof ApiError ? error.traceId : null;
  return (
    <div className="notice notice-error" role="alert">
      <p>{errorText(error)}</p>
      {traceId && <p className="trace">Reference: {traceId}</p>}
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
