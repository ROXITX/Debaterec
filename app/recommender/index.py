"""Stage-one retrieval indexes (PRD §12, §37).

Two lexical scorers are combined, and an optional dense scorer can replace them:

  * **BM25** — implemented here in NumPy rather than pulled from a package, so
    the ranking function is inspectable and the project has one fewer
    dependency. Good at "the query words appear in this item".
  * **TF-IDF cosine** — scikit-learn, with word and character n-grams. The
    character n-grams matter for this catalogue: they let "sci-fi" find
    "science fiction" and "macbook" find "MacBook Air".
  * **Embeddings** — optional. Enabled with RETRIEVAL_MODE=semantic once
    sentence-transformers is installed. Everything else is unchanged, which is
    what makes the lexical-vs-dense comparison a clean experiment.

The default is lexical because it needs no model download and starts instantly
on a fresh Windows or macOS machine.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from ..config import settings
from ..domains.registry import get_adapter, load_domain
from ..schemas import Item

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'+.-]*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 over a sparse term-document matrix.

    k1 controls term-frequency saturation, b the length penalty.

    The matrix must be sparse. A dense term-document matrix costs
    n_docs x vocab x 4 bytes, which is about 180MB for a single 3,000-item
    catalogue and is multiplied by every domain loaded. CSC layout is chosen
    because scoring slices by *column* (one column per query term).
    """

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.4, b: float = 0.72) -> None:
        from scipy import sparse

        self.k1, self.b = k1, b
        self.n_docs = len(corpus_tokens)
        self.doc_len = np.array([len(d) for d in corpus_tokens], dtype=np.float32)
        self.avg_len = float(self.doc_len.mean()) if self.n_docs else 0.0

        self.vocab: dict[str, int] = {}
        rows: list[int] = []
        cols: list[int] = []
        values: list[float] = []
        for i, doc in enumerate(corpus_tokens):
            counts: dict[int, float] = {}
            for term in doc:
                col = self.vocab.setdefault(term, len(self.vocab))
                counts[col] = counts.get(col, 0.0) + 1.0
            rows.extend([i] * len(counts))
            cols.extend(counts.keys())
            values.extend(counts.values())

        shape = (self.n_docs, max(len(self.vocab), 1))
        self.tf = sparse.csc_matrix(
            (np.array(values, dtype=np.float32), (rows, cols)), shape=shape
        )

        df = np.asarray((self.tf > 0).sum(axis=0)).ravel().astype(np.float32)
        # Robertson/Sparck-Jones IDF with the +1 smoothing that keeps it positive.
        self.idf = np.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5)).astype(np.float32)
        # Precomputed length normalisation — identical for every query.
        self.norm = (self.k1 * (1 - self.b + self.b * self.doc_len / max(self.avg_len, 1e-6))).astype(np.float32)

    def score(self, query: str) -> np.ndarray:
        if self.n_docs == 0:
            return np.zeros(0, dtype=np.float32)
        cols = [self.vocab[t] for t in tokenize(query) if t in self.vocab]
        if not cols:
            return np.zeros(self.n_docs, dtype=np.float32)

        scores = np.zeros(self.n_docs, dtype=np.float32)
        for col in cols:
            column = self.tf.getcol(col)
            if column.nnz == 0:
                continue
            docs = column.indices
            freq = column.data
            contribution = (freq * (self.k1 + 1)) / (freq + self.norm[docs])
            # np.add.at accumulates correctly when a term repeats in the query.
            np.add.at(scores, docs, contribution * self.idf[col])
        return scores


@dataclass
class DomainIndex:
    domain: str
    items: list[Item]
    bm25: BM25
    tfidf_word: TfidfVectorizer
    matrix_word: object
    tfidf_char: TfidfVectorizer
    matrix_char: object
    dense: object | None = None
    embeddings: object | None = None

    def semantic_scores(self, query: str) -> np.ndarray:
        """A single relevance vector in [0, 1], one entry per item."""
        if self.dense is not None and self.embeddings is not None:
            q = self.dense.encode([query], normalize_embeddings=True)
            return np.clip(np.asarray(self.embeddings @ q[0]).ravel(), 0.0, 1.0)

        bm = _unit(self.bm25.score(query))
        qw = self.tfidf_word.transform([query])
        cw = np.asarray((self.matrix_word @ qw.T).todense()).ravel()
        qc = self.tfidf_char.transform([query])
        cc = np.asarray((self.matrix_char @ qc.T).todense()).ravel()
        # BM25 finds exact term hits; cosine handles paraphrase and morphology.
        return np.clip(0.45 * bm + 0.35 * _unit(cw) + 0.20 * _unit(cc), 0.0, 1.0)


def _unit(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    top = float(values.max())
    if top <= 1e-9:
        return np.zeros_like(values)
    return values / top


@lru_cache(maxsize=None)
def build_index(domain: str, curated_only: bool = False) -> DomainIndex:
    items = list(load_domain(domain, curated_only))
    adapter = get_adapter(domain)
    corpus = [it.text_blob or adapter.build_text(it) for it in items]

    word = TfidfVectorizer(
        sublinear_tf=True, ngram_range=(1, 2), min_df=1,
        stop_words="english", max_features=300_000, dtype=np.float32,
    )
    m_word = _l2(word.fit_transform(corpus))

    # Character n-grams run over titles and tags ONLY, not the prose.
    # Their whole job is fuzzy surface matching — letting "sci-fi" reach
    # "science fiction" and "macbook" reach "MacBook Air". Running them over full
    # descriptions costs roughly ten times as much for no extra recall: on a
    # 2,400-item catalogue it took index construction from about one second to
    # eleven.
    short_corpus = [_short_text(it) for it in items]
    char = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
        max_features=200_000, dtype=np.float32,
    )
    m_char = _l2(char.fit_transform(short_corpus))

    index = DomainIndex(
        domain=domain,
        items=items,
        bm25=BM25([tokenize(c) for c in corpus]),
        tfidf_word=word,
        matrix_word=m_word,
        tfidf_char=char,
        matrix_char=m_char,
    )

    if settings.retrieval_mode == "semantic":
        try:  # optional dependency, deliberately not in requirements.txt
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(settings.embedding_model)
            index.dense = model
            index.embeddings = model.encode(corpus, normalize_embeddings=True, show_progress_bar=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[retrieval] semantic mode requested but unavailable ({exc}); using lexical.")

    return index


def _short_text(item: Item) -> str:
    """Title, subtitle and tag values — the fields worth fuzzy-matching."""
    parts = [item.title, item.subtitle]
    for values in item.tags.values():
        parts.extend(values)
    return " ".join(p for p in parts if p)


def _l2(matrix):
    from sklearn.preprocessing import normalize

    return normalize(matrix, norm="l2", axis=1)


def warm_all(build_indexes: bool = False) -> dict[str, int]:
    """Load every catalogue, and optionally build every index.

    Index construction is deferred by default. At full catalogue scale building
    all seven costs far more than loading them, and a session typically touches
    two or three domains — so the cost is paid on first use of a domain rather
    than on every startup.
    """
    from ..domains.registry import REGISTRY, load_domain

    out = {}
    for key in REGISTRY:
        out[key] = len(build_index(key).items) if build_indexes else len(load_domain(key))
    return out


def idf_of(index: DomainIndex, term: str) -> float:
    col = index.bm25.vocab.get(term.lower())
    return float(index.bm25.idf[col]) if col is not None else math.log(1.0 + index.bm25.n_docs)
