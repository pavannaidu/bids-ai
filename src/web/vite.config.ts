import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds straight into the FastAPI app's static/ dir, served at /static/*.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
