import react from "@vitejs/plugin-react";
import {defineConfig} from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["src/setupTests.ts"],
  },
  server: {
    host: "0.0.0.0",
    port: 5173
  },
  preview: {
    host: "0.0.0.0",
    port: 5173
  }
});
