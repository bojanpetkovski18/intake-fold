import { Navigate, Outlet, useLocation } from "react-router";
import { useSession } from "../api/hooks";
import { ErrorNotice, Loading } from "../components/feedback";

export function RequireSession() {
  const location = useLocation();
  const session = useSession();

  if (session.isPending) {
    return <Loading label="Loading" />;
  }
  if (session.isError) {
    return (
      <ErrorNotice
        error={session.error}
        onRetry={() => {
          void session.refetch();
        }}
      />
    );
  }
  if (!session.data) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}
