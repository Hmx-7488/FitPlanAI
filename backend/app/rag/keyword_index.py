"""RAG keyword index - simple BM25-like keyword retrieval."""
from __future__ import annotations
import re
import math
from collections import Counter
from typing import Optional
from app.rag.models import KnowledgeChunk


class KeywordIndex:
    """Simple inverted-index keyword retriever (no external deps needed)."""

    def __init__(self):
        self._chunks: list[KnowledgeChunk] = []
        self._doc_freqs: list[Counter] = []
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0

    def build(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = chunks
        self._doc_freqs = []
        df: Counter = Counter()
        total_dl = 0
        for ch in chunks:
            tokens = self._tokenize(ch.title + " " + ch.content)
            freq = Counter(tokens)
            self._doc_freqs.append(freq)
            total_dl += len(tokens)
            for term in set(tokens):
                df[term] += 1
        n = max(len(chunks), 1)
        self._avg_dl = total_dl / n if n else 1.0
        self._idf = {t: math.log((n - v + 0.5) / (v + 0.5) + 1) for t, v in df.items()}

    def search(self, query: str, top_k: int = 5) -> list[tuple[KnowledgeChunk, float]]:
        if not self._chunks:
            return []
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []
        scores = []
        for i, ch in enumerate(self._chunks):
            score = self._bm25_score(q_tokens, i)
            if score > 0:
                scores.append((ch, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _bm25_score(self, q_tokens: list[str], doc_idx: int) -> float:
        k1, b = 1.5, 0.75
        freq = self._doc_freqs[doc_idx]
        dl = sum(freq.values())
        score = 0.0
        for t in q_tokens:
            if t not in freq:
                continue
            tf = freq[t]
            idf = self._idf.get(t, 0.0)
            num = tf * (k1 + 1)
            den = tf + k1 * (1 - b + b * dl / self._avg_dl)
            score += idf * num / den
        return score

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = text.lower()
        # Split on non-alphanumeric and non-CJK
        tokens = re.findall(r"[a-z0-9]+|[一-鿿]+", text)
        # Further split CJK into bigrams for better matching
        result = []
        for t in tokens:
            if len(t) > 1 and re.match(r"[一-鿿]", t):
                # Chinese bigrams
                for j in range(len(t) - 1):
                    result.append(t[j:j+2])
                result.append(t)
            else:
                result.append(t)
        return result
