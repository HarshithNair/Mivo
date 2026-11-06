# Deploying to Vercel

One Vercel project serves both halves via [Vercel Services](https://vercel.com/docs/services), configured in [`vercel.json`](../vercel.json):

| Path | Service | Source |
|---|---|---|
| `/api/*` | FastAPI (`api`) | `backend/`, entrypoint `backend/vercel_app.py` (strips `/api`) |
| everything else | Next.js (`web`) | `frontend/` |

Same domain, so the `samesite=strict` session cookie keeps working.

## Serverless differences
- **Database:** SQLite cannot persist on Vercel. Use Postgres (Neon via the Vercel Marketplace sets `DATABASE_URL`).
- **Negotiations:** functions freeze after responding, so `POST /negotiations` returns `run: true` and the browser calls `POST /negotiations/{id}/run`, which executes the negotiation inside that request (`maxDuration` 300s). The UI polls for progress. Jobs older than `NEGOTIATION_DEADLINE + 60s` are marked failed lazily.
- **Origins:** `APP_ORIGIN` defaults to the production URL; the deployment's own preview URLs are also accepted.
- **Rate limiting** is per-instance memory only — not a real limit across instances.

## First deploy
```sh
npx vercel login
npx vercel link                       # create/link the project from the repo root
npx vercel integration add neon       # or: dashboard → Storage → Neon; sets DATABASE_URL
npx vercel env add GEMINI_API_KEY production
npx vercel env add NEGOTIATION_DEADLINE production   # e.g. 270
npx vercel env pull .env.vercel --environment=production
# create tables + demo catalog in the hosted database
DATABASE_URL="$(grep ^DATABASE_URL= .env.vercel | cut -d= -f2- | tr -d '"')" .venv/bin/alembic upgrade head
DATABASE_URL="$(grep ^DATABASE_URL= .env.vercel | cut -d= -f2- | tr -d '"')" .venv/bin/python -m backend.seed
rm .env.vercel
npx vercel --prod
```
After that, connect the GitHub repo in the Vercel dashboard (Settings → Git) so pushes to `main` deploy to production and branches get previews.

Payments, World and 1inch stay disabled unless their env vars are set; see [INTEGRATIONS.md](INTEGRATIONS.md).
