# Android Integration Handoff

The Android rebuild will use:

```text
Feed URL:
https://greenchain-plus.github.io/greenchain-forecast-feed/forecast/latest.json

Signature URL:
https://greenchain-plus.github.io/greenchain-forecast-feed/forecast/latest.sig

Pinned public-key fingerprint:
6b32c6b62e4c687dbbfd93b0aec7e9167289a2bacbb60e74eeefb44d8b5b76b1
```

The app must bundle `keys/forecast_public.pem`; it must not trust a key
downloaded from the forecast site.

Before replacing the local cache, the client must:

1. Download the raw JSON bytes and detached Base64 signature.
2. Verify `SHA256withRSA` using the bundled public key.
3. Require `schema_version == 1`.
4. Require model release status `APPROVED`.
5. Require production health `HEALTHY`.
6. Require all three prediction objects.
7. Reject a sequence number older than the cached sequence.
8. Reject a feed beyond `forecast_period.stale_after`.
9. Atomically replace the cache only after every check passes.

The last verified local forecast remains visible when network retrieval or any
validation step fails.
