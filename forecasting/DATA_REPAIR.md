# Session history repair and corporate-action audit

The validated history is a **separate provider snapshot**, not a patch to the
legacy workbook/quote CSV. Combining retrospectively adjusted history with raw
last-price quotes would introduce artificial returns. Neither original is
modified by this pipeline.

## Run

```sh
python -m pip install -r forecasting/requirements-repair.txt
python forecasting/repair_history.py --as-of 2026-10-06
```

By default this covers 2020-01-01 through the last completed Oslo exchange
session, for the workbook's ticker universe, with four download workers. Use
`--start`, `--tickers VEI,EQNR`, and `--workers` to change scope. The 30-minute
post-close buffer avoids ingesting an unfinished current-day daily candle.

The command prints the snapshot directory. Resume interrupted downloads with
`--resume data/history_repair/<snapshot>` and identical arguments; source hashes
and parameters must match. Successful cached downloads are checksummed and
reused. Failed symbols are retried once. A new run creates a separate snapshot;
there is no automatic overwriting, ticker-renaming guess, forward fill, weekday
interpolation, or price-jump-based split correction.

Each snapshot includes:

- `raw/`: provider-returned daily bars and metadata, with retrieval time and SHA-256.
- `prices.csv`: only series passing checks; separate `close` and `adjusted_close`.
- `coverage.csv`: acceptance/quarantine/download failure, recovered dates, and remaining gaps.
- `gaps.csv`: each missing legacy ticker/session and whether it was recovered.
- `actions.csv`: dividend/split events and the adjustment consistency result.
- `issues.csv`: invalid/non-session rows, action mismatches, large adjusted returns and identity failures.
- `legacy_disagreements.csv`: overlapping prices differing by over 1% from both provider bases.
- `manifest.json`: source hashes, price checksum, versions, cutoff and limitations.

`remaining_missing` / `unresolved_sessions` count unavailable sessions in the
validated snapshot, **including all excluded observations for quarantined or
unavailable tickers**. They are not a count of gaps in the original workbook.
Missing dates before/after trading availability can be IPO/delisting/suspension
issues; no assumption that every ticker traded on every exchange session is made.

## Price basis and validation

The downloader uses Yahoo Finance via yfinance with `auto_adjust=False`,
`back_adjust=False`, `repair=False`, and `actions=True`. The raw snapshot is the
library-returned data (including any library-level currency conversion), not
an assertion that it is an unprocessed exchange feed. Its heuristic `repair`
option is deliberately disabled.

Yahoo's `Close` is on a split-adjusted share basis. `Adj Close` also incorporates
provider dividend adjustments. Neither should be silently stitched onto a
legacy unadjusted close. Split factors must **not** be applied again to already
adjusted history. Adjusted prices are a research/return series, not historical
executable share prices.

Checks include:

1. Expected `.OL` symbol, Oslo exchange, equity instrument and NOK currency.
2. Unique, completed XOSL session dates and finite positive prices.
3. No fabricated prices at missing dates.
4. Dividend factor identity on consecutive sessions: with `factor = Adj Close /
   Close`, `factor_today / factor_previous` should approximately equal
   `1 / (1 - dividend / previous_close)`. A discrepancy over 0.5% blocks the
   ticker. This assumes prices and cash dividends are on a consistent currency
   and share basis; an inconsistency is flagged, never silently converted.
5. A split accompanied by a close jump consistent with an unadjusted split is
   blocked. No automatic split multiplication is performed.
6. Adjusted one-session returns above 40% in absolute magnitude are review
   flags, not proof of an error; the entire ticker is conservatively excluded.
7. Known complex events in `data/corporate_action_references.json` are blocked
   until a supported economic adjustment is verified. The current KOG entry
   documents the 23 April 2026 demerger and its issuer/Euronext source.

`provider_consistent` means these checks passed. It **does not** mean every
corporate action has been independently verified against issuer notices. The
checks cannot detect an unreported action that is also absent from both close
series. Special dividends, currency errors, rights issues, spin-offs and ticker
changes may need separate exchange/issuer evidence. Do not remove quarantine
just because a price curve looks smoother.

## Backtest the snapshot explicitly

Replace `<snapshot>` with the directory printed by the downloader:

```sh
python forecasting/walk_forward_backtest.py \
  --as-of 2026-10-06 \
  --history-file data/history_repair/<snapshot>/prices.csv \
  --price-basis adjusted_close \
  --archive data/history_repair/<snapshot>/backtest.sqlite \
  --output-dir data/history_repair/<snapshot>/backtest
python forecasting/report_backtest.py \
  --output-dir data/history_repair/<snapshot>/backtest
```

The loader verifies the checksum and rejects quarantined, duplicate or invalid
rows. `--price-basis close` is available for a separate split-adjusted price
experiment. Default legacy runs remain explicit in their metadata as
`legacy_unverified`; no live website model is silently switched.

The adjusted snapshot may change historical scales after a later distribution
or split. Its outcomes therefore are **not used to resolve another snapshot's
pending forecasts or legacy raw-price forecasts**. Rerunning creates a separate
experiment with the input checksum and price basis. This remains a retrospective
backtest, not a point-in-time corporate-action database. Comparisons across the
old 195-ticker sample and the accepted subset are not apples-to-apples; assess
models against no-change within the same new sample.

## Daily quote updater

`app/update_actual_prices.py` now requires an explicit **Closing Price DateTime**
and a valid completed exchange session. It no longer stamps an undated last
price with the download date. Rejections are logged in
`data/quote_refresh_audit.json`; if no row has a verified closing date the updater
fails without changing `oslo_actual_prices.csv`. The Euronext endpoint currently
omits this field, so use the history-repair command for dated data. Historical
misdated rows are kept in the original source for audit, not included in the
validated snapshot.

`run_update.sh` stops on refresh failure rather than continuing to commit/push.
No scheduler was created or changed and that publishing script was not run.

## Verification

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
```

Tests cover completed-session cutoffs, no forward fill, dividend identities,
no double split adjustment, quarantine, checksums, explicit quote timestamps,
leakage-safe weighting, and isolation of archive price bases.

Sources:

- https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html
- https://github.com/ranaroussi/yfinance/blob/main/doc/source/advanced/price_repair.rst
- https://live.euronext.com/en/products/equities/company-news/2026-04-21-kongsberg-gruppen-asa-key-information-regarding-demerger
