# Multi-stage build: compile the Vite app, then serve the static output with an
# unprivileged nginx (non-root, listens on 8080). No Node runtime in the final image.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Public, non-secret build-time settings (see frontend/.env.example). Empty = no map tiles are loaded.
ARG VITE_MAP_TILE_URL=
ARG VITE_MAP_TILE_ATTRIBUTION=
ENV VITE_MAP_TILE_URL=$VITE_MAP_TILE_URL VITE_MAP_TILE_ATTRIBUTION=$VITE_MAP_TILE_ATTRIBUTION
RUN npm run build
# Fill the CSP's map tile origin from the same VITE_MAP_TILE_URL (fails on an invalid URL).
RUN node deploy/render-nginx.mjs nginx.conf /app/nginx.rendered.conf

FROM nginxinc/nginx-unprivileged:1.27-alpine AS final
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/nginx.rendered.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
