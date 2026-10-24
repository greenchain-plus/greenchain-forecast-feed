# Security Policy

The private RSA key exists only in the `FORECAST_SIGNING_KEY_B64` repository
secret and the owner's offline key folder. Never commit it, Android signing
keys, Firebase credentials, or payment credentials.

Clients must download the raw JSON and Base64 detached signature, verify
`SHA256withRSA` using the public key bundled with the app, require schema 1,
an approved model and healthy status, reject stale or older sequences, and
replace the local cache only after every check passes.

The Android app must not trust a public key downloaded alongside the feed.
