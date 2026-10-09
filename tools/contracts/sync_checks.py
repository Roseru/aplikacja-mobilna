"""Local contract checks only: never execute sync or simulate a database."""

import json

from domain_checks import check_domain


def _payload_errors(value):
    if value["payload"] is None:
        return []
    definitions = {
        "profile": "Profile", "goal": "Goal", "meal": "Meal",
        "weight": "Weight", "diary_day": "DiaryDay", "product_draft": "ProductDraft",
    }
    return check_domain(value["payload"], definitions[value["entity_type"]])


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def check_sync(value, definition):
    """Return stable semantic error codes after JSON Schema validation.

    Byte checks measure the compact fixture representation. The future HTTP
    gateway must also enforce the actual uncompressed request-body byte count.
    """
    errors = []
    definition = definition.rsplit("/", 1)[-1]
    if definition == "PushRequest":
        operations = value["operations"]
        if _size(value) > 1048576:
            errors.append("sync_batch_too_large")
        ids = [op["operation_id"] for op in operations]
        if len(ids) != len(set(ids)):
            errors.append("sync_duplicate_operation")
        entities = [(op["entity_type"], op["entity_id"]) for op in operations]
        if len(entities) != len(set(entities)):
            errors.append("sync_duplicate_entity")
        for op in operations:
            errors.extend(_payload_errors(op))
            if op["sync_epoch"] != value["sync_epoch"]:
                errors.append("sync_mixed_epochs")
            if _size(op["payload"]) > 262144:
                errors.append("sync_entity_too_large")
            recovery = op.get("recovery")
            if recovery:
                if recovery["source_epoch"] == op["sync_epoch"]:
                    errors.append("sync_recovery_same_epoch")
                if recovery["decision"] == "recreate_missing" and (
                    op["entity_id"] == recovery["source_entity_id"]
                    or op["base_revision"] is not None
                    or op["action"] != "upsert"
                ):
                    errors.append("sync_recovery_requires_new_entity")
                if recovery["decision"] == "resolve_existing" and op["base_revision"] is None:
                    errors.append("sync_recovery_requires_current_revision")
    elif definition == "PullResponse":
        for entity in value["entities"]:
            errors.extend(_payload_errors(entity))
        if sum(len(value[x]) for x in ("entities", "recovery_mappings", "operation_receipts")) > 500:
            errors.append("sync_page_too_large")
        identities = [(e["entity_type"], e["entity_id"], e["revision"]) for e in value["entities"]]
        if len(identities) != len(set(identities)):
            errors.append("sync_duplicate_change")
        mappings = [(m["source_epoch"], m["source_entity_id"]) for m in value["recovery_mappings"]]
        if len(mappings) != len(set(mappings)):
            errors.append("sync_duplicate_recovery_mapping")
    elif definition == "PushResponse":
        for result in value["results"]:
            if result.get("current") is not None:
                errors.extend(_payload_errors(result["current"]))
        ids = [r["operation_id"] for r in value["results"]]
        if len(ids) != len(set(ids)):
            errors.append("sync_duplicate_result")
    elif definition in {"Operation", "Entity"}:
        errors.extend(_payload_errors(value))
    return sorted(set(errors))


def check_scenario(value):
    """Check fixture consistency; future server results are assertions, not tests run here."""
    errors = []
    status_codes = {
        "unauthorized": 401, "forbidden": 403, "not_found": 404,
        "sync_epoch_changed": 409, "sync_reconciliation_required": 409,
        "sync_cursor_expired": 410, "snapshot_expired": 410,
        "invalid_sync_token": 422, "invalid_request": 422,
        "request_too_large": 413, "rate_limited": 429,
        "service_unavailable": 503,
    }
    for step in value["steps"]:
        if step["kind"] != "http":
            continue
        if step["account"] not in value["preconditions"]["account_ids"]:
            errors.append("scenario_unknown_account")
        endpoint = step["endpoint"].capitalize()
        errors.extend(check_sync(step["request"], endpoint + "Request"))
        if step["expected_status"] == 200:
            errors.extend(check_sync(step["response"], endpoint + "Response"))
            if endpoint == "Push":
                requested = [op["operation_id"] for op in step["request"]["operations"]]
                returned = [result["operation_id"] for result in step["response"]["results"]]
                if requested != returned:
                    errors.append("scenario_result_correspondence")
                requested_entities = [op['entity_id'] for op in step['request']['operations']]
                returned_entities = [result['entity_id'] for result in step['response']['results']]
                if requested_entities != returned_entities:
                    errors.append('scenario_entity_correspondence')
        elif status_codes.get(step["response"]["code"]) != step["expected_status"]:
            errors.append("scenario_error_status")
    return sorted(set(errors))
