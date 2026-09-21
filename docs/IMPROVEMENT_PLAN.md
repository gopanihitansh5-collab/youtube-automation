# Repository improvement plan

This is the rolling inventory for the 3-hour maintenance cycle. Each cycle
should finish one bounded item, verify it, and update this list rather than
repeatedly polishing one file.

## Current priorities

- [x] Make upload failures fail the workflow instead of producing a false green run.
- [x] Repair long-form thumbnail context handling and add regression tests.
- [ ] Separate the long-form pipeline orchestration in `main_long.py` into testable stages.
- [ ] Add fast unit tests for topic selection, script normalization, and upload error paths.
- [ ] Add lint/type-check configuration and run it in a lightweight CI job.
- [ ] Consolidate duplicated short-form and long-form YouTube credential/service setup.
- [ ] Audit external downloads and API calls for timeouts, status checks, and stable URLs.
- [ ] Document long-form local runs, outputs, resumption behavior, and OAuth scope limits.
- [ ] Review dependency pins and remove unused imports and dead helpers.
- [ ] Expand comment-pinning OAuth scope only after explicit user approval.

## Coverage rotation

1. Correctness and failure truthfulness
2. Tests and static checks
3. Structure and duplication
4. Performance and workflow cost
5. Security and dependency hygiene
6. Documentation and operator experience
