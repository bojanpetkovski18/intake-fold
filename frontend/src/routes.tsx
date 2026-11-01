import type { RouteObject } from "react-router";
import { AppLayout } from "./AppLayout";
import { MetricsPage, NotFoundPage } from "./pages";
import { DeadLettersPage } from "./screens/DeadLettersPage";
import { InboxPage } from "./screens/InboxPage";
import { RequireSession } from "./screens/RequireSession";
import { SignInPage } from "./screens/SignInPage";

export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { path: "/sign-in", element: <SignInPage /> },
      {
        element: <RequireSession />,
        children: [
          { path: "/", element: <InboxPage /> },
          { path: "/dead-letters", element: <DeadLettersPage /> },
          { path: "/metrics", element: <MetricsPage /> },
        ],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
