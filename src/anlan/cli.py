"""Run `anlan demo` for JSON snapshots; `anlan chat` for local interactive input."""

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from pydantic import ValidationError

from anlan.analysis import OfflineAnalyzer
from anlan.contracts import Identity
from anlan.model import DeepSeekAnalyzer, ModelConfig
from anlan.service import InvalidTransition, WorkflowService
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
        "data_origin": "SYNTHETIC", "mode": mode,
        "notice": "仅材料辅助核查，需安全管理人员复核；不是作业批准或合规结论。",
        **state,
    }, ensure_ascii=False))


async def run(args):
    identity = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
    async with AsyncExitStack() as stack:
        if args.mode == "deepseek":
            config = ModelConfig.from_env()
            client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
            analyzer = DeepSeekAnalyzer(config, client)
        else:
            analyzer = OfflineAnalyzer()
        service = WorkflowService(analyzer, JsonlTrace(args.trace))
        fields = DEMO_FIELDS
        if args.command == "chat":
            print("仅输入合成材料。四字段 JSON；回车使用演示材料。退出会丢失内存任务。")
            while True:
                raw = input("申请 JSON> ").strip()
                try:
                    fields = json.loads(raw) if raw else DEMO_FIELDS
                    state = await service.start(identity, fields)
                    break
                except (ValidationError, json.JSONDecodeError):
                    print("输入无效：仅接受四个字符串字段，每字段最多 2000 字符。")
        else:
            state = await service.start(identity, fields)
        show(state, args.mode)
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
    parser.add_argument("command", choices=["demo", "chat"])
    parser.add_argument("--mode", choices=["offline", "deepseek"], default="offline")
    parser.add_argument("--trace", type=Path, default=Path(".runtime/traces.jsonl"))
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (EOFError, KeyboardInterrupt):
        print("已结束本地会话；当前版本退出后不能恢复。")
    except ValueError:
        # Do not print a ValidationError that could include config secrets.
        parser.exit(2, "配置无效或缺少 DEEPSEEK_API_KEY；不会发送请求。\n")


if __name__ == "__main__":
    main()
