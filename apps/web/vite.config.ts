import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const coordinatorTarget = process.env.AGENTDESK_COORDINATOR_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  envDir: "../..",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/ag-ui": coordinatorTarget,
      "/api/sessions": coordinatorTarget,
    },
  },
});
