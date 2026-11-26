# A+ Esthetic production remediation

Updated 2026-11-26. There are 71 previously successful manual checklist items reported by the owner. The current remediation tracks outstanding work and links the [patient and native repository](https://github.com/hsdarestani/a_esthetic) and its [native tracker](https://github.com/hsdarestani/a_esthetic/blob/remediation/aesthetic-20261126/docs/qa/AESTHETIC_NATIVE_REMEDIATION.md).

## Repository and release baseline

- [Book main at intake](https://github.com/hsdarestani/book/commit/84a6f34b3cf8db84c332f81da225be596f6e8ede). Work branch [remediation/aesthetic-20261126](https://github.com/hsdarestani/book/tree/remediation/aesthetic-20261126).
- [Patient main at intake](https://github.com/hsdarestani/a_esthetic/commit/6d85d20edb718ca132eb92e787c94e747a84ebae). Both work branches start from their corresponding main. Track per-batch implementation commits and PRs below.
- Existing [Book native draft #100](https://github.com/hsdarestani/book/pull/100), [staff calendar #107](https://github.com/hsdarestani/book/pull/107), and [SimplyBook writeback draft #110](https://github.com/hsdarestani/book/pull/110) are separate work. Open calendar PRs #101–107 report targeted production hotfixes missing from main. The Book production workflow resets the server checkout to main. Reconcile production source and migration history and retain rollback before releasing through that workflow.
- Latest SimplyBook branch found during intake is [audit/ariane-qa-live-pilot-20261126](https://github.com/hsdarestani/book/tree/audit/ariane-qa-live-pilot-20261126), head `32def1b`. Existing remediation candidates include [admin calendar/notifications](https://github.com/hsdarestani/book/tree/fix/admin-calendar-notifications-20261126).
- Baseline [Book deploy run 45837116620](https://github.com/hsdarestani/book/actions/runs/45837116620) succeeded at `84a6f34`. Its log shows no pending migrations after checkout. Public Book health returned 200 and four public admin calendar assets matched `84a6f34` byte-for-byte. Review live environment and host-only changes before releasing.

## Bug status

| ID | Scope | Status | Evidence or exact next action |
| --- | --- | --- | --- |
| BUG-001 | SMS verification | VERIFIED | User confirmed successful SMS verification. Excluded from remediation. |
| BUG-002 | Berlin booking time, UTC instants and DST | TESTED | Synthetic patient, admin and SimplyBook timestamp regression passed. Build acceptance and production verification of the new Book revision remain open. |
| BUG-003 | Treatment duration, buffer and historical reservations | TESTED | Snapshot new local treatment minutes and preserve existing reserved spans on edits or reschedules. Confirm additive migration and live release before verification. |
| BUG-004 | Ariane SimplyBook lifecycle and reconciliation | BLOCKED | Prior synthetic write remains in review. Read-only reconciliation verified the client but found zero matching bookings. No retry was performed. |
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
| NATIVE | Existing Swift/Android admin functionality | IN_PROGRESS | Existing B65 candidate builds and native feature inventory are in the native tracker. Reconcile native and Book source candidates and run device acceptance. |
| RELEASE | Regression, deployment, native builds and acceptance | BLOCKED | Draft changes tested. Verify server-only changes, current environment and rollback before releasing. Native acceptance gates remain open. |
| QAMAR | Dedicated Qamar doctor-panel QA | DEFERRED | Dedicated panel QA deferred by request. Provider isolation remains in booking regression scope. |

For TODO and IN_PROGRESS entries with no report below, root cause, relevant files, implementation SHA, PR, automated and manual results, and deployment are pending. BUG-001 verification is owner-reported. Use VERIFIED only when the appropriate evidence is recorded.

## Phase A checkpoint

### BUG-002 · Berlin scheduling

- Confirmed code causes. Timestamp and date handling depended on Django's activated timezone and the calendar browser's current date. Offset-free DST wall times were accepted without checking for gaps or folds. Berlin wall-clock arithmetic could miscount elapsed minutes across a clock change. The original reported production record was not accessed.
- Implemented by [`b350a56`](https://github.com/hsdarestani/book/commit/b350a5655f0cfc197459ee39dfefd0ae2e942d36) on [draft PR #116](https://github.com/hsdarestani/book/pull/116). Relevant files are `booking/clinical_time.py`, `booking/services.py`, booking API and admin calendar handlers, `booking/simplybook_outbound.py`, and the browser calendar loader. Patient release smoke is tracked in [draft PR #87](https://github.com/hsdarestani/a_esthetic/pull/87) and the native tracker.
- Passed synthetic 18:30 booking round trips for CET and CEST against both admin calendar APIs, DST gap and fold tests, and mocked SimplyBook parsing. The patient web checks passed in Honolulu and Kiritimati. New Book behavior awaits deployment and signed-in synthetic smoke.

### BUG-003 · Treatment and buffer

- Confirmed code cause. Patient, web admin and native admin edit paths reconstructed an existing booking end from the current service catalog. A service edit could change the reserved span of an older appointment, including a status-only change.
- Implemented by [`f84c6fb`](https://github.com/hsdarestani/book/commit/f84c6fb93eb014aa0e61490dd56fd334b5ee1e79) in draft #116. `booking/models.py`, `booking/services.py`, web, patient and native admin handlers, and `0032_appointment_treatment_duration.py` preserve the stored span on same-service edits and snapshot the treatment minutes for new local bookings or explicit service changes. Reschedule availability uses the same span for the signed-in appointment owner. Existing records receive a nullable column without a historical backfill. The prior calendar display heuristic remains for legacy local rows whose original split is unknown. New snapshot-backed rows preserve an exact split.
- Full local Book suite passed 346 tests including Chromium. The first Book timezone code revision also passed all seven triggered PR workflows, including the [Ariane safety checks](https://github.com/hsdarestani/book/actions/runs/45843569040) and [iPhone calendar regression](https://github.com/hsdarestani/book/actions/runs/45843568936). [`b3b4732`](https://github.com/hsdarestani/book/commit/b3b473248e6f7ca846caf357ff286143d1cc37fd) adds both new regression modules to the existing PR booking workflow. Check the latest PR head before release. Django system and migration consistency checks passed locally. Live authenticated calendar smoke, PostgreSQL rollout and native device acceptance are outstanding.

### BUG-004 · SimplyBook

- Reviewed the outbound pilot, nine explicit mappings, provider 2 and migration merge `0031`. [The production deploy](https://github.com/hsdarestani/book/actions/runs/45837116620) showed the baseline checkout and no pending migrations at `84a6f34`. Current candidate includes only the outbound timestamp normalization described under BUG-002, without a new lifecycle integration.
- [Read-only audit 45836864993](https://github.com/hsdarestani/book/actions/runs/45836864993) found one synthetic local row in `review`, one matched source client with a verified link, zero same-client bookings for that day, and zero exact confirmed matches. The earlier live pilot failed. Its cause and safe no-write conclusion still require source review. The code retains its review gate. No retry, migration, flag change or remote mutation was initiated here.
- Exact next action. Reconcile the existing synthetic review row through the authorized production read-only path, confirm the required source fields and genuine submitted inputs for the applicable services, and validate a fresh synthetic create/reschedule/cancel against a suitable source QA environment. Keep Qamar and other providers outside outbound SimplyBook actions.

## Release and handoff

- Book [draft #116](https://github.com/hsdarestani/book/pull/116) and patient [draft #87](https://github.com/hsdarestani/a_esthetic/pull/87) both use `remediation/aesthetic-20261126` in their respective repositories. Patient app code revision `6d85d20` was checked live. New changes in these drafts have not deployed.
- Before Book release, compare the current host checkout and service configuration to baseline, review the additive PostgreSQL migration, and verify rollback to the current working configuration. The established main pipeline hard-resets the checkout, rewrites the environment, and runs seeding. Main also triggers the separate scheduled-source sync workflow. Review existing calendar hotfixes and preserve local settings before using it. Repeat anonymous and signed-in synthetic smokes after any approved rollout.
- Next session. Read both trackers, refresh the two PR heads and CI runs, complete that read-only Book release preflight, and pick up BUG-004 reconciliation. Continue Phase B and the other open phases with synthetic fixtures. Native artifacts, acceptance gaps, branch and next actions are in the linked native tracker.
