# ADR-020: Verified internal model bundles

## Status

Accepted.

## Context

Joblib uses Python pickle semantics and must not deserialize user-controlled bytes. A standalone
`model.joblib` file also lacks the feature, dataset, split and dependency context needed to reproduce
or safely use a forecast.

## Decision

- A model bundle is an internal ZIP artifact with exactly `manifest.json` and `model.joblib`.
- The manifest format is `model-bundle/v1`. Unknown fields, formats and invalid values are rejected.
- The manifest records algorithm and implementation versions, horizon, feature names/version/hash,
  training dataset version, split, commit, seed, parameters, quality/weather modes, dependency
  versions and the model payload SHA-256.
- `ArtifactService` persists an independent SHA-256 for the complete ZIP.
- Loading requires artifact purpose `model` and the bundle media type. The complete artifact checksum,
  embedded payload checksum and caller-supplied compatibility policy are checked before joblib load.
- Library compatibility uses matching major versions by default. Callers may additionally pin the
  algorithm, implementation and training dataset version.
- No API endpoint accepts a serialized model or allows an uploaded dataset artifact to be reclassified.

## Consequences

Corrupted, mislabeled, unknown and incompatible bundles fail before deserialization. Bundle loading
still assumes the application database and private artifact root are trusted administration
boundaries; checksums provide integrity, not authorship. Future migrations must keep older manifest
parsers explicit instead of treating unknown formats as the newest version.
