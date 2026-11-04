import { useEffect, useRef, useState, type SubmitEvent } from "react";
import { Navigate, useLocation } from "react-router";
import { useDemo, useSession, useSignIn } from "../api/hooks";
import type { DemoAccount } from "../api/types";
import { BusyButton, errorText } from "../components/feedback";

const ROLE_NAMES = { reviewer: "Reviewer", admin: "Admin" } as const;

function DemoAccounts({ accounts }: { accounts: DemoAccount[] }) {
  return (
    <section className="demo-accounts" aria-labelledby="demo-accounts-heading">
      <h2 id="demo-accounts-heading">Demo accounts</h2>
      <p className="muted">Fictional accounts, shown because this is a demo.</p>
      <ul>
        {accounts.map((account) => (
          <li key={account.email}>
            <strong>{ROLE_NAMES[account.role]}</strong>
            <dl>
              <div>
                <dt>Email</dt>
                <dd>{account.email}</dd>
              </div>
              <div>
                <dt>Password</dt>
                <dd>{account.password}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SignInPage() {
  const location = useLocation();
  const session = useSession();
  const signIn = useSignIn();
  const demo = useDemo();
  const errorRef = useRef<HTMLParagraphElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (signIn.isError) {
      errorRef.current?.focus();
    }
  }, [signIn.isError, signIn.failureCount]);

  if (session.data) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    signIn.mutate({ email, password });
  }

  return (
    <section className="sign-in" aria-labelledby="sign-in-heading">
      <h1 id="sign-in-heading">Sign in</h1>
      {signIn.isError && (
        <p className="notice notice-error" role="alert" ref={errorRef} tabIndex={-1}>
          {errorText(signIn.error)}
        </p>
      )}
      <form onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
        />
        <BusyButton
          type="submit"
          className="primary"
          busy={signIn.isPending}
          busyLabel="Signing in"
        >
          Sign in
        </BusyButton>
      </form>
      {demo.data && <DemoAccounts accounts={demo.data.accounts} />}
    </section>
  );
}
