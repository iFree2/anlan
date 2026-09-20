"""真实请求的生产预算入口；不提供从CLI改授权ID或重置预算的选项。"""

from anlan.budget import BudgetLedger
from anlan.postgres import database_url


async def production_ledger() -> BudgetLedger:
    ledger = BudgetLedger(database_url())
    await ledger.initialize()
    return ledger
