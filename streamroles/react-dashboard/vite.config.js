import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config adjusted so the production build is rooted at / (served from /).
// This avoids the frontend requiring the browser URL to include /dashboard.
// Dev server proxy continues to forward dashboard proxy calls to the bot API.
export default defineConfig({
  plugins: [react()],
  // serve the app at root in production
  base: "/",
  build: {
    outDir: "../static/react-build",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Keep proxy path matching the backend public proxy endpoints.
      // In dev this will proxy /dashboard/proxy/* -> http://localhost:8080/dashboard/proxy/*
      "/dashboard/proxy": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
