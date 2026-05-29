/**
 * Playwright global setup hook.
 *
 * E2E database schema is reset on API startup via `ensure_e2e_database()`
 * (drop_all + create_all). Do not delete the SQLite file here — the webServer
 * may already hold a lock on it.
 */
export default function globalSetup() {}
