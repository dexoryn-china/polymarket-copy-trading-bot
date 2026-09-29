/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOCK?: string
  /** Mock only: make starting Perps copying fail like a missing key in real mode. */
  readonly VITE_MOCK_FAIL_PERPS_START?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
