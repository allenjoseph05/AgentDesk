import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AgentDeskRuntimeProvider } from "./app/AgentDeskRuntime";
import { createBrowserCoordinatorAgent } from "./agui/client";
import { AgentDeskStateProvider } from "./agui/store-react";
import "./styles.css";

const rootElement = document.getElementById("root");
const createBrowserAgent = () =>
  createBrowserCoordinatorAgent({ environment: import.meta.env });

if (rootElement === null) {
  throw new Error("AgentDesk root element is missing");
}

createRoot(rootElement).render(
  <StrictMode>
    <AgentDeskStateProvider>
      <AgentDeskRuntimeProvider createAgent={createBrowserAgent}>
        <App />
      </AgentDeskRuntimeProvider>
    </AgentDeskStateProvider>
  </StrictMode>,
);
