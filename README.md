# mivo.
Your AI. Your deal.

AI shopping and negotiation work in progress. The UI follows the supplied montage with a warm cream/purple/orange palette, local product illustrations and a lightweight animated orb. No pink. Demo merchants are labeled.

## Local development
Requires Node 24, Python 3.11+.

```sh
npm ci
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
npm run db:migrate
npm run db:seed
npm run api
# another terminal
npm run dev
```

Use `http://localhost:3000`; the Origin must match APP_ORIGIN. Root `.env` is ignored. Configure Gemini there for live AI. Never commit keys, tokens, databases or wallets. Seeded merchants have random inaccessible passwords; register your own merchant account to manage products.

```sh
npm test
npm run typecheck
npm run lint
npm run build
npm run test:e2e
npm run security
```

See [PROGRESS.md](PROGRESS.md) for verified status, [architecture](docs/ARCHITECTURE.md) for trust boundaries, and [integrations](docs/INTEGRATIONS.md) for external setup, [deploy](docs/DEPLOY.md) for Vercel hosting, and [device](docs/DEVICE.md) for Raspberry Pi image identification ([Pi build brief](docs/RPI_CLIENT_BRIEF.md)). Payment is intentionally disabled until deployed contracts, authorization issuance and receipt reconciliation are connected and tested. This is not a production-ready or fully integrated application yet.
