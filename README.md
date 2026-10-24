# Green CHAIN+ Weekly Forecast Feed

This repository publishes the signed weekly lettuce-price forecast consumed by
the Green CHAIN+ Android application. It uses official Department of
Agriculture weekly average retail prices for NCR markets.

## Current model

- Validated damped last-week trend with fixed `alpha = 0.75`
- Green Leaf (DA label: Green Ice), Iceberg, and Romaine
- Initial validation: 42 consecutive official weeks
- Locked holdout: 8 weeks per variety
- Holdout WAPE: 9.1608%
- Holdout MASE: 0.8725

Weekly automation updates verified observations and forecast values. It does
not automatically replace the validated coefficient.

## Published endpoints

After the first successful workflow:

- Dashboard: <https://greenchain-plus.github.io/greenchain-forecast-feed/>
- JSON: <https://greenchain-plus.github.io/greenchain-forecast-feed/forecast/latest.json>
- Signature: <https://greenchain-plus.github.io/greenchain-forecast-feed/forecast/latest.sig>
- Public key: <https://greenchain-plus.github.io/greenchain-forecast-feed/forecast/forecast_public.pem>

## Automatic schedule

The workflow runs every Wednesday at 8:30 AM in `Asia/Manila`. It can also be
started through **Actions → Green CHAIN Weekly Forecast → Run workflow**.

Each run retrieves newer official DA PDFs, validates their periods and prices,
appends observations atomically, evaluates the fixed model on the latest eight
weeks, signs approved JSON with RSA/SHA-256, verifies it, and deploys Pages.

If retrieval, parsing, validation, drift monitoring, signing, or verification
fails, the last good forecast remains deployed.

## Required settings

- Pages source: **GitHub Actions**
- Workflow permissions: **Read and write permissions**
- Secret: `FORECAST_SIGNING_KEY_B64`
- Public repository

Never commit `forecast_private.pem`.

See [INSTALL_ON_MAC.md](INSTALL_ON_MAC.md) for the exact first-deployment
commands.

## Manual DA PDF recovery

Under **Actions**, run the workflow and optionally supply a complete official
`https://www.da.gov.ph/...pdf` URL. Other hosts are rejected.

## Publication gates

Publication freezes if aggregate WAPE exceeds 15%, aggregate MASE reaches 1.0,
any variety WAPE exceeds 15%, or the model stops beating the previous-week
baseline. Model replacement still requires separate validation and approval.

## Local test

```bash
python3 -m unittest discover -s tests -v
```

Live updating also needs Poppler:

```bash
brew install poppler
python3 scripts/update_weekly.py
```

This feed is an NCR retail reference, not a guaranteed farm-gate or Iligan City
quotation.
