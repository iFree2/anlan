"""Trusted catalog metadata intersected with fresh, real-actor fact authorization."""

import json

import pytest
from pydantic import ValidationError

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.interfaces.service_config import ServiceConfig

OWNER = Identity(tenant_id="tenant-a", user_id="applicant")
REVIEWER = Identity(tenant_id="tenant-a", user_id="reviewer")


def metadata(tenant="tenant-a"):
    return dict(tenant_id=tenant, workers=[dict(
        worker_id=f"worker-{letter}", label=f"合成人员{letter}",
        qualification_types=[dict(qualification_type="welding", label="合成焊接资质")])
        for letter in ("a", "b", "hidden")], areas=[dict(
            area_id=f"area-{letter}", label=f"合成区域{letter}")
            for letter in ("a", "b", "hidden")])


def configuration(directory, catalogs=None):
    return ServiceConfig.model_validate(dict(
        schema_version="local-service-v1", facts_dir=directory,
        tokens=[dict(token="a" * 64, identity=OWNER, collaboration_role="applicant"),
                dict(token="b" * 64, identity=REVIEWER, collaboration_role="safety_manager")],
        **({} if catalogs is None else {"precheck_catalogs": catalogs})))


def write_access(directory, actor=OWNER, workers=("a", "b"), areas=("a", "b")):
    (directory / "access.json").write_text(json.dumps(dict(
        data_origin="SYNTHETIC", version="v1", records=[dict(
            tenant_id=actor.tenant_id, user_id=actor.user_id,
            worker_ids=[f"worker-{item}" for item in workers],
            area_ids=[f"area-{item}" for item in areas])])), encoding="utf-8")


async def test_empty_default_is_compatible_and_has_no_selection(tmp_path):
    from anlan.preflight.catalog import CatalogService

    config = configuration(tmp_path)
    assert config.precheck_catalogs == []
    write_access(tmp_path)
    view = await CatalogService(config).visible(OWNER)
    assert view.model_dump() == {"workers": [], "areas": []}


async def test_two_authorized_objects_no_facts_required_and_no_cross_tenant_leak(tmp_path):
    from anlan.preflight.catalog import CatalogService

    write_access(tmp_path)
    foreign = metadata("tenant-b")
    foreign["workers"][0]["label"] = "FOREIGN_SENTINEL"
    service = CatalogService(configuration(tmp_path, [metadata(), foreign]))
    view = await service.visible(OWNER)
    assert [w.worker_id for w in view.workers] == ["worker-a", "worker-b"]
    assert [a.area_id for a in view.areas] == ["area-a", "area-b"]
    assert "hidden" not in view.model_dump_json()
    assert "FOREIGN_SENTINEL" not in view.model_dump_json()
    # A reviewer cannot borrow the applicant's access grant.
    assert (await service.visible(REVIEWER)).workers == []
    from anlan.tools.contracts import FactReferences

    valid = FactReferences(worker_id="worker-a", qualification_type="welding", area_id="area-b")
    await service.validate(OWNER, valid)
    for changes in ({"worker_id": "worker-hidden"}, {"area_id": "area-hidden"},
                    {"qualification_type": "electrical"}):
        with pytest.raises(AccessDenied):
            await service.validate(OWNER, valid.model_copy(update=changes))
    write_access(tmp_path, workers=(), areas=())
    with pytest.raises(AccessDenied):
        await service.validate(OWNER, valid)


@pytest.mark.parametrize("contents", [None, "{", "{}", "x" * 262145],
                         ids=["missing", "malformed", "invalid", "oversized"])
async def test_unreadable_or_invalid_acl_fails_closed(tmp_path, contents):
    from anlan.preflight.catalog import CatalogService

    if contents is not None:
        (tmp_path / "access.json").write_text(contents, encoding="utf-8")
    with pytest.raises(AccessDenied):
        await CatalogService(configuration(tmp_path, [metadata()])).visible(OWNER)


@pytest.mark.parametrize("mutation", ["tenant", "worker", "area", "type", "label", "name"])
def test_catalog_config_rejects_ambiguity_and_invalid_labels(tmp_path, mutation):
    catalog = metadata()
    catalogs = [catalog]
    if mutation == "tenant":
        catalogs.append(metadata())
    elif mutation in {"worker", "area"}:
        key = "workers" if mutation == "worker" else "areas"
        catalog[key].append(catalog[key][0])
    elif mutation == "type":
        catalog["workers"][0]["qualification_types"] *= 2
    elif mutation == "label":
        catalog["areas"][0]["label"] = "   "
    else:
        catalog["workers"][0]["worker_id"] = "张师傅"
    with pytest.raises(ValidationError):
        configuration(tmp_path, catalogs)
