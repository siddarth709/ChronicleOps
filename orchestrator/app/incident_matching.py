import math
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")

def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]

def _tf(tokens: list[str]) -> Counter:
    return Counter(tokens)

def _idf(corpus_tokens: list[list[str]]) -> dict:
    n_docs = len(corpus_tokens)
    doc_freq: Counter = Counter()
    for tokens in corpus_tokens:
        for word in set(tokens):
            doc_freq[word] += 1
    return {
        word: math.log((n_docs + 1) / (freq + 1)) + 1.0
        for word, freq in doc_freq.items()
    }

def _tfidf_vector(tokens: list[str], idf: dict) -> dict:
    tf = _tf(tokens)
    return {word: count * idf.get(word, 0.0) for word, count in tf.items()}

def _cosine(a: dict, b: dict) -> float:
    common = set(a) & set(b)
    numerator = sum(a[w] * b[w] for w in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return numerator / (norm_a * norm_b)

def rank_similar_incidents(
    query_text: str,
    past_incidents: list[dict],
    text_field: str = "log_excerpt",
    top_k: int = 3,
) -> list[dict]:
    if not past_incidents:
        return []

    corpus_tokens = [tokenize(inc.get(text_field, "")) for inc in past_incidents]
    query_tokens = tokenize(query_text)

    idf = _idf(corpus_tokens + [query_tokens])
    query_vec = _tfidf_vector(query_tokens, idf)

    scored = []
    for inc, tokens in zip(past_incidents, corpus_tokens):
        vec = _tfidf_vector(tokens, idf)
        score = _cosine(query_vec, vec)
        scored.append({**inc, "similarity": round(score, 4)})

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]