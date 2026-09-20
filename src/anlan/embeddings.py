"""本地中文神经向量；模型文件固定到首次下载摘要，绝不伪造替代向量。"""

import asyncio
import hashlib
import json
import math
import os
from importlib.metadata import version
from pathlib import Path

DIMENSIONS = 512
MODEL_NAME = "BAAI/bge-small-zh-v1.5"


def validate_vectors(vectors, expected_count):
    if len(vectors) != expected_count:
        raise ValueError("embedding count mismatch")
    for vector in vectors:
        if len(vector) != DIMENSIONS or any(
                type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise ValueError("invalid embedding vector")
        if not any(vector):
            raise ValueError("zero vector cannot support cosine retrieval")
    return vectors


class LocalEmbeddings:
    def __init__(self, cache_dir: Path = Path(".runtime/embeddings")):
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from fastembed import TextEmbedding

        cache_dir = cache_dir.resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = cache_dir / "model-manifest.json"
        self.model = TextEmbedding(
            model_name=MODEL_NAME, cache_dir=str(cache_dir), threads=2,
            providers=["CPUExecutionProvider"], local_files_only=manifest_path.exists())
        # fastembed 0.8.0的已锁定实现公开包装器model，底层保存实际模型目录。
        model_dir = Path(self.model.model._model_dir)
        hashes = {}
        for path in sorted(model_dir.rglob("*")):
            relative = path.relative_to(model_dir)
            if path.is_file() and not any(part.startswith(".") for part in relative.parts):
                hashes[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        self.manifest = {"model": MODEL_NAME, "dimensions": DIMENSIONS,
                         "fastembed_version": version("fastembed"), "files": hashes,
                         "artifact_sha256": digest, "execution": "local_cpu"}
        if manifest_path.exists():
            if json.loads(manifest_path.read_text(encoding="utf-8")) != self.manifest:
                raise ValueError("embedding artifact changed; use a new explicit model version")
        else:
            with manifest_path.open("x", encoding="utf-8") as output:
                json.dump(self.manifest, output, ensure_ascii=False, indent=2)
        self.model_id = MODEL_NAME + ":" + digest

    @classmethod
    async def create(cls, cache_dir: Path = Path(".runtime/embeddings")):
        return await asyncio.to_thread(cls, cache_dir)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await asyncio.to_thread(lambda: [
            vector.tolist() for vector in self.model.embed(texts, batch_size=16)])
        return validate_vectors(vectors, len(texts))
