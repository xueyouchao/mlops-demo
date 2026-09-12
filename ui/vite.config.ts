import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // Dev-only: same proxy layout as the Nginx gateway (see nginx.conf).
      "/auth": "http://localhost:8000",
      "/api": "http://localhost:8000",
      "/docs": "http://localhost:8000",
      "/openapi.json": "http://localhost:8000",
      "/v1": "http://localhost:8001",
      "/diagrams": { target: "http://localhost:5173/public/diagrams", changeOrigin: false },
      "/temporal/": { target: "http://localhost:8233", changeOrigin: true },
      "/mlflow/": { target: "http://localhost:5000", changeOrigin: true, rewrite: (p) => p.replace(/^\/mlflow\//, "/") },
    },
  },
});
