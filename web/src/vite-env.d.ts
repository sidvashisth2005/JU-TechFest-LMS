/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API origin, e.g. https://lms.example.com. Empty = same origin (production) or the Vite proxy (dev). */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
