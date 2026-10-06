# Automatic market updates

After the one-time code deployment, daily prices do not need commits, pushes,
a running laptop, or a Render redeployment.

1. GitHub Actions runs `.github/workflows/refresh-market-data.yml` weekdays at
   **17:35 UTC** (18:35 Oslo winter / 19:35 Oslo summer), or on manual dispatch.
2. It downloads session-dated histories and audits prices/corporate actions.
3. It runs the six-horizon backtest on accepted dividend-adjusted histories.
4. It publishes `latest.json.gz` on the `market-data` GitHub release, without a
   commit. Quarantined tickers and heavy SQLite/raw archives are not published
   as usable price series. Compact audit reports are retained for 14 days in
   Actions artifacts.
5. Render checks that public release on startup and every 15 minutes while
   awake. The current snapshot is atomically replaced only after validation.

The release asset is persistent cloud storage. Render's free ephemeral disk is
only a cache; restarts recover from the release or the bundled bootstrap. No
paid Render disk/cron service is needed. No API token is exposed to the website.
The workflow uses its repository-scoped `GITHUB_TOKEN` to publish the release.

The root URL redirects to `/static/index.html`. The dashboard shows the snapshot
cutoff, expected completed session, per-ticker validation, quarantined/unavailable
counts, and the adaptive-versus-no-change backtest. Its default chart shows only
validated split-adjusted closing prices. Archived model projections have a
separate view and are not rebased or compared to current prices. Heavy neural
models are not retrained by the daily workflow.

## Failure behavior

A failed download or regression test stops publication. Fewer than 100 accepted
tickers, fewer than 80% current closing dates, or a >20% drop from the prior
published coverage also stops publication. Render retains the last good snapshot
and visibly marks outdated data. It never substitutes quarantined prices from
the legacy workbook.

GitHub schedules are best effort and can be delayed. GitHub may disable schedules
in public repositories after 60 days without repository activity; check the
workflow page if the dashboard flags stale data. Re-enable a disabled workflow
and choose **Run workflow**. This is a platform limitation, not a daily push
requirement. The first weekday run after an outage backfills history. Holidays
use the last completed XOSL session rather than fabricating a quote.

Render free services sleep when idle, so an initial visit may wait for startup.
The updater runs on GitHub whether or not Render is awake. The website fetches
the published snapshot on startup; no keep-alive requests are required.

## Operations

- Workflow: https://github.com/zillurbmb51/oslo_stocks/actions/workflows/refresh-market-data.yml
- Published data: https://github.com/zillurbmb51/oslo_stocks/releases/tag/market-data
- Health: `/healthz`
- Freshness and benchmark details: `/api/market-status?ticker=VEI`
- Optional `MARKET_DATA_URL` overrides the public release URL.
- Optional `MARKET_CACHE_FILE` overrides the disposable local cache path.

The older `run_update.sh` publishing script is no longer needed for this flow.
Disable any locally configured scheduled invocation if you previously installed
one; this deployment does not modify machine-level cron settings.

Source datasets are retrospectively adjusted provider history, not a historical
point-in-time feed. Passing arithmetic checks does not independently verify all
corporate actions. See `forecasting/DATA_REPAIR.md` for the checks and exclusions.

References:
- https://render.com/docs/free
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
