"""Create a new ignored local console configuration without printing credentials."""
import argparse
import asyncio
import json
from pathlib import Path

from prepare_service_demo import ROOT, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/console-demo.json")
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / ".runtime").resolve()):
        parser.error("Console credential configuration must stay inside ignored .runtime")
    result = asyncio.run(prepare(args.output, console=True), loop_factory=asyncio.SelectorEventLoop)
    result.update(console_url="http://127.0.0.1:8000/console", model_mode="scripted_double")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
