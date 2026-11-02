import type { RouteObject } from "react-router";
import { AppLayout } from "./AppLayout";
import { NotFoundPage } from "./pages";
import { LogPage } from "./screens/LogPage";
import { MetricsPage } from "./screens/MetricsPage";
import { DeadLettersPage } from "./screens/DeadLettersPage";
import { InboxPage } from "./screens/InboxPage";
import { RequireSession } from "./screens/RequireSession";
import { ReviewPage } from "./screens/review/ReviewPage";
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
          { path: "/documents/:id", element: <ReviewPage /> },
          { path: "/documents/:id/log", element: <LogPage /> },
          { path: "/dead-letters", element: <DeadLettersPage /> },
          { path: "/metrics", element: <MetricsPage /> },
        ],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
