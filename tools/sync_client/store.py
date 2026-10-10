"""Durable local protocol state, immutable operations and atomic page application."""

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from .wire import (
    MAX_PUSH_BYTES,
    MAX_PUSH_OPERATIONS,
    AdaptationRequired,
    adapt_source,
    digest,
    dumps,
    encode_json,
    loads,
    validate,
)


class ClientError(ValueError):
    pass


@dataclass(frozen=True)
class Context:
    scope: str
    lease_generation: int
    account_id: str
    account_generation: int
    sync_epoch: str
    context_revision: int


DDL = """
CREATE TABLE IF NOT EXISTS owners(scope TEXT PRIMARY KEY,kind TEXT NOT NULL,
 issuer TEXT,subject TEXT,UNIQUE(issuer,subject));
CREATE TABLE IF NOT EXISTS active(id INTEGER PRIMARY KEY CHECK(id=1),scope TEXT NOT NULL,
 generation INTEGER NOT NULL,FOREIGN KEY(scope) REFERENCES owners(scope));
CREATE TABLE IF NOT EXISTS bindings(scope TEXT PRIMARY KEY,account_id TEXT NOT NULL UNIQUE,
 generation INTEGER NOT NULL,epoch TEXT NOT NULL,context_revision INTEGER NOT NULL,
 requires_recovery INTEGER NOT NULL,blocked INTEGER NOT NULL DEFAULT 0,
 checkpoint TEXT,checkpoint_epoch TEXT,timeline INTEGER NOT NULL DEFAULT 0,
 FOREIGN KEY(scope) REFERENCES owners(scope));
CREATE TABLE IF NOT EXISTS guest_bindings(guest TEXT PRIMARY KEY,account TEXT NOT NULL,
 decision_id TEXT NOT NULL UNIQUE,FOREIGN KEY(guest) REFERENCES owners(scope),
 FOREIGN KEY(account) REFERENCES owners(scope));
CREATE TABLE IF NOT EXISTS originals(id TEXT PRIMARY KEY,scope TEXT NOT NULL,
 entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,action TEXT NOT NULL,
 source_json TEXT NOT NULL,source_hash TEXT NOT NULL,format_version INTEGER NOT NULL,
 FOREIGN KEY(scope) REFERENCES owners(scope));
CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,state TEXT NOT NULL DEFAULT 'pending',
 review TEXT,FOREIGN KEY(id) REFERENCES originals(id));
CREATE TABLE IF NOT EXISTS wire_ops(operation_id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,
 scope TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,epoch TEXT NOT NULL,
 wire_json TEXT NOT NULL,wire_hash TEXT NOT NULL,adapter_version INTEGER NOT NULL,
 state TEXT NOT NULL,result_json TEXT,FOREIGN KEY(draft_id) REFERENCES originals(id),
 FOREIGN KEY(scope) REFERENCES owners(scope));
CREATE TRIGGER IF NOT EXISTS immutable_wire BEFORE UPDATE OF operation_id,draft_id,scope,
 entity_type,entity_id,epoch,wire_json,wire_hash,adapter_version ON wire_ops
 BEGIN SELECT RAISE(ABORT,'immutable_wire'); END;
CREATE TRIGGER IF NOT EXISTS immutable_original BEFORE UPDATE ON originals
 BEGIN SELECT RAISE(ABORT,'immutable_original'); END;
CREATE TRIGGER IF NOT EXISTS preserve_original BEFORE DELETE ON originals
 BEGIN SELECT RAISE(ABORT,'preserve_original'); END;
CREATE TRIGGER IF NOT EXISTS preserve_wire BEFORE DELETE ON wire_ops
 BEGIN SELECT RAISE(ABORT,'preserve_wire'); END;
CREATE TABLE IF NOT EXISTS shadow(scope TEXT NOT NULL,epoch TEXT NOT NULL,
 entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,entity_json TEXT NOT NULL,
 PRIMARY KEY(scope,epoch,entity_type,entity_id));
CREATE TABLE IF NOT EXISTS shadow_history(id INTEGER PRIMARY KEY,scope TEXT NOT NULL,
 epoch TEXT NOT NULL,entity_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pull_sessions(id TEXT PRIMARY KEY,scope TEXT NOT NULL,
 context_json TEXT NOT NULL,mode TEXT NOT NULL,limit_value INTEGER NOT NULL,
 request_json TEXT NOT NULL,snapshot_token TEXT,page_token TEXT,checkpoint TEXT,
 epoch TEXT NOT NULL,timeline INTEGER,state TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pages(session_id TEXT NOT NULL,position INTEGER NOT NULL,
 request_json TEXT NOT NULL,response_json TEXT NOT NULL,
 PRIMARY KEY(session_id,position),FOREIGN KEY(session_id) REFERENCES pull_sessions(id));
CREATE TABLE IF NOT EXISTS staged_entities(session_id TEXT NOT NULL,entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,entity_json TEXT NOT NULL,PRIMARY KEY(session_id,entity_type,entity_id));
CREATE TABLE IF NOT EXISTS mappings(scope TEXT NOT NULL,source_epoch TEXT NOT NULL,
 source_entity_id TEXT NOT NULL,mapping_json TEXT NOT NULL,
 PRIMARY KEY(scope,source_epoch,source_entity_id));
CREATE TABLE IF NOT EXISTS mapping_contexts(scope TEXT NOT NULL,source_epoch TEXT NOT NULL,
 source_entity_id TEXT NOT NULL,context_json TEXT NOT NULL,
 PRIMARY KEY(scope,source_epoch,source_entity_id),
 FOREIGN KEY(scope,source_epoch,source_entity_id)
 REFERENCES mappings(scope,source_epoch,source_entity_id));
CREATE TABLE IF NOT EXISTS receipts(scope TEXT NOT NULL,operation_id TEXT NOT NULL,
 receipt_json TEXT NOT NULL,PRIMARY KEY(scope,operation_id));
CREATE TABLE IF NOT EXISTS conflicts(id INTEGER PRIMARY KEY,scope TEXT NOT NULL,
 entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,reason TEXT NOT NULL,
 local_json TEXT,server_json TEXT,resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,scope TEXT NOT NULL,
 source_epoch TEXT NOT NULL,source_entity_id TEXT NOT NULL,decision_json TEXT NOT NULL,
 operation_id TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS aliases(scope TEXT NOT NULL,source_epoch TEXT NOT NULL,
 source_entity_id TEXT NOT NULL,target_entity_id TEXT NOT NULL,
 PRIMARY KEY(scope,source_epoch,source_entity_id));
"""


