"""Validate public candidate metadata or replay an explicitly licensed local sample.

No network or publication action is offered. Run from the installed anlan environment.
"""

import argparse
import json
from pathlib import Path

from anlan.knowledge.sources.contracts import SourceManifest
from anlan.knowledge.sources.validation import MAX_BYTES, replay


def read_bounded(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError('input must be a regular non-symlink file')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('input exceeds byte limit')
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'replay'])
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--source-id')
    parser.add_argument('--file')
    args = parser.parse_args()
    try:
        manifest = SourceManifest.model_validate_json(read_bounded(args.manifest, 262144))
        if args.action == 'validate':
            result = {'manifest_version': manifest.manifest_version,
                      'sources': len(manifest.sources), 'state': 'candidate'}
        else:
            if not args.source_id or not args.file:
                raise ValueError('replay requires --source-id and --file')
            relative = Path(args.file)
            if relative.is_absolute() or relative.drive or any(p == '..' for p in relative.parts):
                raise ValueError('sample path must stay below manifest directory')
            base = args.manifest.resolve().parent
            target = base / relative
            for part in [target, *target.parents]:
                if part == base:
                    break
                if part.is_symlink() or part.is_junction():
                    raise ValueError('linked sample paths forbidden')
            if not target.resolve().is_relative_to(base):
                raise ValueError('sample path escapes manifest directory')
            source = next((s for s in manifest.sources if s.source_id == args.source_id), None)
            if source is None:
                raise ValueError('source_id is not registered')
            receipt = replay(source, read_bounded(target, MAX_BYTES), final_url=source.source_url,
                             status=200, content_type='text/plain')
            result = receipt.model_dump()
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError):
        # Do not echo untrusted metadata, arbitrary path names or URL credentials.
        parser.exit(2, 'Candidate validation failed; inspect local input against the contract.\n')


if __name__ == '__main__':
    main()
