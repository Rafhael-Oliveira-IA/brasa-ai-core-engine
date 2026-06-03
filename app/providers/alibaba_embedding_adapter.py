from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from app.providers.base import ProviderFailure, ProviderUnavailable


RETRIABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class AlibabaEmbeddingAdapter:
    name = "alibaba-embedding"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model_name: str = "text-embedding-v4",
        timeout_seconds: int = 25,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.35,
        region_base_urls: list[str] | None = None,
        max_batch_size: int = 16,
        cache_file: Path | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model_name = model_name
        self.timeout_seconds = max(5, timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.05, retry_backoff_seconds)
        self.max_batch_size = max(1, max_batch_size)

        normalized_urls = [item.rstrip("/") for item in (region_base_urls or self._parse_region_urls(base_url)) if item]
        if not normalized_urls:
            normalized_urls = [base_url.rstrip("/")]

        self.base_url = normalized_urls[0]
        self.region_base_urls = normalized_urls

        self.cache_file = cache_file
        self._lock = Lock()
        self._cache: dict[str, list[float]] = self._load_cache()

    def embed_texts(self, texts: list[str], model_name: str | None = None) -> list[list[float]]:
        cleaned = [item.strip() for item in texts if item and item.strip()]
        if not cleaned:
            return []

        if not self.api_key:
            raise ProviderUnavailable("Alibaba API key is not configured for embeddings.")

        selected_model = (model_name or self.model_name).strip() or self.model_name

        vectors_by_text: dict[str, list[float]] = {}
        misses: list[str] = []

        with self._lock:
            for text in cleaned:
                cached = self._cache.get(self._cache_key(selected_model, text))
                if cached:
                    vectors_by_text[text] = cached
                else:
                    misses.append(text)

        if misses:
            for start in range(0, len(misses), self.max_batch_size):
                batch = misses[start : start + self.max_batch_size]
                batch_vectors = self._request_embedding_batch(inputs=batch, model_name=selected_model)
                if len(batch_vectors) != len(batch):
                    raise ProviderFailure("Alibaba embeddings returned an unexpected vector count.")

                with self._lock:
                    for text, vector in zip(batch, batch_vectors, strict=False):
                        vectors_by_text[text] = vector
                        self._cache[self._cache_key(selected_model, text)] = vector

            self._flush_cache()

        return [vectors_by_text[text] for text in cleaned if text in vectors_by_text]

    def _request_embedding_batch(self, *, inputs: list[str], model_name: str) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model_name,
            "input": inputs,
        }

        last_error: Exception | None = None
        for base_url in self.region_base_urls:
            url = f"{base_url}/embeddings"

            for attempt in range(self.max_retries + 1):
                try:
                    with httpx.Client(timeout=self.timeout_seconds) as client:
                        response = client.post(url, json=payload, headers=headers)

                    if response.status_code in RETRIABLE_STATUS_CODES and attempt < self.max_retries:
                        time.sleep(self.retry_backoff_seconds * (2**attempt))
                        continue

                    response.raise_for_status()
                    data = response.json()
                    return self._extract_vectors(data, expected_count=len(inputs))
                except httpx.HTTPStatusError as exc:
                    details = exc.response.text[:400]
                    last_error = ProviderFailure(f"Alibaba embeddings HTTP error ({exc.response.status_code}): {details}")
                    if exc.response.status_code in RETRIABLE_STATUS_CODES and attempt < self.max_retries:
                        time.sleep(self.retry_backoff_seconds * (2**attempt))
                        continue
                    break
                except httpx.HTTPError as exc:
                    last_error = ProviderUnavailable(f"Alibaba embeddings network error: {exc}")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_backoff_seconds * (2**attempt))
                        continue
                    break

        if last_error is not None:
            raise last_error
        raise ProviderUnavailable("Alibaba embeddings request failed without details.")

    def _extract_vectors(self, payload: dict[str, Any], *, expected_count: int) -> list[list[float]]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderFailure("Alibaba embeddings response does not contain a valid data list.")

        ordered: list[list[float] | None] = [None] * expected_count

        for item in data:
            if not isinstance(item, dict):
                continue

            index = int(item.get("index", -1))
            embedding = item.get("embedding")
            if index < 0 or index >= expected_count or not isinstance(embedding, list):
                continue

            ordered[index] = [float(value) for value in embedding]

        vectors = [item for item in ordered if item is not None]
        if len(vectors) != expected_count:
            raise ProviderFailure("Alibaba embeddings response is missing vector entries.")

        return vectors

    def _parse_region_urls(self, raw_value: str) -> list[str]:
        parts = [item.strip() for item in (raw_value or "").split(",")]
        return [item for item in parts if item]

    def _cache_key(self, model_name: str, text: str) -> str:
        value = f"{model_name}:{text}".encode("utf-8", errors="ignore")
        return hashlib.sha256(value).hexdigest()

    def _load_cache(self) -> dict[str, list[float]]:
        if self.cache_file is None or not self.cache_file.exists():
            return {}

        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, dict):
            return {}

        cache: dict[str, list[float]] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, list):
                continue
            try:
                cache[key] = [float(item) for item in value]
            except Exception:
                continue

        return cache

    def _flush_cache(self) -> None:
        if self.cache_file is None:
            return

        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.cache_file.write_text(
                json.dumps(self._cache, ensure_ascii=True, separators=(",", ":")),
                encoding="utf-8",
            )
