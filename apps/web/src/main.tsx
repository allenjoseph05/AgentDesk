import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AgentDeskRuntimeProvider } from "./app/AgentDeskRuntime";
import "./styles.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("AgentDesk root element is missing");
}

createRoot(rootElement).render(
  <StrictMode>
    <AgentDeskRuntimeProvider>
      <App />
    </AgentDeskRuntimeProvider>
  </StrictMode>,
);
