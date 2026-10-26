"""Server filtering of trusted metadata using current, real-actor facts ACLs."""

import asyncio

from anlan.common.errors import AccessDenied
from anlan.preflight.contracts import ObjectCatalog
from anlan.tools.contracts import AccessData
from anlan.tools.queries import MAX_SOURCE_BYTES, read_bytes


class CatalogService:
    def __init__(self, config):
        self.config = config

    async def visible(self, actor) -> ObjectCatalog:
        if self.config.collaboration_role(actor) not in {"applicant", "safety_manager"}:
            raise AccessDenied("当前身份未启用协作角色")
        try:
            raw = await asyncio.wait_for(read_bytes(self.config.facts_dir / "access.json"), 2)
            if len(raw) > MAX_SOURCE_BYTES:
                raise ValueError("ACL exceeds size limit")
            access = AccessData.model_validate_json(raw)
        except (OSError, ValueError, TimeoutError):
            raise AccessDenied("对象目录授权源不可用") from None
        grants = [g for g in access.records
                  if (g.tenant_id, g.user_id) == (actor.tenant_id, actor.user_id)]
        workers = {key for grant in grants for key in grant.worker_ids}
        areas = {key for grant in grants for key in grant.area_ids}
        catalog = next((c for c in self.config.precheck_catalogs
                        if c.tenant_id == actor.tenant_id), None)
        return ObjectCatalog(
            workers=[w for w in catalog.workers if w.worker_id in workers] if catalog else [],
            areas=[a for a in catalog.areas if a.area_id in areas] if catalog else [])

    async def validate(self, actor, references) -> None:
        catalog = await self.visible(actor)
        if (not any(w.worker_id == references.worker_id and any(
                q.qualification_type == references.qualification_type
                for q in w.qualification_types) for w in catalog.workers)
                or not any(a.area_id == references.area_id for a in catalog.areas)):
            raise AccessDenied("对象不在当前授权目录中")
