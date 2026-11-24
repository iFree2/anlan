"""Pure offline checks. Never resolves DNS, follows redirects or executes content."""

import hashlib
import re
from urllib.parse import urlsplit

from .contracts import CandidateReceipt, SourceCandidate

MAX_BYTES = 65536
ALLOWED_HOSTS = frozenset({'www.mem.gov.cn', 'huggingface.co', 'modelscope.cn'})


def validate_url(url: str, *, allow_synthetic: bool = False) -> str:
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        raise ValueError('URL must be printable ASCII without whitespace')
    if any(c in url for c in ('\\', '%', '?', '#')):
        raise ValueError('URL encoding, query, fragment or backslash forbidden')
    parsed = urlsplit(url)
    if allow_synthetic and re.fullmatch(r'synthetic://public-pilot/[a-z0-9-]+\.txt', url):
        return url
    if parsed.scheme != 'https' or parsed.netloc not in ALLOWED_HOSTS:
        raise ValueError('URL requires HTTPS and an exact approved host')
    if any(p in ('.', '..') for p in parsed.path.split('/')):
        raise ValueError('relative URL path forbidden')
    return url


def replay(
    source: SourceCandidate, body: bytes, *, final_url: str, status: int,
    content_type: str, redirected: bool = False, content_encoding: str | None = None,
) -> CandidateReceipt:
    """Check host-supplied bytes; does not establish upstream permission by itself."""
    # Revalidate even constructed/model_copy objects before trusting policy fields.
    source = SourceCandidate.model_validate(source.model_dump())
    if (source.import_policy != 'licensed_sample'
            or source.license.redistribution != 'allowed'
            or source.license.identifier.lower() in {'unknown', 'none', 'unverified'}
            or source.upstream_revision is None or source.content_sha256 is None):
        raise ValueError('import requires evidenced permission, revision and content hash')
    if (validate_url(final_url, allow_synthetic=source.access == 'offline_fixture')
            != source.source_url or status != 200 or redirected):
        raise ValueError('response URL/status/redirect mismatch')
    if content_encoding is not None:
        raise ValueError('encoded response forbidden')
    if content_type.lower().replace(' ', '') not in {'text/plain', 'text/plain;charset=utf-8'}:
        raise ValueError('only UTF-8 plain text is supported')
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES:
        raise ValueError('body must be 1..65536 bytes')
    text = body.decode('utf-8', errors='strict')
    if '\x00' in text:
        raise ValueError('NUL text forbidden')
    digest = hashlib.sha256(body).hexdigest()
    if digest != source.content_sha256:
        raise ValueError('content SHA256 mismatch')
    return CandidateReceipt(source_id=source.source_id, upstream_revision=source.upstream_revision,
                            sha256=digest, size_bytes=len(body))
