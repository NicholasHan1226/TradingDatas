import { defineConfig, loadEnv } from "vite";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { researchPublicProjection } from "./scripts/research-public-projection.mjs";

export default defineConfig(({ mode }) => ({
  define: {
    "import.meta.env.VITE_TRADINGDATAS_API_BASE_URL": JSON.stringify(process.env.VITE_TRADINGDATAS_API_BASE_URL ?? loadEnv(mode, fileURLToPath(new URL(".", import.meta.url))).VITE_TRADINGDATAS_API_BASE_URL ?? "https://tradingdatas.com"),
  },
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
}));
