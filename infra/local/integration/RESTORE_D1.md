# Existing Native: D1 source ports, D2 operator gate

D1 supplies code and tests on synthetic files/command boundaries. It does not
qualify a real existing lifecycle, Room27, full KO32, Google, production or release.
Native owns the later D2 window and original R2/source. Root reviews/integrates this
delivery after Native's current E4; no file is copied into that running checkout.
Even one new `integration/*.py` changes `native.source()`.

The small adapter reuses `_capture_locked` from `restore.py`; the old locked
`OwnedPG.capture` entry remains. `NativeCaptureSource` is distinct: no invented
owner marker, relocated datadir or substituted ledger installation ID. Its real
runtime generation is the capture owner, while ledger installation/stream/anchor
remain separate. Every public operation owns one nonreentrant `native.lock`.

Stop the old qualified generation **before integration**. Use a fresh configured
Python process; the external runner imports the explicit OLD checkout. It must
not be imported into a process already holding the new Native module. The receipt
and its unique stdout file are new files inside the original private source state.
The supplied binding pin is SHA256 of **raw runtime-binding.json file bytes**,
not the observer's canonical JSON binding digest.

```powershell
& $NativePython $ExternalReviewedStopRunner --checkout $OldNativeCheckout `
  --state $Source --receipt $NewOldStopReceipt `
  --expected-generation $OldGeneration --binding-file-sha256 $OldBindingFileSHA
```

This invokes old `require_running`/observer qualification and actual old `_down`
under its held lock, recording real stop exit/identities/config/epoch/HBA/physical
cluster identity. A STOPPED label alone is insufficient. Root then integrates the
reviewed source. No RUNNING source hash is relabelled. New-code binding SHA is the
canonical sorted compact UTF-8 JSON SHA of `native.source($ReviewedPin)`, held by
the reviewing controller; it is a different hash domain from the raw binding pin.

```powershell
& $NativePython -m infra.local.integration.native_existing start --state $Source `
  --handoff $NewOldStopReceipt --handoff-sha256 $OldStopSHA `
  --source-pin $ReviewedPin --source-sha256 $ReviewedSourceSHA

```

`start` only starts existing PG, or qualifies an already-live restored PG. It
returns MAINTENANCE, **not readiness or an opened issuer**. The controller must
verify actual service readiness, provider logout-all/session emptiness, issuance
and API closure, and qualified token settings. It records an independently pinned
`native-existing-auth-fence/v1` proof for that maintenance generation. Required
fields are `issuer`, `generation`, `qualified_minimum_seconds` (at least421),
`qualified_token_settings_sha256`, true `logout_all_succeeded` and
`issuance_api_503_observed`, nonempty zero `provider_user_session_counts`, and
`closed_after_logout_at`/`closed_after_logout_monotonic`. The helper measures both
real elapsed clocks after that logout/session boundary; no DB clock, epoch or
`closed_at` is rewritten. A host restart or a mismatched timer requires a new
qualification. The proof is trusted controller evidence, not a file inferred
from restored DB contents or a self-issued substitute for actual observations.

```powershell
& $NativePython -m infra.local.integration.native_existing activate --state $Source `
  --generation $MaintenanceGeneration --handoff $ActualFenceProof `
  --handoff-sha256 $ActualFenceProofSHA
```

Activation restarts the real gateway and creates another actual generation.
Actual old-token401/refresh-invalid_grant checks follow opening, **before client
admission**; they cannot be claimed from maintenance503. Root/Native keeps clients
offline until those checks pass. One bound `lifecycle` in the runtime binding
holds timer/kind/parent; no independent stale timer file exists.

After those checks, with the client offline, capture the actual returned RUNNING
generation (a MAINTENANCE generation is deliberately refused):

```powershell
& $NativePython -m infra.local.integration.native_existing capture --state $Source `
  --generation $CurrentRunningGeneration --archive $NewPairedArchive
