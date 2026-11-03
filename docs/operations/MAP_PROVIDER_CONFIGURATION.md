# Map Provider Configuration (Phase 7)

**Status: IMPLEMENTED.** No map tile provider or API key is hardcoded,
bundled, or defaulted anywhere in this codebase -- this document exists
to configure one for your own deployment.

## 1. Why this is required

The Interactive Map Explorer (`frontend/src/pages/geo/MapExplorerPage.tsx`)
reads its tile source from two build-time environment variables:

```
VITE_MAP_TILE_URL=https://{your-provider}/{z}/{x}/{y}.png
VITE_MAP_TILE_ATTRIBUTION=&copy; Your Attribution Text
```

If `VITE_MAP_TILE_URL` is unset, the page does **not** render a broken
or blank map -- it shows an informative fallback card explaining that
no tile provider is configured, and offers the accessible list view
(every located record as a plain list with coordinates) as a fully
functional alternative. Markers, clustering, the legend, and the
viewport-based spatial query all still work in this mode; only the
background raster tile imagery is unavailable. See
`frontend/vite-env.d.ts` for the `ImportMetaEnv` type augmentation
backing these two variables.

## 2. Why no default is bundled

Every public tile provider (OpenStreetMap's own servers included) has
a usage policy that restricts production/high-volume automated
traffic and typically requires attribution and, for anything beyond
light development use, a registered API key or a self-hosted tile
server. Bundling a specific provider's URL as a silent default would
mean every deployment of this project inherits that provider's terms
and rate limits without the deploying organization ever having agreed
to them -- the specification's "no hardcoded map tile API keys" rule is
honored here in the stronger sense of not hardcoding a tile *source*
at all, not just not hardcoding a *key*.

## 3. Configuration options, by deployment scale

| Option | When to use | Example `VITE_MAP_TILE_URL` |
|---|---|---|
| OpenStreetMap's own tile servers | Light development/demo use only, under [osmfoundation.org's tile usage policy](https://operations.osmfoundation.org/policies/tiles/) -- not appropriate for production or high-volume traffic | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` |
| A commercial tile provider (e.g. Mapbox, MapTiler, Stadia Maps) | Production use at any real scale -- requires signing up for the provider's own account and API key | Provider-specific URL template including your own key, e.g. `https://api.maptiler.com/maps/streets/{z}/{x}/{y}.png?key=YOUR_KEY` |
| A self-hosted tile server (e.g. your own TileServer GL / OpenMapTiles instance) | Air-gapped, classified, or otherwise network-restricted deployments where no external tile request is acceptable | `https://your-internal-host/tiles/{z}/{x}/{y}.png` |

Whichever option is chosen, the key or account credential lives **only**
in the deployment's own `.env` file (gitignored, same convention as
every other `VITE_*`/`SECRET_KEY`/`DATABASE_URL` value in this
project) -- never committed, never hardcoded in a `.tsx` file, and
never present in this repository.

## 4. Setting it up

1. Copy `frontend/.env.example` to `frontend/.env`.
2. Set `VITE_MAP_TILE_URL` to your chosen provider's tile URL template
   (must contain `{z}`, `{x}`, `{y}` placeholders -- the standard
   Leaflet/Slippy Map tile URL convention) and `VITE_MAP_TILE_ATTRIBUTION`
   to the attribution text that provider's terms require you to display.
3. Rebuild/restart the frontend dev server or production build --
   Vite environment variables are read at build time.

## 5. Sandbox verification note

During this phase's own live Playwright verification (run inside this
project's cloud development sandbox), the Map Explorer was configured
with the OpenStreetMap development URL above and correctly rendered
markers, clustering, the legend, and the record-count summary; the
background tile *images* themselves failed to load with
`ERR_TUNNEL_CONNECTION_FAILED` console errors. This was confirmed, via
direct network-log inspection, to be the sandbox's own network egress
proxy not allowlisting `tile.openstreetmap.org` -- not a defect in the
application's tile-loading code. A real deployment outside this
sandbox, with normal outbound HTTPS access, is expected to load tiles
normally once `VITE_MAP_TILE_URL` is set. See
`docs/implementation/history/PHASE_7_FINAL_REPORT.md` for the full
verification record.

## 6. What this does NOT do

- No bundled, hardcoded, or environment-independent default tile URL.
- No API key of any kind is ever read from, or written to, the
  backend, the database, or any response the frontend receives from
  the API -- the tile provider is a frontend-only, build-time
  configuration concern.
- No tile-proxying endpoint in the backend -- the browser requests
  tiles directly from whatever `VITE_MAP_TILE_URL` points to.
