/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string
  readonly VITE_SUPABASE_ANON_KEY: string
  readonly VITE_RELAY_URL: string
  /** パスポートのダウンロード先（省略時は /download/DreamlandPassport.zip） */
  readonly VITE_CONNECTOR_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
