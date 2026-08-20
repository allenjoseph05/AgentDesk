import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AgentDeskRuntimeProvider } from "./app/AgentDeskRuntime";
import { AgentDeskStateProvider } from "./agui/store-react";
import "./styles.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("AgentDesk root element is missing");
}

createRoot(rootElement).render(
  <StrictMode>
    <AgentDeskStateProvider>
      <AgentDeskRuntimeProvider>
        <App />
      </AgentDeskRuntimeProvider>
    </AgentDeskStateProvider>
  </StrictMode>,
);
