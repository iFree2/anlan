"""Run `anlan demo` for JSON snapshots; `anlan chat` for local interactive input."""

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path

import httpx
import psycopg
from pydantic import ValidationError

from anlan.analysis import OfflineAnalyzer
from anlan.budget import BudgetError, BudgetLedger
from anlan.contracts import Identity
from anlan.embeddings import LocalEmbeddings
from anlan.facts import check_facts
from anlan.knowledge import KnowledgeStore
from anlan.live import production_ledger
from anlan.model import DeepSeekAnalyzer, ModelConfig
from anlan.postgres import database_url, initialize_database, postgres_service
from anlan.registry import TaskBusy
from anlan.service import AccessDenied, InvalidTransition, WorkflowService
from anlan.tool_loop import check_facts_agent
from anlan.tool_model import DeepSeekToolModel, ScriptedToolModel
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace

DEMO_FIELDS = {
    "work_location_description": "",
    "work_object_description": "SYNTHETIC：演示试件 A 接缝",
    "work_method_description": "",
    "attachment_description": "SYNTHETIC：试件 A 的位置标记示意图",
}
DEMO_PATCHES = [
    {"work_location_description": "SYNTHETIC：演示 A 区 1 号台"},
    {"work_method_description": "SYNTHETIC：电弧焊连接接缝"},
]


def show(state: dict, mode: str):
    print(json.dumps({
        "data_origin": "SYNTHETIC", "mode": state.get("analysis_mode", mode),
        "notice": "仅材料辅助核查，需安全管理人员复核；不是作业批准或合规结论。",
        **state,
    }, ensure_ascii=False))


def created_receipt(task_id: str):
    # Available even if the first analysis fails or the process exits abruptly.
    print(json.dumps({"event": "task_created", "task_id": task_id}), file=sys.stderr, flush=True)


