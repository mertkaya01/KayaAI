import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirme: `npm run dev` → API çağrıları 127.0.0.1:8765'e yönlenir.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } },
  },
  test: { environment: "jsdom", globals: true },
});
