# Changelog

All notable changes to sift-pdf are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

---

## [0.1.1] — 2026-06-04

### Security

- **CI hardening**: Added `persist-credentials: false` on every
  `actions/checkout@v4` step (all three jobs) to prevent accidental
  credential leakage in workflow logs or forked-PR contexts.
- **CI hardening**: Added a new `security` job (blocking gate — other
  jobs now `needs: security`) that runs `bandit -ll -ii` and
  `semgrep --config p/security-audit --config p/secrets --config p/python`
  on `src/` on every push and pull-request. Baseline result: 0 bandit
  findings, 0 semgrep findings.
- **Scan confirmation**: Full semgrep (security-audit + secrets + python),
  bandit (medium/medium), and pip-audit runs against the locked dependency
  set produced zero actionable findings for sift-pdf itself. The only
  pyjwt CVEs detected by pip-audit were from the scan-tooling's own
  Python environment, not from any sift-pdf transitive dependency.

### Changed

- Bumped `version` in `pyproject.toml` and `src/sift_pdf/version.py`
  from `0.1.0` to `0.1.1` (patch; no user-visible API changes).

---

## [0.1.0] — initial release

Initial public release of sift-pdf: stateless imposition planning
solver producing `ImposePlan` outputs (T1 grid/stagger, T2 gang via
OR-Tools CP-SAT) for the Print With Synergy compile-pdf pipeline.
