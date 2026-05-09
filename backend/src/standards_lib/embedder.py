"""离线 Embedder：启动时加载本地模型，全局复用。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import numpy as np

log = logging.getLogger(__name__)

# 模型名（sentence-transformers）
# 注意：必须与 ChromaDB 里的 embedding 维度一致。
# 场景一文件用的是 BAAI/bge-m3 (1024维)，所以这里也用这个。
_EMBEDDER_MODEL = "BAAI/bge-m3"
_EMBEDDER_BATCH_SIZE = 16

# 全局单例
_instance: "Embedder | None" = None


class Embedder:
    """SentenceTransformer 包装，进程内单例。"""

    def __init__(self, model_name: str = _EMBEDDER_MODEL) -> None:
        from sentence_transformers import SentenceTransformer
        log.info("加载 Embedder 模型: %s …", model_name)
        self._model = SentenceTransformer(model_name, device="cpu")
        self._dim = self._model.get_embedding_dimension()
        log.info("Embedder 加载完成，维度=%d", self._dim)

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: str | list[str], *, batch_size: int = _EMBEDDER_BATCH_SIZE) -> np.ndarray:
        """返回 numpy.ndarray shape (n, dim)，L2 归一化。"""
        single = isinstance(texts, str)
        texts = [texts] if single else texts
        vecs = self._model.encode(texts, batch_size=batch_size,
                                  normalize_embeddings=True,  # cosine 只需 dot product
                                  show_progress_bar=False)
        return vecs if not single else vecs[0]

    def encode_query(self, text: str) -> np.ndarray:
        """查询专用（单条），结果已归一化，可直接做 dot product。"""
        return self.encode(text)


def get_embedder() -> Embedder:
    """获取全局单例，延迟加载。"""
    global _instance
    if _instance is None:
        _instance = Embedder()
    return _instance


def preload_embedder() -> None:
    """在后台线程预热模型（uvicorn 启动时调用）。"""
    import threading
    t = threading.Thread(target=get_embedder, daemon=True)
    t.start()