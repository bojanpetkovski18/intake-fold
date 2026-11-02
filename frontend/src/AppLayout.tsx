import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useSession, useSignOut } from "./api/hooks";
import { BusyButton, ErrorNotice } from "./components/feedback";

export function AppLayout() {
  const location = useLocation();
  const { pathname } = location;
  const flash = (location.state as { flash?: string } | null)?.flash;
  const navigate = useNavigate();
  const session = useSession();
  const signOut = useSignOut();
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);
  const user = session.data?.user;

  // A client-side route change is silent to keyboard and screen-reader users otherwise.
  useEffect(() => {
    if (previousPath.current !== pathname) {
      previousPath.current = pathname;
      main.current?.focus();
    }
  }, [pathname]);

  function leave() {
    signOut.mutate(undefined, {
      onSuccess: () => {
        void navigate("/sign-in");
      },
    });
  }

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <Link className="app-brand" to="/">
          Intakefold
        </Link>
        {user && (
          <>
            <nav className="app-nav" aria-label="Main">
              <ul>
                <li>
                  <NavLink to="/" end>
                    Inbox
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/dead-letters">Dead letters</NavLink>
                </li>
                <li>
                  <NavLink to="/metrics">Metrics</NavLink>
                </li>
              </ul>
            </nav>
            <div className="app-user">
              <span>{user.displayName}</span>
              <BusyButton
                type="button"
                busy={signOut.isPending}
                busyLabel="Signing out"
                onClick={leave}
              >
                Sign out
              </BusyButton>
            </div>
          </>
        )}
      </header>
      {session.data?.extractor === "mock" && (
        <p className="banner">
          Mock extractor: results come from stored labels, not a model. They say nothing about
          accuracy.
        </p>
      )}
      <main id="main" className="app-main" ref={main} tabIndex={-1}>
        {signOut.isError && <ErrorNotice error={signOut.error} />}
        {flash && <p role="status">{flash}</p>}
        <Outlet />
      </main>
    </>
  );
}
