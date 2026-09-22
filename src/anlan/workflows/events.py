"""Pure admission and material association rules; no alarm-control capability."""


def admission(event, source, now):
    if source is None:
        return "unknown_source"
    if event.kind != source.kind:
        return "kind_mismatch"
    if event.object_ref != source.object_ref:
        return "object_mismatch"
    if event.observed_at > now:
        return "future_event"
    if event.expires_at <= now:
        return "expired_event"
    if not source.valid_from <= event.observed_at <= now < source.valid_until:
        return "source_outside_window"
    return "pending"


def material_status(source, state):
    if not state:
        return "material_unavailable"
    if (state["task_id"] != source.task_id or state["revision"] != source.revision
            or state["run_id"] != source.run_id):
        return "stale_material"
    if state["status"] not in ("waiting_input", "awaiting_review"):
        return "material_pending"
    return "linked"
