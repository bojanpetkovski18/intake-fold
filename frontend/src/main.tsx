import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { routes } from "./routes";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("The #root element is missing from index.html.");
}

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={createBrowserRouter(routes)} />
  </StrictMode>,
);
