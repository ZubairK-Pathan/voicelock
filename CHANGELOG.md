# Changelog — VoiceLock Enterprise

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Semantic Versioning.

---

## [Unreleased]

### Added
- Created `.env.example` with sanitized environment configuration template.
- Added comprehensive handoff documentation suite:
  - `AGENTS.md` (Operational instructions and safety rules for AI coding agents)
  - `PROJECT_STATUS.md` (Current milestone, verified test results, and roadmap)
  - `ARCHITECTURE.md` (Current reference and target enterprise architecture)
  - `DEVELOPMENT.md` (Local development, execution, and testing procedures)
  - `DECISIONS.md` (ADRs on credentials, statistical validity of EER, persistence, and runtime)
  - `SECURITY.md` (Threat model, challenge requirements, and secret handling rules)
  - `CHANGELOG.md` (Version tracking and audit records)

### Fixed
- Fixed `AttributeError: 'list' object has no attribute 'values'` in `tune_threshold.py` by iterating `all_embeddings` as a list rather than calling `.values()`.
- Updated `.gitignore` to prevent tracking of `firebase-credentials.json`, `.env`, and private key files.

### Security
- Isolated `firebase-credentials.json` on local filesystem and added rules preventing Git inclusion.
- Analyzed statistical bias of 0.00% EER report and retained conservative `DEFAULT_THRESHOLD = 0.25` pending multi-speaker acoustic validation.
