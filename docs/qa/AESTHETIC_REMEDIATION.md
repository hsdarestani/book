# A+ Esthetic production remediation

Updated 2026-11-26. There are 71 previously successful manual checklist items reported by the owner. The current remediation tracks outstanding work and links the [patient and native repository](https://github.com/hsdarestani/a_esthetic) and its [native tracker](https://github.com/hsdarestani/a_esthetic/blob/remediation/aesthetic-20261126/docs/qa/AESTHETIC_NATIVE_REMEDIATION.md).

## Repository and release baseline

- [Book main at intake](https://github.com/hsdarestani/book/commit/84a6f34b3cf8db84c332f81da225be596f6e8ede). Work branch [remediation/aesthetic-20261126](https://github.com/hsdarestani/book/tree/remediation/aesthetic-20261126).
- [Patient main at intake](https://github.com/hsdarestani/a_esthetic/commit/6d85d20edb718ca132eb92e787c94e747a84ebae). Both work branches start from their corresponding main. Track per-batch implementation commits and PRs below.
- Existing [Book native draft #100](https://github.com/hsdarestani/book/pull/100), [staff calendar #107](https://github.com/hsdarestani/book/pull/107), and [SimplyBook writeback draft #110](https://github.com/hsdarestani/book/pull/110) are separate work. Open calendar PRs #101–107 report targeted production hotfixes missing from main. The Book production workflow resets the server checkout to main. Reconcile production source and migration history and retain rollback before releasing through that workflow.
- Latest SimplyBook branch found during intake is [audit/ariane-qa-live-pilot-20261126](https://github.com/hsdarestani/book/tree/audit/ariane-qa-live-pilot-20261126), head `32def1b`. Existing remediation candidates include [admin calendar/notifications](https://github.com/hsdarestani/book/tree/fix/admin-calendar-notifications-20261126).
- Baseline CI and live revision are pending verification. No deployment, database migration, or external write was initiated by this checkpoint.

## Bug status

| ID | Scope | Status | Evidence or exact next action |
| --- | --- | --- | --- |
| BUG-001 | SMS verification | VERIFIED | User confirmed successful SMS verification. Excluded from remediation. |
| BUG-002 | Berlin booking time, UTC instants and DST | IN_PROGRESS | Audit existing timezone fixes and compare winter/summer/DST behavior across booking, admin, native and SimplyBook. |
| BUG-003 | Treatment duration, buffer and historical reservations | TODO | Trace stored start/end and treatment duration through edits, rendering, slot search and sync. |
| BUG-004 | Ariane SimplyBook lifecycle and reconciliation | IN_PROGRESS | Read latest pilot evidence and reconcile deployed migrations and the uncertain write through read-only checks. |
| BUG-005 | Web admin calendar | TODO | Reconcile existing mobile and calendar changes with production and capture the visual baseline. |
| BUG-006 | Admin desktop viewport and content widths | TODO | Capture responsive layout baseline and audit shared container rules. |
| BUG-007 | Admin typography and spacing | TODO | Review shared page typography and accessible font sizes. |
| BUG-008 | Google Bewertungen navigation | TODO | Find and remove the navigation entry. |
| BUG-009 | Admin Session errors in referrals and campaigns | TODO | Trace existing admin bridge and route-specific session failures. |
| BUG-010 | Intake identity matching | TODO | Inspect intake_identity.py and existing normalized identity policy. |
| BUG-011 | Automatic transactional intake assignment and review | TODO | Inspect intake_forms.py, existing review reasons and duplicate prevention. |
| BUG-012 | Searchable patient selection | TODO | Inventory selectors and existing permission-protected patient search. |
| BUG-013 | Required medical history responses | TODO | Audit frontend/backend validation and supported intake entry points. |
| BUG-014 | Consolidated prior operations question | TODO | Audit rendering and versioned answers for new versus signed submissions. |
| BUG-015 | Invoice treatment options and approved billing mappings | TODO | Compare active service catalog with existing validated GOÄ configuration. |
| BUG-016 | Invoice live preview and totals | TODO | Compare recent GOÄ release behavior across preview, draft and PDF. |
| BUG-017 | Invoice draft loading and submission | TODO | Reproduce a synthetic draft against the current release and trace the failing request. |
| BUG-018 | Global visual consistency and admin contrast | TODO | Map shared styles and check recent production contrast changes. |
| BUG-019 | Hide internal SimplyBook provider in clinical selectors | TODO | Trace selectors and identify safe places to filter the internal provider. |
| BUG-020 | Calendar controls on non-calendar admin pages | TODO | Trace control ownership and route-specific rendering. |
| BUG-021 | Active sidebar state | TODO | Review navigation routes and resolved section selection. |
| BUG-022 | Intermittent admin session/authentication issues | TODO | Audit cookies, redirects, authorization and session expiry across admin sections. |
| BUG-023 | Admin form controls and alignment | TODO | Review responsive forms, buttons, inputs and dropdowns. |
| BUG-024 | Admin navigation and content organization | TODO | Map existing entry points and consolidate route grouping. |
| BUG-025 | Settings and homepage image management | TODO | Review settings hierarchy and homepage image cards and controls. |
| BUG-026 | Referrals information and points | TODO | Inventory referral status and points data already available to admins. |
| BUG-027 | German copy, date formatting and responsive consistency | TODO | Audit date displays and layout at 390, 768, 1024, 1366 and 1920 CSS pixels. |
| BUG-028 | Admin bell and communication QA | TODO | Read existing notification routes and the current fix branch before deciding scope. |
| NATIVE | Existing Swift/Android admin functionality | TODO | Inventory intended native scope and reconcile drafts and existing calendar work. |
| RELEASE | Regression, deployment, native builds and acceptance | TODO | Establish deployed baseline, then verify test, rollback and acceptance gates. |
| QAMAR | Dedicated Qamar doctor-panel QA | DEFERRED | Dedicated panel QA deferred by request. Provider isolation remains in booking regression scope. |

For TODO and IN_PROGRESS entries with no report below, root cause, relevant files, implementation SHA, PR, automated and manual results, and deployment are pending. BUG-001 verification is owner-reported. Use VERIFIED only when the appropriate evidence is recorded.

## Active batch

- BUG-002. Book main includes prior booking changes. Patient main already contains `6d85d20` for Europe/Berlin booking display. Confirm actual call sites, device-zone independence and DST behavior before editing.
- BUG-003. Book main contains `7e8e390` for calendar buffer visualization. Preserve stored historical reservation spans as evaluation moves into booking and rescheduling code.
- BUG-004. Book main contains `b338634`, `5ae80a5`, `3775185` and `84a6f34`. Inspect the reconciliation run and required field configuration. Keep unresolved writes quarantined and avoid replay. Validate with synthetic data and retain independent behavior for Qamar and other providers.

## Resume

Read both trackers first. Fetch branch heads, inspect open PRs, review relevant Actions runs and check deployed state before taking the first incomplete step above. Record root cause, files, implementation SHA and PR, automated/manual results, deployment workflow/result, remaining work and the exact next action at each checkpoint. Use synthetic QA accounts and fixtures.
