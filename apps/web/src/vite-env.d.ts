/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AGENTDESK_AG_UI_ENDPOINT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
