import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Bind mount Windows/macOS -> Docker khong phat su kien file: can polling de HMR hoat dong
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      "/api": { target: process.env.API_TARGET || "http://localhost:8000", changeOrigin: true },
    },
  },
});
