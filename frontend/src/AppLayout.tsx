import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useSession, useSignOut } from "./api/hooks";
import { DemoBanner } from "./components/DemoBanner";
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

  function afterReset(queued: number) {
    const flash = `Demo data reset. ${String(queued)} documents are being processed again.`;
    // Focus moves to the inbox even when it is already showing, because the confirm buttons
    // that held focus are gone.
    void Promise.resolve(navigate("/", { state: { flash } })).then(() => {
      main.current?.focus();
    });
  }

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {/* The banners sit inside the header, so landmark navigation reaches them too. */}
      <header>
        <div className="app-header">
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
        </div>
        {user && session.data?.demoMode && (
          <DemoBanner canReset={user.role === "admin"} onReset={afterReset} />
        )}
        {session.data?.extractor === "mock" && (
          <p className="banner">
            Mock extractor: results come from stored labels, not a model. They say nothing about
            accuracy.
          </p>
        )}
      </header>
      <main id="main" className="app-main" ref={main} tabIndex={-1}>
        {signOut.isError && <ErrorNotice error={signOut.error} />}
        {flash && <p role="status">{flash}</p>}
        <Outlet />
      </main>
    </>
  );
}
