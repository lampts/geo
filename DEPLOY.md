# Deployment plan — publish the report at https://www.lampt.org/geo/

## How lampt.org works (verified)
- `lampt.org` is **GitHub Pages**, account **`lampts`**, custom domain set on the user
  site (`lampts/lampts.github.io`).
- Project repos serve at **`lampt.org/<repo-name>/`** — e.g. `lampts/kids` → `lampt.org/kids/`.
- ⇒ A repo named **`geo`** publishes to **`https://www.lampt.org/geo/`**. No new DNS/CNAME needed.

## Readiness review (done)
- ✅ `report/index.html` uses **relative paths** (`./css`, `./js`, `./summary.json`) → works under the `/geo/` subpath.
- ✅ **No secrets** in the repo (API keys are read from `~/.env`, which lives outside the project). Verified by scan.
- ✅ Self-contained 164 KB static bundle; Observable Plot loaded from CDN.
- ⚠️ Publishing makes the **report data public & indexable** (brand analysis, AEI, Cake numbers). That's the intent — confirm you're OK with it being world-readable.

## Decisions to confirm
1. **Repo name** = `geo` (to hit `/geo`). 
2. **Repo visibility** = public (matches your other repos; required for free Pages on a fresh repo).
3. **Scope** = whole project (pipeline + report) public, OR report-only.
4. **Deploy method** = GitHub Actions (recommended) vs `/docs` branch.

## Recommended approach — GitHub Actions publishing `report/`
Keeps `report/` as the single source of truth (the pipeline already writes there); no file
duplication. Each push rebuilds the Pages site from `report/`.

### Steps
1. **Prep the report folder**
   - add `report/.nojekyll` (skip Jekyll processing of a plain static site)
   - add a small `report/favicon.svg` + `<link rel="icon">` (kills the 404)
2. **Tidy .gitignore** — also ignore `build/` (reproducible artifacts: raw answers, audit logs) so the repo stays lean. Keep `data/`, `pipeline/`, `analysis/`, `report/`, docs.
3. **Init + first commit**
   ```bash
   git init -b main
   git add -A && git commit -m "GEO: AI brand-visibility report for Vietnamese banking"
   ```
4. **Create the public repo and push**
   ```bash
   gh repo create lampts/geo --public --source . --remote origin --push
   ```
5. **Add the Pages workflow** `.github/workflows/deploy.yml`:
   ```yaml
   name: Deploy report to Pages
   on: { push: { branches: [main], paths: ["report/**", ".github/workflows/deploy.yml"] } }
   permissions: { pages: write, id-token: write, contents: read }
   concurrency: { group: pages, cancel-in-progress: true }
   jobs:
     deploy:
       environment: { name: github-pages, url: "${{ steps.deployment.outputs.page_url }}" }
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/configure-pages@v5
         - uses: actions/upload-pages-artifact@v3
           with: { path: report }
         - id: deployment
           uses: actions/deploy-pages@v4
   ```
6. **Enable Pages = GitHub Actions** (one-time):
   ```bash
   gh api -X POST repos/lampts/geo/pages -f build_type=workflow   # or set in repo Settings → Pages
   ```
7. **Verify** (after the Action finishes, ~1–2 min): open `https://www.lampt.org/geo/`,
   confirm figures render and `summary.json` loads (200). Hard-refresh (Pages cache ~10 min).

### Notes / gotchas
- **Do NOT** add a `CNAME` file to the `geo` repo — the custom domain belongs to the user
  site; project pages inherit it automatically.
- Re-deploys: `python -m pipeline.build` (or `build_db.py` → `--export`) refreshes `report/summary.json`; `git add report && git commit && git push` triggers the workflow.
- Optional resilience: vendor Observable Plot locally (`report/vendor/plot.js`) instead of CDN.

## Simpler fallback — `/docs` branch deploy (no Actions)
If you'd rather avoid a workflow: copy `report/` → `docs/`, set Pages **source = main /docs**.
Trade-off: `docs/` duplicates `report/` (a one-line `make deploy` rsync keeps them in sync).

## Rollback
Delete the repo or disable Pages (`gh api -X DELETE repos/lampts/geo/pages`); the URL goes 404. No effect on the rest of `lampt.org`.