async def run(args):
    # Local test identity is host input, not read from material or model output.
    identity = Identity(tenant_id=args.tenant, user_id=args.user)
    if args.command in {"knowledge-ingest", "knowledge-query", "knowledge-withdraw"}:
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise ValueError("知识查询时间必须带时区")
        embeddings = None if args.command == "knowledge-withdraw" \
            else await LocalEmbeddings.create()
        store = KnowledgeStore(database_url(), embeddings, clock=(lambda: as_of) if as_of else None)
        if args.command == "knowledge-ingest":
            payload = json.loads(args.knowledge_file.read_text(encoding="utf-8-sig"))
            await store.initialize()
            receipts = []
            for document in payload["documents"]:
                receipts.append(await store.ingest(identity, document))
            result = {"data_origin": "SYNTHETIC", "documents": receipts,
                      "notice": "按文档原子摄取；withdraw列表不自动执行，撤回使用显式命令。"}
        elif args.command == "knowledge-withdraw":
            result = await store.withdraw(identity, args.doc_id)
        else:
            result = await store.search(identity, {"question": args.question,
                                                   "strategy": args.strategy})
            result["clock_mode"] = "simulated" if as_of else "system_utc"
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command == "budget-status":
        print(json.dumps(await BudgetLedger(database_url()).snapshot(), ensure_ascii=False))
        return
    if args.command in {"check-facts", "check-facts-agent"}:
        # 只读核验在模型初始化之前分流，即使mode=deepseek也不读取模型配置。
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise ValueError("核验时间必须带时区")
        tools = FactTools(args.facts_dir, clock=(lambda: as_of) if as_of else None)
        trace = JsonlTrace(args.trace)
        async with AsyncExitStack() as stack:
            service = await stack.enter_async_context(
                postgres_service(database_url(), OfflineAnalyzer()))
            references = json.loads(args.refs_file.read_text(encoding="utf-8-sig"))
            if args.command == "check-facts":
                report = await check_facts(service, identity, args.task, references, tools, trace)
            else:
                # 在加载模型配置或预算之前验证归属；循环入口仍再次校验快照。
                await service.get(identity, args.task)
                model = ScriptedToolModel()
                ledger = None
                if args.mode == "deepseek":
                    config = ModelConfig.from_env()
                    ledger = await production_ledger()
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(follow_redirects=False))
                    model = DeepSeekToolModel(config, client, ledger)
                report = await check_facts_agent(
                    service, identity, args.task, references, tools, model, trace)
                if ledger is not None:
                    try:
                        report["budget_snapshot"] = await ledger.snapshot()
                    except BudgetError:
                        report["budget_snapshot"] = None
                        report["budget_warning"] = "snapshot_unavailable"
        report["clock_mode"] = "simulated" if as_of else "system_utc"
        print(json.dumps(report, ensure_ascii=False))
        return
    if args.command == "db-init":
        await initialize_database(database_url())
        await production_ledger()
        print(json.dumps({"status": "database_ready", "schema": "anlan_v2"}))
        return
    async with AsyncExitStack() as stack:
        if args.mode == "deepseek" and args.command not in ("show", "history"):
            config = ModelConfig.from_env()
            client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
            analyzer = DeepSeekAnalyzer(config, client, ledger=await production_ledger())
        else:
            analyzer = OfflineAnalyzer()
        if args.storage == "postgres":
            service = await stack.enter_async_context(postgres_service(
                database_url(), analyzer, JsonlTrace(args.trace), mode=args.mode))
        else:
            service = WorkflowService(analyzer, JsonlTrace(args.trace), mode=args.mode)
        if args.command == "show":
            show(await service.get(identity, args.task), args.mode)
            return
        if args.command == "history":
            print(json.dumps({"task_id": args.task,
                              "operations": await service.history(identity, args.task)}))
            return
        if args.command == "recover":
            show(await service.recover(identity, args.task), args.mode)
            return
        fields = json.loads(args.fields_file.read_text(encoding="utf-8-sig")) \
            if args.fields_file else DEMO_FIELDS
        if args.command == "resume":
            show(await service.resume(identity, args.task, args.revision, fields,
                                      request_id=args.request_id), args.mode)
            return
        if args.command == "chat":
            persistence = "可按 task_id 跨进程恢复。" if args.storage == "postgres" \
                else "退出会丢失内存任务。"
            print(f"仅输入合成材料。四字段 JSON；回车使用演示材料。{persistence}")
            while True:
                raw = input("申请 JSON> ").strip()
                try:
                    fields = json.loads(raw) if raw else DEMO_FIELDS
                    state = await service.start(
                        identity, fields,
                        on_created=created_receipt if args.storage == "postgres" else None)
                    break
                except (ValidationError, json.JSONDecodeError):
                    print("输入无效：仅接受四个字符串字段，每字段最多 2000 字符。")
        else:
            state = await service.start(
                identity, fields,
                on_created=created_receipt if args.storage == "postgres" else None)
        show(state, args.mode)
        if args.command == "start":
            return
        if args.command == "demo":
            for patch in DEMO_PATCHES:
                if state["status"] != "waiting_input":
                    break
                state = await service.resume(identity, state["task_id"], state["revision"], patch)
                show(state, args.mode)
            return
        while state["status"] == "waiting_input":
            raw = input("补充字段 JSON（/quit 退出）> ").strip()
            if raw == "/quit":
                break
            try:
                patch = json.loads(raw)
                state = await service.resume(identity, state["task_id"], state["revision"], patch)
                show(state, args.mode)
            except (ValidationError, json.JSONDecodeError, InvalidTransition):
                print("补充无效：请用当前四字段的非空 JSON 对象；原任务状态未修改。")


