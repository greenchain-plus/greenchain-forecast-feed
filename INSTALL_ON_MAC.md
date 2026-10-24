# First Deployment from macOS

## 1. Download and extract

Download `GreenChain_ForecastFeed_v1.0.0.zip` into **Downloads** and extract
it. Use the normal macOS Terminal for the remaining steps.

## 2. Merge it into the existing repository

```bash
cd "$HOME/Downloads"
git clone https://github.com/greenchain-plus/greenchain-forecast-feed.git
rsync -av "GreenChain_ForecastFeed_v1.0.0/" "greenchain-forecast-feed/"
cd "greenchain-forecast-feed"
git status
```

Do not add `--delete` to the `rsync` command.

The status must not show `forecast_private.pem`, `.env`, Android signing
keys, or wallet credentials.

## 3. Commit and push

```bash
git add .
git commit -m "Add automated Green CHAIN weekly forecast feed"
git push origin main
```

Complete the GitHub authentication prompt if one appears. Never paste the
forecast private key into Terminal.

## 4. Monitor the first deployment

Open the repository's **Actions** tab, select **Green CHAIN Weekly Forecast**,
and wait for the push-triggered run. If it does not start, select
**Run workflow**.

Confirm that the update, tests, signature verification, and deployment pass.

## 5. Verify

Open:

```text
https://greenchain-plus.github.io/greenchain-forecast-feed/
https://greenchain-plus.github.io/greenchain-forecast-feed/forecast/latest.json
```

The dashboard should say **Forecast healthy** and **Signature verified**. A
first Pages deployment can take several minutes.

The expected public-key fingerprint is:

```text
6b32c6b62e4c687dbbfd93b0aec7e9167289a2bacbb60e74eeefb44d8b5b76b1
```

If no new DA report exists, that is a successful condition and the last signed
forecast is retained. If the DA document format changes, the workflow stops
before publication.
