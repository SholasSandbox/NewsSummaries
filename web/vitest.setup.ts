/**
 * vitest.setup.ts
 *
 * Global test setup — extends Vitest's expect with @testing-library/jest-dom
 * matchers (toBeInTheDocument, toHaveTextContent, etc.).
 *
 * Env vars set here are visible to module-level constants in the code under
 * test (e.g. `const TABLE = process.env.DYNAMODB_TABLE_NAME ?? ""`), because
 * setupFiles run before each test file's top-level imports are resolved.
 */
import "@testing-library/jest-dom"

// Set env vars before any modules are imported so module-level constants
// (captured with `?? ""` at load time) see the correct test values.
process.env.DYNAMODB_TABLE_NAME = "test-episodes"
process.env.AWS_REGION = "us-east-1"
