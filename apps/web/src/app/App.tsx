import { lazy, Suspense } from "react";

import { ApplicationErrorBoundary, ShellLoadingFallback } from "./boundaries";

const AgentDeskWorkspace = lazy(async () => {
  const module = await import("./AgentDeskWorkspace");
  return { default: module.AgentDeskWorkspace };
});

export function App() {
  return (
    <ApplicationErrorBoundary>
      <Suspense fallback={<ShellLoadingFallback />}>
        <AgentDeskWorkspace />
      </Suspense>
    </ApplicationErrorBoundary>
  );
}
