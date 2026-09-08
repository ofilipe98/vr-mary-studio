"""Optional CPU embeddings. Network access exists only in explicit prepare_model()."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Callable, Sequence

from .embedding_contract import EmbeddingBackend

MODELS = {
    "e5-small": {
        "repository": "intfloat/multilingual-e5-small", "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "license": "MIT", "dimension": 384, "max_tokens": 512, "pooling": "masked_mean_l2",
        "query_prefix": "query: ", "document_prefix": "passage: ",
        "files": {
            "model.onnx": ("onnx/model_qint8_avx512_vnni.onnx", "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88", 118346824),
            "tokenizer.json": ("tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39", 17082730),
        },
    },
    "minilm": {
        "repository": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
        "license": "Apache-2.0", "dimension": 384, "max_tokens": 128, "pooling": "masked_mean_l2",
        "query_prefix": "", "document_prefix": "",
        "files": {
            "model.onnx": ("onnx/model_quint8_avx2.onnx", "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f", 118453870),
            "tokenizer.json": ("tokenizer.json", "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8", 9081518),
        },
    },
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_directory(root: Path, model: str) -> Path:
    return root / "tools" / "embeddings" / model / MODELS[model]["revision"]


def prepare_model(root: Path, model: str, progress: Callable[[str, int, int], None] | None = None) -> Path:
    """Explicit user action: download public weights, verify SHA-256, publish readiness."""
    import urllib.request
    spec = MODELS[model]
    directory = model_directory(root, model)
    directory.mkdir(parents=True, exist_ok=True)
    for local, (remote, checksum, size) in spec["files"].items():
        target = directory / local
        if target.is_file() and file_hash(target) == checksum:
            continue
        temporary = directory / f"{local}.{os.getpid()}.part"
        url = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/{remote}"
        try:
            received = 0
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
                while data := response.read(1024 * 1024):
                    stream.write(data)
                    received += len(data)
                    if progress:
                        progress(local, received, size)
            if received != size or file_hash(temporary) != checksum:
                raise ValueError(f"Checksum inválido: {local}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    # Store the full immutable contract alongside the offline assets.
    ready = directory / f"ready.{os.getpid()}.tmp"
    ready.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    ready.replace(directory / "ready.json")
    return directory


class LocalOnnxEmbedding(EmbeddingBackend):
    """Masked mean pooling on CPU; loading never downloads or swaps vector spaces."""

    def __init__(self, root: Path, model: str = "e5-small", *, threads: int = 2):
        self.spec = MODELS[model]
        self.directory = model_directory(root, model)
        if not (self.directory / "ready.json").is_file():
            raise FileNotFoundError("Modelo local ausente. Use Preparar modelo semântico.")
        for local, (_, checksum, _) in self.spec["files"].items():
            if file_hash(self.directory / local) != checksum:
                raise ValueError(f"Modelo local corrompido: {local}")
        import onnxruntime as ort
        from tokenizers import Tokenizer
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, threads)
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.directory / "model.onnx"), sess_options=opts, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=self.spec["max_tokens"])
        pad = self.tokenizer.token_to_id("<pad>")
        self.tokenizer.enable_padding(pad_id=pad if pad is not None else 0)
        self._lock = threading.Lock()

    @property
    def dimension(self) -> int:
        return self.spec["dimension"]

    @property
    def model_name(self) -> str:
        return f"{self.spec['repository']}@{self.spec['revision']}:{self.spec['files']['model.onnx'][1]}:mean-l2"

    def _embed(self, texts: Sequence[str], prefix: str) -> list[list[float]]:
        import numpy as np
        if not texts:
            return []
        with self._lock:
            encoded = self.tokenizer.encode_batch([prefix + str(t) for t in texts])
        inputs = {
            "input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
            "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64),
        }
        output = self.session.run(None, {i.name: inputs[i.name] for i in self.session.get_inputs()})[0]
        mask = inputs["attention_mask"][..., None]
        pooled = (output * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
        pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        if pooled.shape != (len(texts), self.dimension) or not np.isfinite(pooled).all():
            raise ValueError("Modelo retornou vetores incompatíveis.")
        return pooled.tolist()

    def embed_text(self, text: str) -> list[float]:
        return self._embed([text], self.spec["document_prefix"])[0]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], self.spec["query_prefix"])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, self.spec["document_prefix"])
