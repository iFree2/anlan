"""Offline dataset validator. Exit 0 means contract validity, never model quality."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from anlan.evaluation.dataset import build_manifest, validate_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.catalog.read_bytes())
        result = validate_catalog(data, source_root=ROOT)
        if not result.valid:
            print(result.model_dump_json())
            return 2
        manifest = build_manifest(data, source_root=ROOT)
        with args.output.open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(manifest.model_dump_json(indent=2) + '\n')
        print('{"valid":true,"quality":"not_evaluated","model_requests":0}')
        return 0
    except (OSError, ValueError, TypeError):
        print('{"valid":false,"errors":[{"code":"input_or_output","path":"cli"}]}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
