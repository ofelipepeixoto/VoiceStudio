# Profile upload boundaries — Radar study fork

Audited base: `debpalash/VoiceStudio` commit
`4df5033e5a1a92e22936fb4d7d2d39e03cf10a91`.
This change belongs to the public `ofelipepeixoto/VoiceStudio` study fork.
The upstream history, attribution and AGPL license are preserved. No model
weights are included or relicensed by this change.

## Problem and behavior

`create_profile` read the complete reference recording into application memory.
`record_consent` likewise read the complete recording without a size bound.
Both paths bypassed the existing 128 MiB reference upload limit.

Profile creation now uses the existing chunked `_save_upload` helper. An
oversized reference returns HTTP 413 before decoding or database persistence;
the partial output is removed on failure, including cancellation.
Consent recordings read at most the existing limit plus one byte and return
HTTP 413 before database access when oversized. The existing minimum consent
size and subsequent persistence logic remain in effect.

## Reproduction and validation

From the repository root, with the project's test dependencies installed:

```sh
HF_HUB_OFFLINE=1 HF_HUB_CACHE="$(mktemp -d)" python -m pytest -q \
  tests/test_profile_upload_bounds.py tests/test_upload_suffix_sites.py
```

The three new regression tests execute the actual function ASTs with synthetic
uploads and small byte limits: rejection and partial-file cleanup for profile
creation, bounded consent reads before database access, and preservation of
bytes exactly at the writer limit. These checks import neither the application
nor model engines and make no model or service calls.

The original audited regression run reproduced both unbounded reads before the
patch and passed all three boundary tests after the patch. This PR passed 17
tests: the three boundaries, the existing upload-suffix guard and 13 changelog
style checks. Python syntax and diff checks also passed. No full-suite,
inference/GPU, browser/E2E, multipart parsing, OS matrix or deployment claim is
made by these focused checks. GitHub Actions have not been enabled in the fork.

## Limits

This is an application-level read/write limit. It does not impose a transport
body limit before multipart parsing, total disk/request quotas or a process
memory budget. Consent buffering is bounded but may still reach 128 MiB plus
one byte. Authentication, consent authenticity and voice provenance require
their own validation. No dependencies, models, release workflows or deployment
settings are changed here.
