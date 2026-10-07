"""Freeze only the retired local production ledger after verified cloud cutover."""
import asyncio
import json

from anlan.infrastructure.budget import AUTHORIZATION_ID, BudgetLedger, BudgetUnavailable
from anlan.infrastructure.db import conninfo, database_url

SQL = """
CREATE OR REPLACE FUNCTION anlan_v2.reject_archived_model_budget() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE scope text;
BEGIN
    IF TG_OP='UPDATE' AND OLD.authorization_id='20260920-long-term-v1' THEN
        RAISE EXCEPTION 'Production model budget moved to authorized cloud database';
    END IF;
    IF TG_OP='DELETE' THEN scope := OLD.authorization_id;
    ELSE scope := NEW.authorization_id;
    END IF;
    IF scope='20260920-long-term-v1' THEN
        RAISE EXCEPTION 'Production model budget moved to authorized cloud database';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
DROP TRIGGER IF EXISTS archived_model_budget_read_only ON anlan_v2.model_budget_attempts;
CREATE TRIGGER archived_model_budget_read_only
BEFORE INSERT OR UPDATE OR DELETE ON anlan_v2.model_budget_attempts
FOR EACH ROW EXECUTE FUNCTION anlan_v2.reject_archived_model_budget();
"""


async def main():
    from psycopg import AsyncConnection

    ledger = BudgetLedger(database_url())
    before = await ledger.snapshot()
    assert before["total_reserved"] == 46 and before["status_counts"]["reserved"] == 0
    async with await AsyncConnection.connect(conninfo(database_url())) as connection:
        await connection.execute(
            "SELECT authorization_id FROM anlan_v2.model_budget_authorizations "
            "WHERE authorization_id=%s FOR UPDATE", (AUTHORIZATION_ID,),
        )
        count = (await (await connection.execute(
            "SELECT count(*) FROM anlan_v2.model_budget_attempts WHERE authorization_id=%s",
            (AUTHORIZATION_ID,),
        )).fetchone())[0]
        assert count == 46
        await connection.execute(SQL, prepare=False)
    try:
        await ledger.reserve("P2-WP02", "archive-freeze-probe")
    except BudgetUnavailable:
        pass
    else:
        raise RuntimeError("Retired local budget is still writable")
    after = await ledger.snapshot()
    assert after["total_reserved"] == 46
    print(json.dumps({"status": "frozen", "historical_attempts": 46,
                      "reserve_rejected_before_http": True, "new_model_requests": 0}))


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