```

Capture first qualifies the running process/config/PG/catalog, freezes one held
configuration cohort, saves exact HBA bytes before seal, stops only own API/KC,
and verifies zero other PG clients. A failed capture remains closed with failure
evidence. The resulting pinned capture handoff resumes the same source without
PG restart and restores its exact original HBA. It never installs that HBA on a
target. `stop` records actual subsequent generations; parent receipts form a
bounded chain to the selected capture, not a hardcoded two-generation story.

Stopping API/KC does not prove all other clients have left: a worker or observer
still connected makes the operation refuse and preserve its failure evidence.
Retention stays a separately coordinated Native resource; this adapter adds no
worker, scheduler, supervisor, snapshot-limit increase or session deletion.

The existing sealed `restore.py` path authenticates external checkpoint/evidence,
stages the paired payload, restores into a NEW OwnedPG and closes epoch/gates.
It never calls this lifecycle implicitly. To materialize services on that target:

```powershell
& $NativePython -m infra.local.integration.native_existing bind-target --state $Target `
  --handoff $CaptureHandoff --handoff-sha256 $CaptureSHA `
  --source-stop $PostT0SourceStop --source-stop-sha256 $PostT0SourceStopSHA `
  --restore-receipt-sha256 $PairedRestoreReceiptSHA
```

The target service state is its actual OwnedPG `state/postgres`, with two genuine
marker families. Its own `password.private` supplies only the postgres bootstrap
password; restored app/KC role credentials, sync MAC secret, issuer/CA/leaf key
come from the pinned T0 cohort. The actual catalog is
`catalog-restored/catalog`. Software is copied without data/import or writable
aliases and must match the captured software hashes. No CA signing key or photos
are copied. HBA under target maintenance allows postgres, API and KC only; no
worker starts. Native observer SQL which requires a migrator connection is not
implicitly authorized through this HBA; use the operator's existing read-only
admin witness or coordinate that distinct later access.

Use the returned target descriptor for `start`, then the same real fence protocol.
Use the latest successful `stop` receipt for a subsequent STOPPED resume; legitimate
same-epoch sync sessions are preserved. Do not delete sessions or change epochs to
satisfy an initial-restore assertion. `stop` updates real Native and OwnedPG records
and preserves its own immutable stop/stdout evidence. START_FAILED retains actual
partial markers; no successful stop/ready status is fabricated. An unqualifiable
PG PID file is explicitly reported for operator investigation, never guessed/killed.

Stop has a separate cleanup qualifier for partial/failed or unadmitted MAINTENANCE
generations. Confirmed absent own processes have UNKNOWN exits; stale markers do
not block stopping other verified own resources. A live reused PID/birth/exe
mismatch still refuses before any stop. RUNNING/admission qualification remains
strict. API/TLS/provider-only drift is recorded rather than used as launch input;
state/source/binaries/PG/bootstrap remain bound. `STOPPED_COHORT_DRIFT` is not a
resume handoff: restore the pinned cohort and obtain explicit requalification.
If PG itself was already dead, cleanup leaves its PID file intact and records
`CLEANED_UNKNOWN_EXIT`, without pg_ctl/exit0 or automatic restart authority.

Keycloak starts with schema **validation**, `initialize-empty=false` and no realm
import; application migration/provision/init/prepare is absent. These provider
options are documented in [Keycloak provider configuration](https://www.keycloak.org/server/all-provider-config)
and the [26.8 upgrading guide](https://www.keycloak.org/docs/26.8.0/upgrading/).
Actual acceptance on the installed binaries remains a D2 check.

Root's return decision is fixed: stop/isolate target and any qualified cold clone
first, then resume the never-restored source and original R2 with appropriate
auth/fence. Target-observing clients stay isolated. Original data/quota/ledger after
T0 remain; target AI stays closed. No epoch/`closed_at` rollback or336h exception.
Android recovery uses existing production ImportScreen/ViewModel under Native;
this adapter does not modify the replay driver, APK or AVD.
