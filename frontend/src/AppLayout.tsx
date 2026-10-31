import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

export function AppLayout() {
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);

  // A client-side route change is silent to keyboard and screen-reader users otherwise.
  useEffect(() => {
    if (previousPath.current !== pathname) {
      previousPath.current = pathname;
      main.current?.focus();
    }
  }, [pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <Link className="app-brand" to="/">
          Intakefold
        </Link>
        <nav className="app-nav" aria-label="Main">
          <ul>
            <li>
              <NavLink to="/" end>
                Inbox
              </NavLink>
            </li>
            <li>
              <NavLink to="/metrics">Metrics</NavLink>
            </li>
          </ul>
        </nav>
      </header>
      <main id="main" className="app-main" ref={main} tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}
