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

The existing mobile desktop flow remains the fallback for advanced form/file administration, invoice work, patient identity review, source-managed appointment changes and older shared blocks. A new staff build must clear release review before being offered to production personnel.

Remaining release work includes all-writer overlap checks against legacy desktop mutations, durable delivery for customer-side package reservation failures, provider and service assignment parity, and a physical-device role and gesture matrix.
