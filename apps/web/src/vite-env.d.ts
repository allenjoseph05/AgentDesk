/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AGENTDESK_ADAPTIVE_INTAKE_ENABLED?: "true" | "false";
  readonly VITE_AGENTDESK_AG_UI_ENDPOINT?: string;
  readonly VITE_AGENTDESK_RUNTIME_MODE?: "live" | "demo" | "adaptive-demo";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
