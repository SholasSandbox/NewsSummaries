/**
 * vitest.config.ts
 *
 * Vitest configuration for the web/ Next.js 16 application.
 * Uses happy-dom as the browser-like environment so React components
 * and Next.js server utilities can both be tested without a full browser.
 */
import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import path from "path"

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["__tests__/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["app/**", "lib/**"],
      exclude: ["app/globals.css"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
})
