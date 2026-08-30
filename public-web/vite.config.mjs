import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { researchPublicProjection } from "./scripts/research-public-projection.mjs";

export default defineConfig({
  build: {
    outDir: "dist/client",
    rollupOptions: { output: { manualChunks: { "react-vendor": ["react", "react-dom", "react-dom/client"], "research-catalog": ["./src/researchCatalog.js"] } } },
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  plugins: [researchPublicProjection(), react()],
});
