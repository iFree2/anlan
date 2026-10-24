"""Write new private SYNTHETIC dual-role configurations; never print credentials."""

import argparse
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from anlan.interfaces.service_config import ServiceConfig


def prepare(output: Path):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / 'examples/synthetic/perception-v1'
    tenant = 'synthetic-p12-' + uuid4().hex[:12]
    grants = [{'token': secrets.token_urlsafe(48),
               'identity': {'tenant_id': tenant, 'user_id': user}, 'collaboration_role': role}
              for user, role in [('applicant-demo', 'applicant'),
                                 ('safety-manager-demo', 'safety_manager')]]
    facts = output / 'facts'
    facts.mkdir(mode=0o700)
    for path in (source / 'facts').glob('*.json'):
        document = json.loads(path.read_text(encoding='utf-8'))
        for record in document.get('records', []):
            record['tenant_id'] = tenant
        with (facts / path.name).open('x', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
    config = {'schema_version': 'local-service-v1', 'tokens': grants,
              'model_mode': 'scripted_double',
              'as_of': '2026-09-22T04:00:00+00:00',
              'facts_dir': str(facts.resolve()),
              'console_profiles': [{'identity': grants[1]['identity'], 'references':
                  json.loads((source / 'refs.json').read_text(encoding='utf-8'))}]}
    ServiceConfig.model_validate(config)
    for name, document in [('service', config), ('applicant', {
        'schema_version': 'local-service-v1', 'tokens': [grants[0]]}), ('safety-manager', {
        'schema_version': 'local-service-v1', 'tokens': [grants[1]]})]:
        target = output / f'{name}.json'
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.runtime') / (
        'collaboration-demo-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '-' +
        uuid4().hex[:8]))
    args = parser.parse_args()
    try:
        output = prepare(args.output)
    except FileExistsError:
        parser.exit(2, 'Output already exists; choose a new directory. No files overwritten.\n')
    print('SYNTHETIC scripted configurations created in a new private directory.')
    # No document contents, DSN or tokens are emitted, even on failure.
    for name in ('service', 'applicant', 'safety-manager'):
        print(name + ': ' + str((output / f'{name}.json').resolve()))
    print('Material review completion does not authorize work.')


if __name__ == '__main__':
    main()
