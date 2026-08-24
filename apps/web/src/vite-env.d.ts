/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AGENTDESK_AG_UI_ENDPOINT?: string;
  readonly VITE_AGENTDESK_RUNTIME_MODE?: "live" | "demo";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