class SyncStore:
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(DDL)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def register(self, *, issuer=None, subject=None):
        if (issuer is None) != (subject is None):
            raise ClientError("identity_required")
        with self.transaction() as db:
            if issuer:
                old = db.execute(
                    "SELECT scope FROM owners WHERE issuer=? AND subject=?", (issuer, subject)
                ).fetchone()
                if old:
                    return old[0]
            scope = str(uuid4())
            db.execute(
                "INSERT INTO owners VALUES(?,?,?,?)",
                (scope, "account" if issuer else "guest", issuer, subject),
            )
            return scope

    def select(self, scope):
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM owners WHERE scope=?", (scope,)).fetchone():
                raise ClientError("unknown_scope")
            db.execute(
                "INSERT INTO active VALUES(1,?,1) ON CONFLICT(id) DO UPDATE "
                "SET scope=excluded.scope,generation=active.generation+1",
                (scope,),
            )

    def bootstrap(self, scope, response, *, lease_generation):
        from calorie_app.modules.profiles.schemas import Bootstrap

        Bootstrap.model_validate(response)
        with self.transaction() as db:
            active = db.execute("SELECT * FROM active WHERE id=1").fetchone()
            if active is None or (active["scope"], active["generation"]) != (
                scope,
                lease_generation,
            ):
                raise ClientError("stale_context")
            owner = db.execute("SELECT kind FROM owners WHERE scope=?", (scope,)).fetchone()
            if owner[0] != "account":
                raise ClientError("account_required")
            old = db.execute("SELECT * FROM bindings WHERE scope=?", (scope,)).fetchone()
            if old and (
                old["account_id"] != response["account_id"]
                or (
                    old["epoch"] == response["sync_epoch"]
                    and old["generation"] > response["account_generation"]
                )
            ):
                raise ClientError("bootstrap_conflict")
            changed = bool(
                old
                and (
                    old["epoch"] != response["sync_epoch"]
                    or old["generation"] != response["account_generation"]
                )
            )
            if old:
                db.execute(
                    "UPDATE bindings SET generation=?,epoch=?,context_revision=?,"
                    "requires_recovery=?,checkpoint=? WHERE scope=?",
                    (
                        response["account_generation"],
                        response["sync_epoch"],
                        old["context_revision"] + int(changed),
                        old["requires_recovery"] or changed,
                        None if changed else old["checkpoint"],
                        scope,
                    ),
                )
            else:
                db.execute(
                    "INSERT INTO bindings(scope,account_id,generation,epoch,"
                    "context_revision,requires_recovery) VALUES(?,?,?,?,1,0)",
                    (
                        scope,
                        response["account_id"],
                        response["account_generation"],
                        response["sync_epoch"],
                    ),
                )

    def capture(self):
        active = self.db.execute("SELECT * FROM active WHERE id=1").fetchone()
        if not active:
            raise ClientError("account_required")
        binding = self.db.execute(
            "SELECT * FROM bindings WHERE scope=?", (active["scope"],)
        ).fetchone()
        if not binding:
            raise ClientError("bootstrap_required")
        return Context(
            active["scope"],
            active["generation"],
            binding["account_id"],
            binding["generation"],
            binding["epoch"],
            binding["context_revision"],
        )

    def _check(self, context, *, reconciliation=False):
        if self.capture() != context:
            raise ClientError("stale_context")
        row = self.db.execute("SELECT * FROM bindings WHERE scope=?", (context.scope,)).fetchone()
        if row["blocked"]:
            raise ClientError("account_deleting")
        if row["requires_recovery"] and not reconciliation:
            raise ClientError("recovery_required")
        return row

    def bind_guest(self, guest, context, *, confirmed):
        if not confirmed:
            raise ClientError("explicit_confirmation_required")
        with self.transaction() as db:
            self._check(context, reconciliation=True)
            owner = db.execute("SELECT kind FROM owners WHERE scope=?", (guest,)).fetchone()
            if not owner or owner[0] != "guest":
                raise ClientError("guest_required")
            old = db.execute(
                "SELECT account FROM guest_bindings WHERE guest=?", (guest,)
            ).fetchone()
            if old and old[0] != context.scope:
                raise ClientError("guest_already_bound")
            if not old:
                db.execute(
                    "INSERT INTO guest_bindings VALUES(?,?,?)", (guest, context.scope, str(uuid4()))
                )

    def import_source(
        self, scope, entity_type, entity_id, action, raw_json, *, source_id=None, format_version=1
    ):
        if action not in ("create", "update", "upsert", "delete"):
            raise ClientError("invalid_source_action")
        loads(raw_json)  # Validate but preserve exact original bytes/whitespace.
        source_id = source_id or str(uuid4())
        with self.transaction() as db:
            db.execute(
                "INSERT INTO originals VALUES(?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    scope,
                    entity_type,
                    entity_id,
                    action,
                    raw_json,
                    hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
                    format_version,
                ),
            )
            db.execute("INSERT INTO drafts(id) VALUES(?)", (source_id,))
        return source_id

    def _owns_source(self, context, scope):
        if context.scope == scope:
            return
        row = self.db.execute(
            "SELECT account FROM guest_bindings WHERE guest=?", (scope,)
        ).fetchone()
        if not row or row[0] != context.scope:
            raise ClientError("foreign_source")

    def materialize(self, context, source_id, **options):
        try:
            return self._materialize(context, source_id, **options)
        except AdaptationRequired as error:
            self.mark_review(source_id, str(error))
            raise

    def _materialize(
        self,
        context,
        source_id,
        *,
        metadata=None,
        reviewed_payload=None,
        recovery=None,
        confirmed=False,
        target_id=None,
    ):
        """Freeze wire once; a later source edit is a separate original/draft."""
        with self.transaction() as db:
            binding = self._check(context, reconciliation=recovery is not None)
            if not binding["checkpoint"] or binding["checkpoint_epoch"] != context.sync_epoch:
                raise ClientError("completed_snapshot_required")
            source = db.execute("SELECT * FROM originals WHERE id=?", (source_id,)).fetchone()
            if not source:
                raise ClientError("unknown_source")
            self._owns_source(context, source["scope"])
            existing = db.execute(
                "SELECT wire_json FROM wire_ops WHERE draft_id=?", (source_id,)
            ).fetchone()
            if existing and recovery is None:
                if metadata or reviewed_payload is not None or recovery or target_id:
                    raise ClientError("immutable_wire")
                return loads(existing[0])
            entity_id = target_id or source["entity_id"]
            pending = db.execute(
                "SELECT 1 FROM wire_ops WHERE scope=? AND entity_type=? "
                "AND entity_id=? AND state NOT IN "
                "('accepted','already_applied','resolved','preserved')",
                (context.scope, source["entity_type"], entity_id),
            ).fetchone()
            if pending:
                raise ClientError("predecessor_unresolved")
            action = "delete" if source["action"] == "delete" else "upsert"
            shadow = db.execute(
                "SELECT entity_json FROM shadow WHERE scope=? AND epoch=? "
                "AND entity_type=? AND entity_id=?",
                (context.scope, context.sync_epoch, source["entity_type"], entity_id),
            ).fetchone()
            current = loads(shadow[0]) if shadow else None
            base = current["revision"] if current and not current["deleted"] else None
            # ACK advances base even before the post-push pull; replay revision is original.
            ack = db.execute(
                "SELECT result_json FROM wire_ops WHERE scope=? AND epoch=? "
                "AND entity_type=? AND entity_id=? AND state IN "
                "('accepted','already_applied') ORDER BY rowid DESC LIMIT 1",
                (context.scope, context.sync_epoch, source["entity_type"], entity_id),
            ).fetchone()
            if ack:
                base = max(base or 0, loads(ack[0])["revision"])
            if current and current["deleted"] and not recovery:
                raise ClientError("entity_deleted_review")
            if (
                not recovery
                and db.execute(
                    "SELECT 1 FROM conflicts WHERE scope=? AND entity_type=? AND entity_id=? "
                    "AND reason='absent_same_epoch' AND resolved=0",
                    (context.scope, source["entity_type"], entity_id),
                ).fetchone()
            ):
                raise ClientError("entity_deleted_review")
            if source["action"] in ("update", "delete") and base is None and not recovery:
                raise ClientError("server_revision_required")
            if recovery:
                validate(recovery, "RecoverySource")
                if not confirmed or recovery["source_epoch"] == context.sync_epoch:
                    raise ClientError("explicit_epoch_recovery_required")
                if recovery["source_entity_id"] != source["entity_id"]:
                    raise ClientError("recovery_source_mismatch")
                if action != "upsert":
                    raise ClientError("recovery_upsert_required")
                self._check_recovery_source(db, context, source, recovery)
                if recovery["decision"] == "recreate_missing":
                    if entity_id == source["entity_id"] or base is not None or action != "upsert":
                        raise ClientError("new_uuid_required")
                elif base is None:
                    raise ClientError("existing_revision_required")
            try:
                payload = (
                    None
                    if action == "delete"
                    else adapt_source(
                        source["entity_type"],
                        reviewed_payload
                        if reviewed_payload is not None
                        else loads(source["source_json"]),
                        metadata=metadata,
                    )
                )
            except (ValueError, KeyError) as error:
                # Persist review outside the failed materialization transaction below.
                raise AdaptationRequired(str(error)) from error
            if reviewed_payload is not None and not confirmed:
                raise ClientError("explicit_confirmation_required")
            if target_id and not recovery and not confirmed:
                raise ClientError("explicit_confirmation_required")
            if payload and source["entity_type"] in ("profile", "diary_day") and base is None:
                for row in db.execute(
                    "SELECT entity_json FROM shadow WHERE scope=? AND epoch=? AND entity_type=?",
                    (context.scope, context.sync_epoch, source["entity_type"]),
                ):
                    canonical = loads(row[0])
                    if not canonical["deleted"] and (
                        source["entity_type"] == "profile"
                        or canonical["payload"]["local_date"] == payload["local_date"]
                    ):
                        raise ClientError("natural_key_review_required")
            if len(dumps(payload).encode("utf-8")) > 262144:
                raise ClientError("payload_too_large")
            if payload and source["entity_type"] == "goal":
                mapped_replay = recovery and self._mapped_goal_recovery(
                    db, context, recovery, payload
                )
                if payload["timeline_base_revision"] != binding["timeline"] and not mapped_replay:
                    raise ClientError("timeline_review_required")
            if payload and source["entity_type"] == "meal" and payload["goal_id"]:
                goal = db.execute(
                    "SELECT entity_json FROM shadow WHERE scope=? AND epoch=? "
                    "AND entity_type='goal' AND entity_id=?",
                    (context.scope, context.sync_epoch, payload["goal_id"]),
                ).fetchone()
                if not goal or loads(goal[0])["deleted"]:
                    raise ClientError("goal_not_confirmed")
            operation = {
                "operation_id": str(uuid4()) if recovery else source_id,
                "entity_type": source["entity_type"],
                "entity_id": entity_id,
                "action": action,
                "base_revision": base,
                "sync_epoch": context.sync_epoch,
                "payload": payload,
            }
            if recovery:
                operation["recovery"] = recovery
            validate(operation, "Operation")
            db.execute(
                "INSERT INTO wire_ops VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    operation["operation_id"],
                    source_id,
                    context.scope,
                    source["entity_type"],
                    entity_id,
                    context.sync_epoch,
                    dumps(operation),
                    digest(operation),
                    1,
                    "queued",
                    None,
                ),
            )
            db.execute(
                "UPDATE drafts SET state='materialized',review=NULL WHERE id=?", (source_id,)
            )
            if recovery:
                db.execute(
                    "INSERT INTO decisions VALUES(?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        context.scope,
                        recovery["source_epoch"],
                        recovery["source_entity_id"],
                        dumps(recovery),
                        operation["operation_id"],
                    ),
                )
            return operation

    def mark_review(self, source_id, reason):
        with self.transaction() as db:
            db.execute("UPDATE drafts SET review=? WHERE id=?", (reason, source_id))

    def _check_recovery_source(self, db, context, source, recovery):
        """Known local/server evidence must agree; absence is left for the server."""
        operation_id = recovery["source_operation_id"]
        if operation_id is None:
            return
        wire = db.execute("SELECT * FROM wire_ops WHERE operation_id=?", (operation_id,)).fetchone()
        if wire and (
            wire["scope"] != context.scope
            or wire["entity_type"] != source["entity_type"]
            or wire["entity_id"] != source["entity_id"]
            or wire["epoch"] != recovery["source_epoch"]
            or loads(wire["wire_json"])["action"] != "upsert"
        ):
            raise ClientError("recovery_source_mismatch")
        if wire and wire["result_json"]:
            result = loads(wire["result_json"])
            if result["status"] not in ("accepted", "already_applied") or (
                recovery["source_revision"] is not None
                and result["revision"] != recovery["source_revision"]
            ):
                raise ClientError("recovery_source_mismatch")
        receipt = db.execute(
            "SELECT receipt_json FROM receipts WHERE scope=? AND operation_id=?",
            (context.scope, operation_id),
        ).fetchone()
        if receipt:
            record = loads(receipt[0])
            if (
                record["source_epoch"] != recovery["source_epoch"]
                or record["entity_id"] != source["entity_id"]
                or record["status"] != "accepted"
                or (
                    recovery["source_revision"] is not None
                    and record["revision"] != recovery["source_revision"]
                )
            ):
                raise ClientError("recovery_source_mismatch")

    def _mapped_goal_recovery(self, db, context, recovery, payload):
        """Only a confirmed mapping and identical canonical target bypass the new-decision axis."""
        row = db.execute(
            "SELECT m.mapping_json,c.context_json FROM mappings m "
            "LEFT JOIN mapping_contexts c USING(scope,source_epoch,source_entity_id) "
            "WHERE m.scope=? AND m.source_epoch=? AND m.source_entity_id=?",
            (context.scope, recovery["source_epoch"], recovery["source_entity_id"]),
        ).fetchone()
        if row is None:
            return False
        if row["context_json"] != dumps(asdict(context)):
            raise ClientError("recovery_mapping_context_required")
        mapping = loads(row["mapping_json"])
        targets = db.execute(
            "SELECT entity_type,entity_json FROM shadow WHERE scope=? AND epoch=? AND entity_id=?",
            (context.scope, context.sync_epoch, mapping["target_entity_id"]),
        ).fetchall()
        if len(targets) != 1 or targets[0]["entity_type"] != "goal":
            raise ClientError("recovery_target_conflict")
        target = loads(targets[0]["entity_json"])
        if (
            target["entity_type"] != "goal"
            or target["entity_id"] != mapping["target_entity_id"]
            or target["deleted"]
            or target["revision"] != mapping["target_revision"]
        ):
            raise ClientError("recovery_target_conflict")
        if dumps(target["payload"]) != dumps(payload):
            raise ClientError("recovery_content_conflict")
        return True

    def prepare_push(self, context, *, recovery_only=False, limit=100):
        if type(limit) is not int or limit < 1:
            raise ClientError("invalid_limit")
        with self.transaction() as db:
            binding = self._check(context, reconciliation=recovery_only)
            rows = db.execute(
                "SELECT * FROM wire_ops WHERE scope=? AND epoch=? AND state "
                "IN ('queued','sent') ORDER BY rowid",
                (context.scope, context.sync_epoch),
            )
            operations = []
            body = {
                "protocol_version": 1,
                "sync_epoch": context.sync_epoch,
                "checkpoint": binding["checkpoint"],
                "operations": operations,
            }
            size = len(encode_json(body))
            seen = set()
            for row in rows:
                operation = loads(row["wire_json"])
                if recovery_only and "recovery" not in operation:
                    continue
                key = row["entity_type"], row["entity_id"]
                if key in seen:
                    # Keep a contiguous eligible prefix: later operations may depend
                    # on this entity's second edit, which belongs in the next batch.
                    break
                addition = len(encode_json(operation)) + int(bool(operations))
                if size + addition > MAX_PUSH_BYTES:
                    if not operations:
                        raise ClientError("operation_too_large")
                    break
                seen.add(key)
                operations.append(operation)
                size += addition
                if len(operations) >= min(limit, MAX_PUSH_OPERATIONS):
                    break
            if not operations:
                raise ClientError("no_operations")
            validate(body, "PushRequest")
            if len(encode_json(body)) > MAX_PUSH_BYTES:
                raise ClientError("batch_too_large")
            for operation in operations:
                db.execute(
                    "UPDATE wire_ops SET state='sent' WHERE operation_id=?",
                    (operation["operation_id"],),
                )
            return body

    def apply_push(self, context, request, response):
        validate(response, "PushResponse")
        with self.transaction() as db:
            self._check(context, reconciliation=True)
            if response["sync_epoch"] != context.sync_epoch:
                raise ClientError("response_epoch_mismatch")
            results = response["results"]
            if len(results) != len(request["operations"]):
                raise ClientError("incomplete_ack")
            for operation, result in zip(request["operations"], results, strict=True):
                if (result["operation_id"], result["entity_id"]) != (
                    operation["operation_id"],
                    operation["entity_id"],
                ):
                    raise ClientError("ack_order_mismatch")
                row = db.execute(
                    "SELECT * FROM wire_ops WHERE operation_id=?", (operation["operation_id"],)
                ).fetchone()
                if (
                    not row
                    or row["scope"] != context.scope
                    or row["wire_hash"] != digest(operation)
                ):
                    raise ClientError("immutable_wire_mismatch")
                if row["result_json"] and loads(row["result_json"]) != result:
                    # accepted may replay as already_applied, with the same original revision.
                    old = loads(row["result_json"])
                    if (
                        old["status"] not in ("accepted", "already_applied")
                        or result["status"] not in ("accepted", "already_applied")
                        or old["revision"] != result["revision"]
                    ):
                        raise ClientError("ack_changed")
                db.execute(
                    "UPDATE wire_ops SET state=?,result_json=? WHERE operation_id=?",
                    (result["status"], dumps(result), operation["operation_id"]),
                )
                mapping = result["recovery_mapping"]
                if mapping:
                    self._mapping(db, context.scope, mapping, context=context)
                if result["status"] in ("conflict", "rejected"):
                    db.execute(
                        "INSERT INTO conflicts(scope,entity_type,entity_id,reason,"
                        "local_json,server_json) VALUES(?,?,?,?,?,?)",
                        (
                            context.scope,
                            operation["entity_type"],
                            operation["entity_id"],
                            result["code"],
                            row["wire_json"],
                            dumps(result["current"]),
                        ),
                    )

    def start_pull(self, context, *, full=False, limit=500, recovery_ids=None):
        if not 1 <= limit <= 500:
            raise ClientError("invalid_limit")
        with self.transaction() as db:
            binding = self._check(context, reconciliation=True)
            if binding["requires_recovery"] and not full:
                raise ClientError("full_snapshot_required")
            request = {"sync_epoch": context.sync_epoch, "limit": limit}
            mode = "snapshot" if full or not binding["checkpoint"] else "incremental"
            if mode == "incremental":
                request["checkpoint"] = binding["checkpoint"]
            elif recovery_ids:
                request["recovery_operation_ids"] = recovery_ids
            validate(request, "PullRequest")
            session_id = str(uuid4())
            db.execute(
                "INSERT INTO pull_sessions(id,scope,context_json,mode,limit_value,"
                "request_json,epoch,state) VALUES(?,?,?,?,?,?,?,'active')",
                (
                    session_id,
                    context.scope,
                    dumps(asdict(context)),
                    mode,
                    limit,
                    dumps(request),
                    context.sync_epoch,
                ),
            )
            return session_id

    def prepare_pull(self, context, session_id):
        self._check(context, reconciliation=True)
        session = self.db.execute(
            "SELECT * FROM pull_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not session or session["context_json"] != dumps(asdict(context)):
            raise ClientError("stale_context")
        if session["state"] != "active":
            raise ClientError("session_complete")
        return loads(session["request_json"])

    def _mapping(self, db, scope, mapping, *, context=None):
        key = (scope, mapping["source_epoch"], mapping["source_entity_id"])
        old = db.execute(
            "SELECT mapping_json FROM mappings WHERE scope=? AND source_epoch=? "
            "AND source_entity_id=?",
            key,
        ).fetchone()
        if old and loads(old[0])["target_entity_id"] != mapping["target_entity_id"]:
            raise ClientError("mapping_target_changed")
        db.execute(
            "INSERT INTO mappings VALUES(?,?,?,?) ON CONFLICT DO UPDATE "
            "SET mapping_json=excluded.mapping_json",
            (*key, dumps(mapping)),
        )
        db.execute(
            "INSERT INTO aliases VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
            (*key, mapping["target_entity_id"]),
        )
        if context is not None:
            db.execute(
                "INSERT INTO mapping_contexts VALUES(?,?,?,?) ON CONFLICT DO UPDATE "
                "SET context_json=excluded.context_json",
                (*key, dumps(asdict(context))),
            )

    def apply_pull(self, context, session_id, request, response):
        validate(response, "PullResponse")
        with self.transaction() as db:
            self._check(context, reconciliation=True)
            session = db.execute("SELECT * FROM pull_sessions WHERE id=?", (session_id,)).fetchone()
            if not session or session["context_json"] != dumps(asdict(context)):
                raise ClientError("stale_context")
            previous = db.execute(
                "SELECT response_json FROM pages WHERE session_id=? AND request_json=?",
                (session_id, dumps(request)),
            ).fetchone()
            if previous:
                if loads(previous[0]) != response:
                    raise ClientError("page_replay_changed")
                return response["page_token"] is None
            if session["state"] != "active" or loads(session["request_json"]) != request:
                raise ClientError("page_request_mismatch")
            if response["sync_epoch"] != context.sync_epoch or response["mode"] != session["mode"]:
                raise ClientError("response_context_mismatch")
            if (
                session["timeline"] is not None
                and session["timeline"] != response["goal_timeline_revision"]
            ):
                raise ClientError("snapshot_metadata_changed")
            if (
                session["snapshot_token"]
                and session["snapshot_token"] != response["snapshot_token"]
            ):
                raise ClientError("snapshot_token_changed")
            count = sum(
                len(response[key])
                for key in ("entities", "recovery_mappings", "operation_receipts")
            )
            if count > session["limit_value"]:
                raise ClientError("page_limit_exceeded")
            db.execute(
                "INSERT INTO pages VALUES(?,?,?,?)",
                (session_id, session["position"], dumps(request), dumps(response)),
            )
            for entity in response["entities"]:
                db.execute(
                    "INSERT INTO staged_entities VALUES(?,?,?,?) ON CONFLICT DO UPDATE "
                    "SET entity_json=excluded.entity_json",
                    (session_id, entity["entity_type"], entity["entity_id"], dumps(entity)),
                )
            # Mapping/receipts stage in immutable pages, never published before final page.
            next_request = {"sync_epoch": context.sync_epoch, "limit": session["limit_value"]}
            if response["page_token"]:
                next_request["page_token"] = response["page_token"]
                if session["mode"] == "snapshot":
                    next_request["snapshot_token"] = response["snapshot_token"]
                else:
                    next_request["checkpoint"] = request["checkpoint"]
            complete = response["page_token"] is None
            db.execute(
                "UPDATE pull_sessions SET request_json=?,snapshot_token=?,page_token=?,"
                "checkpoint=?,timeline=?,state=?,position=position+1 WHERE id=?",
                (
                    dumps(next_request),
                    response["snapshot_token"],
                    response["page_token"],
                    response["checkpoint"],
                    response["goal_timeline_revision"],
                    "complete" if complete else "active",
                    session_id,
                ),
            )
            if complete:
                self._activate(db, context, session_id, session["mode"], response)
            return complete

    def _activate(self, db, context, session_id, mode, response):
        if mode == "snapshot":
            # Keep both revisions/content across restore; absence is only deletion in same epoch.
            db.execute(
                "INSERT INTO shadow_history(scope,epoch,entity_json) SELECT scope,epoch,"
                "entity_json FROM shadow WHERE scope=?",
                (context.scope,),
            )
            missing = db.execute(
                "SELECT entity_type,entity_id,entity_json FROM shadow WHERE "
                "scope=? AND epoch=? AND NOT EXISTS(SELECT 1 FROM staged_entities s "
                "WHERE s.session_id=? AND s.entity_type=shadow.entity_type "
                "AND s.entity_id=shadow.entity_id)",
                (context.scope, context.sync_epoch, session_id),
            ).fetchall()
            for old in missing:
                db.execute(
                    "INSERT INTO conflicts(scope,entity_type,entity_id,reason,server_json) "
                    "VALUES(?,?,?,?,?)",
                    (context.scope, old[0], old[1], "absent_same_epoch", old[2]),
                )
            db.execute(
                "DELETE FROM shadow WHERE scope=? AND epoch=?", (context.scope, context.sync_epoch)
            )
        for row in db.execute("SELECT * FROM staged_entities WHERE session_id=?", (session_id,)):
            db.execute(
                "INSERT INTO shadow VALUES(?,?,?,?,?) ON CONFLICT DO UPDATE "
                "SET entity_json=excluded.entity_json",
                (
                    context.scope,
                    context.sync_epoch,
                    row["entity_type"],
                    row["entity_id"],
                    row["entity_json"],
                ),
            )
        for row in db.execute(
            "SELECT response_json FROM pages WHERE session_id=? ORDER BY position", (session_id,)
        ):
            page = loads(row[0])
            for mapping in page["recovery_mappings"]:
                self._mapping(db, context.scope, mapping, context=context)
            for receipt in page["operation_receipts"]:
                db.execute(
                    "INSERT INTO receipts VALUES(?,?,?) ON CONFLICT DO UPDATE "
                    "SET receipt_json=excluded.receipt_json",
                    (context.scope, receipt["operation_id"], dumps(receipt)),
                )
        db.execute(
            "UPDATE bindings SET checkpoint=?,checkpoint_epoch=?,timeline=? WHERE scope=?",
            (
                response["checkpoint"],
                context.sync_epoch,
                response["goal_timeline_revision"],
                context.scope,
            ),
        )

    def handle_error(self, context, code):
        with self.transaction() as db:
            self._check(context, reconciliation=True)
            if code == "account_deleting":
                db.execute("UPDATE bindings SET blocked=1 WHERE scope=?", (context.scope,))
            elif code in (
                "sync_epoch_changed",
                "account_generation_changed",
                "sync_reconciliation_required",
                "sync_cursor_expired",
            ):
                db.execute(
                    "UPDATE bindings SET requires_recovery=1,checkpoint=NULL WHERE scope=?",
                    (context.scope,),
                )

    def finish_reconciliation(self, context, *, confirmed):
        if not confirmed:
            raise ClientError("explicit_confirmation_required")
        with self.transaction() as db:
            binding = self._check(context, reconciliation=True)
            if not binding["checkpoint"] or binding["checkpoint_epoch"] != context.sync_epoch:
                raise ClientError("completed_snapshot_required")
            unresolved = db.execute(
                "SELECT 1 FROM wire_ops WHERE scope=? AND epoch<>? AND state IN ('queued','sent')",
                (context.scope, context.sync_epoch),
            ).fetchone()
            if unresolved:
                raise ClientError("old_outbox_needs_decision")
            if db.execute(
                "SELECT 1 FROM wire_ops WHERE scope=? AND epoch=? AND state IN "
                "('queued','sent','conflict','rejected') AND wire_json LIKE '%\"recovery\"%'",
                (context.scope, context.sync_epoch),
            ).fetchone():
                raise ClientError("recovery_operations_unresolved")
            db.execute("UPDATE bindings SET requires_recovery=0 WHERE scope=?", (context.scope,))

    def retire_old_operation(self, context, operation_id, *, confirmed):
        """User acknowledges preservation of old evidence; no stale operation is resent."""
        if not confirmed:
            raise ClientError("explicit_confirmation_required")
        with self.transaction() as db:
            self._check(context, reconciliation=True)
            row = db.execute(
                "SELECT * FROM wire_ops WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if not row or row["scope"] != context.scope or row["epoch"] == context.sync_epoch:
                raise ClientError("old_epoch_operation_required")
            db.execute(
                "UPDATE wire_ops SET state='preserved' WHERE operation_id=?", (operation_id,)
            )

    def resolve_conflict(self, context, operation_id, *, confirmed):
        """Permit a new reviewed draft/operation while retaining both prior versions."""
        if not confirmed:
            raise ClientError("explicit_confirmation_required")
        with self.transaction() as db:
            self._check(context, reconciliation=True)
            row = db.execute(
                "SELECT * FROM wire_ops WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if (
                not row
                or row["scope"] != context.scope
                or row["state"] not in ("conflict", "rejected")
            ):
                raise ClientError("conflict_required")
            db.execute("UPDATE wire_ops SET state='resolved' WHERE operation_id=?", (operation_id,))
            db.execute(
                "UPDATE conflicts SET resolved=1 WHERE scope=? AND entity_type=? AND entity_id=?",
                (context.scope, row["entity_type"], row["entity_id"]),
            )

    def remap_new_references(self, context, payload, source_epoch):
        """Copy new source for reviewed materialization; immutable wire remains untouched."""
        self._check(context, reconciliation=True)
        result = loads(dumps(payload))
        for field in ("goal_id", "correction_of"):
            source = result.get(field)
            if source is not None:
                row = self.db.execute(
                    "SELECT target_entity_id FROM aliases WHERE scope=? AND source_epoch=? "
                    "AND source_entity_id=?",
                    (context.scope, source_epoch, source),
                ).fetchone()
                if row:
                    result[field] = row[0]
        return result
