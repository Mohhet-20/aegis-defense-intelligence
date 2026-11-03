# Public demo -- free hosting

The root `Dockerfile` builds **one container** with the React frontend, the FastAPI backend, the real
detector's weights and the COCO evaluation sample. On every start it creates a fresh SQLite database,
seeds the shared demo accounts, loads the demo walkthrough, runs the real detector on three CC BY
photos and evaluates it on 200 photos (about a minute), then serves everything on one port. Every
`DEMO_RESET_HOURS` (default 6) it starts over on a fresh database.

Use it to **show** the project. For real use, deploy with `docker-compose.yml` (PostgreSQL, nginx,
persistent volumes): [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md).

## What demo mode does

| | |
|---|---|
| Sign-in page | One-click buttons for administrator, analyst, investigator and viewer (from `GET /api/v1/demo`) |
| Shared accounts | Cannot be locked out by failed logins; their password, role, status and sessions cannot be changed (HTTP 403). Visitors can create their own users and change those freely |
| Data | Synthetic only; wiped and rebuilt on every start and every `DEMO_RESET_HOURS` |
| Security | Same as production: Secure HttpOnly cookies, CSP, `ENVIRONMENT=production` start-up checks. The signing key is generated per start unless `SECRET_KEY` is set |
| Rate limits | Per visitor address read from `X-Forwarded-For` (`TRUSTED_PROXY_HOPS` entries from the right); login limit 30/minute |
| API docs | On (`/api/docs`) so reviewers can browse the API |

Never set `DEMO_MODE=true` on a deployment with real data: it publishes the demo password on the
sign-in page. `scripts/demo_server.py` also refuses anything but a SQLite file it may delete.

## Option A -- Hugging Face Spaces (recommended)

Free CPU Space (2 vCPU, 16 GB RAM), HTTPS, no credit card. It sleeps after 48 hours without visitors
and wakes on the next visit.

1. Push the repository to GitHub first ([`GITHUB_PUBLICATION.md`](GITHUB_PUBLICATION.md)), so the Space
   can link to the code.
2. On <https://huggingface.co/new-space>: choose a name (e.g. `aegis`), **SDK: Docker → Blank**,
   hardware **CPU basic (free)**, visibility **Public**. Create it.
3. On your machine, from the repository root:

   ```bash
   pip install -U huggingface_hub
   hf auth login                     # paste a token with WRITE access (huggingface.co/settings/tokens)
   python scripts/export_hf_space.py ../aegis-space --github-url https://github.com/<you>/<repo>
   hf upload <hf-user>/aegis ../aegis-space . --repo-type space
   ```

   The export contains only committed files: no `.env`, database, weights or `node_modules`.
4. The Space builds the image (about 10 minutes the first time; watch **Logs → Build**). When the
   container log shows `[demo] ready on port 7860`, open `https://<hf-user>-aegis.hf.space`.
5. Optional: **Settings → Variables and secrets → New secret** `SECRET_KEY` (any 48+ random characters)
   keeps visitors signed in across restarts.

Use the direct `*.hf.space` address when sharing. Inside the Space page's frame the browser treats the
session cookie as third-party, so reloading there signs you out (one click to sign in again).

To update the Space later: commit, export to an empty folder again and repeat the `hf upload`.

## Option B -- Render (free web service)

512 MB RAM; sleeps after about 15 idle minutes, and the first visit after that takes 1-2 minutes
(container start plus demo data).

1. Push the repository to GitHub.
2. Render dashboard → **New → Blueprint** → connect the repository. Render reads [`render.yaml`](../../render.yaml)
   (Docker, free plan, health check, generated `SECRET_KEY`).
3. After the build, open the `https://aegis-demo-XXXX.onrender.com` address it shows.

## Option C -- any machine with Docker

```bash
docker build -t aegis-demo .
docker run --rm -p 7860:7860 aegis-demo
```

Open <http://localhost:7860>. Useful variables: `DEMO_RESET_HOURS` (0 = never), `SECRET_KEY`, `PORT`.
Build arguments: `FETCH_EVAL_DATA=0` leaves out the COCO sample (the detector still works; the
real-photo evaluation is then unavailable), `VITE_MAP_TILE_URL=` (empty) disables map tiles.

## After it is live

- Put the link at the top of `README.md` (there is a commented placeholder) and on your GitHub
  repository's **About → Website**.
- Check it from a private browser window: sign in as each role, open **Computer vision → Inference
  Jobs** (the real-photo jobs show their boxes) and **Model Evaluation** (the COCO result).

## Third-party content in the image

The detector weights are Apache-2.0. The 200 COCO photos are each under a Creative Commons or
public-domain licence, recorded with their Flickr URL in `manifest.json` inside the image. The three
photos shown to visitors are CC BY and credited by their COCO id in the file name. Map tiles come from
OpenStreetMap's public servers, which are fine for a low-traffic demo under the
[OSMF tile usage policy](https://operations.osmfoundation.org/policies/tiles/) and are credited on the
map. For heavier traffic, point `VITE_MAP_TILE_URL` at another provider.

## Verification

Verified on Windows 11 by running the demo server with the image's exact settings outside Docker:
fresh-start sequence, one-click sign-in, the 76-route browser walk for administrator and viewer, the
HTML CSP and framing headers, API precedence over the frontend fallback, and the real-detector showcase
(mAP@0.5 0.461). **The Docker image itself has not been built here** (no Docker); the CI `containers` job
builds it and starts it on every push.
