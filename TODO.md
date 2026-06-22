# TODO

- [x] Patch `app/data_loader.py` to make `load_model_commentaries()` resilient: wrap each `pd.read_csv()` in try/except (FileNotFoundError/Exception), log, and continue so startup never fails if one TSV is missing.

- [ ] (Optional) Add startup guard in `app/main.py` to avoid full crash if any loader fails.
- [x] Update UI header text in `static/index.html` to list latest model names used in predictions.

- [ ] Rebuild/redeploy and verify the service boots.
- [ ] Verify `/api/tickers` and `/api/commentary/{ticker}` return FinGPT1 + other available comments.
