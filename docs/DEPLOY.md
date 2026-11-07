# Deploying MatchLens for free

Everything here stays on free tiers. The only usage-limited part is the LLM (Groq's free
tier), which stops working at its limits rather than charging you, and the app falls back
to non-AI results when it does.

| Part | Host | Free-tier facts that matter |
| --- | --- | --- |
| Database | [Neon](https://neon.com) | Suspends after 5 idle minutes; pgvector included |
| API (FastAPI, Docker) | [Render](https://render.com) | 512 MB RAM (MatchLens peaks around 300 MB); sleeps after 15 idle minutes, about a minute to wake |
| Web app (Next.js) | [Vercel](https://vercel.com) Hobby | Repo must be under your personal GitHub account (it is) |
| Daily job import | GitHub Actions | Free for public repos |
| LLM | Groq free tier | 1,000 requests/day and 8,000 tokens/minute per model |

Allow about 30 minutes. Do the steps in order, because each one needs a value from the
previous one.

## 1. Database: Neon

1. Sign up at neon.com and create a project. Pick the region **AWS US West 2 (Oregon)**, to
   match the Render region in `render.yaml`.
2. Open **Connect** and copy the connection string with **connection pooling turned off**
   (the *direct* string, host without `-pooler`). It looks like
   `postgresql://user:password@ep-....us-west-2.aws.neon.tech/neondb?sslmode=require`.
   Paste it as-is: MatchLens converts `sslmode` for its database driver.

Don't create tables by hand. The API applies migrations when it starts, including
`CREATE EXTENSION vector`.

## 2. API: Render

1. Sign up at render.com with your GitHub account.
2. **New → Blueprint**, select the `Match-Lens` repository. Render reads `render.yaml` and
   asks for the secret values:
   - `DATABASE_URL`: the Neon direct connection string from step 1.
   - `LLM_API_KEY`: your Groq key (the same one as `GROQ_API_KEY` in your `.env`).
   - `CORS_ORIGINS`: leave as `http://localhost:3100` for now; set it in step 5.
   - `CORS_ORIGIN_REGEX`: leave empty.
3. Create it. The first build takes about 5 minutes. When it's live, copy the service URL,
   e.g. `https://matchlens-api.onrender.com`, and check `https://<that URL>/health`.

## 3. Jobs: run the import

1. In GitHub: **Settings → Secrets and variables → Actions → New repository secret**, named
   `DATABASE_URL`, with the same Neon direct connection string.
2. **Actions → Ingest jobs → Run workflow**. The first run embeds about 1,500 jobs and takes
   about 5 minutes; after that it runs daily at 06:17 UTC on its own.
3. Check `https://<render URL>/status/pipeline`: `active_jobs` should be in the thousands.

GitHub pauses scheduled workflows after 60 days without repository activity; any commit
re-enables them.

## 4. Web app: Vercel

1. Sign up at vercel.com with your GitHub account. **Add New → Project**, import
   `Match-Lens`.
2. Set **Root Directory** to `frontend` (Vercel detects Next.js).
3. Add the environment variable `NEXT_PUBLIC_API_URL` = your Render URL (no trailing
   slash).
4. Deploy, then copy the production URL, e.g. `https://match-lens.vercel.app`.

## 5. Connect the two

In Render → `matchlens-api` → **Environment**:

- `CORS_ORIGINS` = the Vercel production URL. Several URLs are allowed, comma-separated.
- Optional, so Vercel preview deployments work too: `CORS_ORIGIN_REGEX` =
  `https://match-lens(-[a-z0-9-]+)?\.vercel\.app` (adjust to your project name).

Saving restarts the API.

## 6. Check it (the Phase 7 exit check)

Wait at least 15 minutes so the API is asleep, then on your phone:

1. Open the Vercel URL. A "Waking up the server" note should appear and clear within about
   a minute.
2. **Try a sample**: the profile, matches and an ATS check should all work.
3. Upload your own resume and repeat.

`/status` shows the API, the database and the latest job import.

## Day-to-day

- **Deploys:** pushing to `main` redeploys both Render (API) and Vercel (web).
- **Rate limits:** each IP gets 10 uploads, 30 sample loads, 40 match lists and 30 ATS
  checks per hour, set via the `RATE_LIMIT_*` variables. The shared sample resume and its
  matches are cached, so most demo visits make no LLM calls at all.
- **Switching LLM:** change `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` in Render.
- **Never set `EVAL_TOOLS` in production:** it exposes the local labeling endpoints.
