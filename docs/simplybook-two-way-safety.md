# SimplyBook two-way writeback — staged, fail-closed

## In this branch
- Imported SimplyBook appointments: reschedule and cancel; admin role only.
- Source-first via authenticated SimplyBook Admin API (editBook / cancelBooking). Both preflight and read-back required.
- Reject stale Book data, wrong patient/source ID, mismatched service or missing credential.
- Fail closed for paid/invoiced/promo bookings, source-specific locations and intake fields; SimplyBook API details may not expose invoice IDs, so `price` is checked explicitly.
- Preserve original SimplyBook event/unit/client IDs. Never use generic imported Book staff ID as remote unit ID.
- Fail closed when SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED is absent or false.
- Existing SimplyBook -> Book ten-minute importer remains authoritative.

## Release gates
1. Pass isolated Book and native Android/iOS CI.
2. Reconcile both old native draft branches with latest main; never force merge old features.
3. Perform controlled synthetic LIVE write-back test in SimplyBook: move dummy appointment, read back, cancel, read back, observe subsequent import; ensure no real-patient messages.
4. Enable production SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED=true only when step 3 passes.
5. Monitor source status and conflict rejection; no blind retry on ambiguous external responses.
6. Submit actual signed App Store and Google Play builds only using Publisher credentials after production is proven.

## Deliberately not enabled
- Remote creation, patient / provider / service reassignment, source calendar notes, blocks, working hours, service changes, patient profile writes.
- These need independent source-ID mapping and per-operation verification.
- SimplyBook source appointments must never be edited only in Book, and source blocks must never be edited in Book while its importer may overwrite them.

Current: isolated implementation and synthetic mocked CI; no live source mutations, no production flag, no store submission.
