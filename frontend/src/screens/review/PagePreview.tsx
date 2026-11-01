import { useState } from "react";

const ZOOM_LEVELS = [100, 150, 200] as const;

interface PagePreviewProps {
  documentId: string;
  filename: string;
  pageCount: number | null;
}

export function PagePreview({ documentId, filename, pageCount }: PagePreviewProps) {
  const pages = pageCount ?? 0;
  const [page, setPage] = useState(1);
  const [zoomIndex, setZoomIndex] = useState(0);
  // Keyed by page, so moving to a new page starts from "loading" without an effect.
  const [loaded, setLoaded] = useState<{ page: number; failed: boolean } | null>(null);
  const state = loaded?.page === page ? loaded : null;
  const zoom = ZOOM_LEVELS[zoomIndex] ?? 100;

  if (pages === 0) {
    return <p className="muted">No pages are available for this document yet.</p>;
  }

  return (
    <>
      <div className="preview-tools" role="group" aria-label="Page preview">
        <button
          type="button"
          aria-disabled={page <= 1}
          onClick={() => {
            if (page > 1) setPage(page - 1);
          }}
        >
          Previous page
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button
          type="button"
          aria-disabled={page >= pages}
          onClick={() => {
            if (page < pages) setPage(page + 1);
          }}
        >
          Next page
        </button>
        <button
          type="button"
          aria-disabled={zoomIndex === 0}
          onClick={() => {
            if (zoomIndex > 0) setZoomIndex(zoomIndex - 1);
          }}
        >
          Zoom out
        </button>
        <span>{zoom}%</span>
        <button
          type="button"
          aria-disabled={zoomIndex === ZOOM_LEVELS.length - 1}
          onClick={() => {
            if (zoomIndex < ZOOM_LEVELS.length - 1) setZoomIndex(zoomIndex + 1);
          }}
        >
          Zoom in
        </button>
      </div>
      {state?.failed ? (
        <p className="notice notice-error" role="alert">
          This page could not be loaded.
        </p>
      ) : (
        <>
          {!state && <p className="muted">Loading page</p>}
          {/* Focusable, so a zoomed page can be scrolled from the keyboard. */}
          <div
            className={`preview-frame zoom-${String(zoom)}`}
            tabIndex={0}
            role="group"
            aria-label="Page image, scrollable"
          >
            <img
              key={page}
              src={`/api/documents/${documentId}/pages/${String(page)}`}
              alt={`Page ${String(page)} of ${String(pages)} of ${filename}`}
              onLoad={() => {
                setLoaded({ page, failed: false });
              }}
              onError={() => {
                setLoaded({ page, failed: true });
              }}
            />
          </div>
        </>
      )}
    </>
  );
}
