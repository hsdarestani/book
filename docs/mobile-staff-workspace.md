# Mobile staff workspace

A+ Esthetic continues to own account roles, memberships, packages, points and wallet transactions. Book owns clinical identity, availability, patient records and appointments. The two databases are independent.

The bundled client sends its existing bearer to the A+ staff API. A+ authenticates and restricts the relay to specific Book operations. Book checks the same token against A+ before looking up data. The existing clinician mapping links the verified Qamar Hameed group and specialist profile to exactly one active Book doctor. Book restricts the clinician to assigned appointments, explicitly granted patients, and scoped records. A Book patient ID is never used to debit an A+ membership.

## Appointment commands

Every bundled write has a unique key per A+ actor. Book records the command and result in the same transaction as its mutation. An identical retry returns the existing receipt. A change to the command payload requires a new key. Appointment edits also carry a revision and lock the target providers in consistent order. Public booking uses the same provider row lock. Schedule validation covers existing appointments, working intervals and blocking (calendar notes remain non-blocking).

Customer appointment records and canonical public UUIDs remain in Book. Staff cancellation commits the status and a durable credit-release row together. The reconciliation command sends the UUID through the pre-existing shared credential boundary to a new, restricted A+ endpoint. A+ permanently marks that UUID as cancelled, serializes this marker with reservations, and returns the original result on retry. Package rows and ledger entries are updated in a single transaction.

Run `manage.py reconcile_mobile_cancellations` on isolated staging first. For a future approved release, a dedicated job should run at least once per minute and alert on old pending rows and repeated failures. A successful A+ response timestamps the row. Persistent failures can be replayed by the same scheduled command without issuing a second credit. Track outbound cancellation notifications separately from credit reconciliation.

## Release order and rollback

1. Verify both additive migrations against isolated copies with synthetic data. Verify scheduler, role scoping, customer booking and patient identity mappings on PostgreSQL. Compare package ledger before and after a deliberately interrupted relay.
2. After authorization, make the A+ identity and package endpoints available before deploying Book's mobile routes and reconciler. Verify desktop and currently installed app behavior before distributing a native build.
3. Start with a small internal cohort. Monitor relay latency, authorization failures, slot conflicts, pending queue age and verification failure rates.
4. To roll back, halt native rollout and restore the previous app surface. Leave additive tables and reconciliation active until the pending queue drains. Keep existing booking, identity and credit history. A rollback across web deployment and existing native installations needs a staged rehearsal.

## Revised product requirement — complete native administration

The owner explicitly requires the mobile app to become the authoritative,
feature-complete admin console. Any desktop-only admin action is a **release
parity gap**, not an acceptable permanent mobile limitation. The existing
desktop interfaces stay operational solely as transition/rollback tools until
native parity and live-data reconciliation are proven. See
[A+ issue #83](https://github.com/hsdarestani/a_esthetic/issues/83)
and [A+ PR #81](https://github.com/hsdarestani/a_esthetic/pull/81).

**Historical blocked-time edits:** The A+ admin can now edit/delete legacy
Book blocks using the same native editor; source-imported SimplyBook calendar
notes are marked with a stable invisible ID. On an admin change, Book stores
an audited local override or deletion tombstone, and the notes importer
respects it. Editing a Book mirror does **not** update the SimplyBook
source, and this distinction must stay visible in the UI until the external
calendar is retired or upstream synchronization becomes writable and verified.

**Source-managed SimplyBook appointments:** There is not yet a verified
bidirectional mutation path. Existing rejection of native updates/cancels
remains a safety gate: do not bypass it and silently diverge the canonical
external booking from the local Book mirror. Complete safe upstream write
support or formal ownership cutover before declaring mobile appointment
parity.

A new staff build must clear full feature-parity, role and security review
on both platforms before being offered as a completed admin replacement.

Remaining release work includes all-writer overlap checks against legacy desktop mutations, durable delivery for customer-side package reservation failures, provider and service assignment parity, and a physical-device role and gesture matrix.

## November 22 hotfix reconciliation

Calendar fixes #102, #104, #105, #106 and #107 are cumulative through Book commit `ed40b65d84bfd34807f5bac7fd96e249a54bcf53`. Integrate that snapshot with the independently diverged #101 template-comment fix and #103 canonical public Sunday closure and tests. The combined regression workflow runs the complete Django suite and calendar JavaScript syntax checks. The new data migration corrects only the historical seeded returning-patient Botox setting (15 minutes + 10 buffer) to 15 minutes + 0 buffer; it never rewrites appointment times or overwrites other customized configurations.

This integration is repository-based; the exact deployed assets and production service configuration have not been independently compared. Do not run the production deployment workflow or migration without approval. The existing public Sunday guard does not prohibit authorized staff historical/manual appointment handling. Native calendar rendering and device gestures still require separate implementation and testing.