def main():
    parser = argparse.ArgumentParser(description="安澜 2.0 合成动火材料工作流")
    persistent = {"db-init", "start", "show", "resume", "recover", "history", "check-facts",
                  "check-facts-agent", "budget-status", "knowledge-ingest", "knowledge-query",
                  "knowledge-withdraw"}
    parser.add_argument("command", choices=["demo", "chat", *sorted(persistent)])
    parser.add_argument("--mode", choices=["offline", "deepseek"], default="offline")
    parser.add_argument("--trace", type=Path, default=Path(".runtime/traces.jsonl"))
    parser.add_argument("--storage", choices=["memory", "postgres"])
    parser.add_argument("--task", help="业务 task_id，不是 checkpoint thread_id")
    parser.add_argument("--revision", type=int, help="本次补充所基于的状态版本")
    parser.add_argument("--request-id", help="本次补充的稳定 ID；重试时保持相同")
    parser.add_argument("--fields-file", type=Path, help="UTF-8 合成四字段/局部补充 JSON")
    parser.add_argument("--refs-file", type=Path, help="合成人员/资质类型/区域引用JSON")
    parser.add_argument("--facts-dir", type=Path, default=Path("examples/synthetic/facts-v1"),
                        help="宿主指定的合成事实与授权目录，不来自工具参数")
    parser.add_argument("--as-of", help="带时区ISO时间；仅用于明确标注的合成时钟演示")
    parser.add_argument("--knowledge-file", type=Path,
                        default=Path("examples/synthetic/knowledge-v1/documents.json"))
    parser.add_argument("--question", help="示例知识查询问题")
    parser.add_argument("--strategy", choices=["vector", "hybrid"], default="vector")
    parser.add_argument("--doc-id", help="需要撤回的自有示例文档ID")
    parser.add_argument("--tenant", default="synthetic-demo", help="本地模拟入口身份，非生产认证")
    parser.add_argument("--user", default="safety-manager-demo", help="本地模拟入口用户")
    args = parser.parse_args()
    args.storage = args.storage or ("postgres" if args.command in persistent else "memory")
    if args.command in persistent and args.storage != "postgres":
        parser.error("持久化子命令需要 PostgreSQL；内存演示请用 demo/chat")
    if args.command in {"show", "resume", "recover", "history", "check-facts",
                        "check-facts-agent"} and not args.task:
        parser.error("需要 --task")
    if args.command == "resume" and any(value is None for value in (
        args.revision, args.request_id, args.fields_file
    )):
        parser.error("resume 需要 --revision、--request-id 和 --fields-file")
    if args.command in {"check-facts", "check-facts-agent"} and args.refs_file is None:
        parser.error("事实核验需要 --refs-file")
    if args.command == "knowledge-query" and not args.question:
        parser.error("knowledge-query需要 --question")
    if args.command == "knowledge-withdraw" and not args.doc_id:
        parser.error("knowledge-withdraw需要 --doc-id")
    try:
        # Psycopg async I/O requires a selector loop on Windows; Python 3.13 supports loop_factory.
        asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
    except (EOFError, KeyboardInterrupt):
        print("已结束会话；PostgreSQL 任务可用 show/recover 读取或续接，内存任务已结束。")
    except (AccessDenied, InvalidTransition, TaskBusy) as exc:
        parser.exit(2, f"{exc}\n")
    except BudgetError as exc:
        parser.exit(2, f"{exc}\n")
    except psycopg.Error:
        parser.exit(2, "数据库操作失败；请检查本地服务、配置和 db-init，不输出凭据。\n")
    except (OSError, json.JSONDecodeError, ValidationError):
        parser.exit(2, "无法读取或校验输入；请检查 UTF-8 JSON 和字段类型。\n")
    except ValueError:
        # Do not print a ValidationError that could include config secrets.
        if args.command.startswith("knowledge-"):
            parser.exit(2, "知识配置或本地编码器无效；检查模型缓存和带时区的 --as-of。\n")
        if args.command in {"check-facts", "check-facts-agent"}:
            parser.exit(2, "核验配置无效；请检查数据库/模型配置和带时区的 --as-of。\n")
        parser.exit(2, "配置无效；请检查 ANLAN_DATABASE_URL / DEEPSEEK_API_KEY。\n")
    except Exception:
        print("执行中断；持久化任务保留提交记录，可用 show/history/recover 排查。", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
