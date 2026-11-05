/// <reference types="vite/client" />

// Geospatial intelligence: the map tile source is
// deliberately NOT hardcoded -- see docs/operations/MAP_PROVIDER_CONFIGURATION.md
// and MapExplorerPage.tsx's own fallback when this is unset. Setting
// it to a provider that requires an API key means putting that key in
// this build-time env var, never inline in source -- and even then,
// only a key meant for client-side/public use under that provider's
// own terms, never a server-side secret.
interface ImportMetaEnv {
  readonly VITE_MAP_TILE_URL?: string
  readonly VITE_MAP_TILE_ATTRIBUTION?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
