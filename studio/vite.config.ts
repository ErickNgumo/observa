import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../python/python/observa/static/studio",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["lightweight-charts"],
          markdown: ["react-markdown"],
        },
      },
    },
  },
});
