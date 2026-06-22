# Deploying ForgeIQ (free, provider-independent)

The strategy: **data lives in Supabase** (permanent free Postgres) and the
**web app runs on Render** (free). Because the database is independent of the
host, you can later move the app to Railway/Fly without migrating data — just
reuse the same `DATABASE_URL`.

```
  Supabase (Postgres)  ◄── DATABASE_URL ──  Render web service (FastAPI)
        ▲                                            │
        └─────────── same URL works from Railway later ──────────┘
```

## 1. Create the database (Supabase)

1. Go to **supabase.com** → **New project**. Pick a region near India
   (e.g. Mumbai / Singapore). Set a database password.
2. Once provisioned: **Project Settings → Database → Connection string → URI**.
   - Use the **Session pooler** (or the direct connection) string — not the
     transaction pooler — because the app runs its own connection pool.
   - It looks like:
     `postgresql://postgres.xxxx:[PASSWORD]@aws-0-...pooler.supabase.com:5432/postgres`
3. Copy that string — it's your `DATABASE_URL`. You do **not** need to run any
   SQL: the app creates its schema on first boot.

## 2. Deploy the web app (Render)

1. Go to **render.com** → **New → Blueprint** → connect your GitHub repo
   `adityash1138/Forgeiq`, branch `claude/wizardly-albattani-cmkxin`.
2. Render reads `render.yaml` and creates the `forgeiq-api` web service.
3. In the service's **Environment** tab, set:
   - `DATABASE_URL` → the Supabase string from step 1.
   - (optional) `ANTHROPIC_API_KEY` → enables full AI Copilot + LLM entity
     resolution. Leave blank to run Copilot in fallback mode.
   - `ADMIN_API_KEY` and `SECRET_KEY` are auto-generated — open the
     Environment tab to read the admin key (you'll need it for `/admin`).
4. Deploy. On first boot the app applies the schema, seeds config + demo data,
   and serves. Watch the logs for `[init_db] {...}`.

## 3. Open it

- Render gives you a URL like `https://forgeiq-api.onrender.com`.
- `/`            → vendor dashboard. Demo key: `fiq_demo_key_2026`
- `/onboarding`  → vendor signup
- `/admin`       → founder console (use the generated `ADMIN_API_KEY`)
- `/marketplace` → buyer RFQ portal
- `/buyer`       → free benchmark
- `/health`      → status + DB check

After confirming it works, set `FORGEIQ_SEED_DEMO=0` and redeploy so demo data
isn't re-seeded on every restart.

## Notes & caveats

- **Free web sleeps when idle** → first request after ~15 min is slow (cold
  start ~30s). Fine for demos; upgrade to a paid instance for always-on.
- **The scraper worker** (`scheduler/scheduler.py`, the `worker` in `Procfile`)
  needs an always-on process, which free tiers don't provide. The web app +
  demo data work fully without it; add the worker when you go paid.

## Switching to Railway later (no data migration)

1. On **railway.app**: **New Project → Deploy from GitHub repo** → same repo.
   Railway auto-detects `railway.toml` + `Dockerfile`.
2. In **Variables**, set the **same** `DATABASE_URL` (your Supabase string),
   plus `ANTHROPIC_API_KEY` / `ADMIN_API_KEY` / `SECRET_KEY`.
3. Generate a domain. Done — same database, zero data movement.

If you ever DO want to move the data too (e.g. off Supabase), it's one command:
```bash
pg_dump "$OLD_DATABASE_URL" | psql "$NEW_DATABASE_URL"
```
