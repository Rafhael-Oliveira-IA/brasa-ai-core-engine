from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.providers.alibaba_embedding_adapter import AlibabaEmbeddingAdapter


class StubAlibabaEmbeddingAdapter(AlibabaEmbeddingAdapter):
    def __init__(self, *, cache_file: Path) -> None:
        super().__init__(
            api_key="key",
            base_url="https://example.com/v1",
            cache_file=cache_file,
            max_batch_size=8,
        )
        self.calls = 0

    def _request_embedding_batch(self, *, inputs: list[str], model_name: str) -> list[list[float]]:
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in inputs]


class SplitTrackingEmbeddingAdapter(AlibabaEmbeddingAdapter):
    def __init__(self, *, cache_file: Path, max_batch_size: int) -> None:
        super().__init__(
            api_key="key",
            base_url="https://example.com/v1",
            cache_file=cache_file,
            max_batch_size=max_batch_size,
        )
        self.batch_sizes: list[int] = []

    def _request_embedding_batch(self, *, inputs: list[str], model_name: str) -> list[list[float]]:
        self.batch_sizes.append(len(inputs))
        return [[0.4, 0.2, 0.1] for _ in inputs]


def test_alibaba_embedding_adapter_uses_cache_between_calls() -> None:
    with TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "embeddings-cache.json"
        adapter = StubAlibabaEmbeddingAdapter(cache_file=cache_file)

        first = adapter.embed_texts(["inventory service", "event bus"])
        second = adapter.embed_texts(["inventory service", "event bus"])

        assert first == second
        assert adapter.calls == 1
        assert cache_file.exists()


def test_alibaba_embedding_adapter_caps_batch_size_at_ten() -> None:
    with TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "embeddings-cache.json"
        adapter = SplitTrackingEmbeddingAdapter(cache_file=cache_file, max_batch_size=999)

        payload = [f"token-{index}" for index in range(23)]
        vectors = adapter.embed_texts(payload)

        assert len(vectors) == 23
        assert adapter.max_batch_size == 10
        assert adapter.batch_sizes == [10, 10, 3]
