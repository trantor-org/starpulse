"""Trace clusters: groups of cases that did the same distinctive work, and how far each case strays from its group.

A case's features are its activities (`a:`) and the areas it read (`r:`) and wrote (`w:`), less the `stop` activities
every delivery performs. TF-IDF weights them (binary term frequency, smoothed idf, rows scaled to unit length) after
dropping a feature found in fewer than `min_df` cases or in more than `max_df` of them, so the lifecycle every task
performs never defines a cluster. Average-linkage agglomerative clustering on cosine distance joins cases until the
nearest pair of clusters is `threshold` apart; a case with no feature left joins no cluster.

The result is the one scikit-learn's `TfidfVectorizer` and `AgglomerativeClustering(linkage="average")` give, in the
standard library alone: the case matrix is sparse, and a pair of cases that share no feature is a distance of 1.
"""

import hashlib
import heapq
import math
from collections import Counter, defaultdict
from collections.abc import Hashable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby
from statistics import median

from starpulse.flow_metrics.model.traces import Case

__all__ = [
    "Cluster",
    "Dispersion",
    "Outlier",
    "cluster_key",
    "dispersion",
    "lcs_length",
    "partition",
    "trace",
    "trace_clusters",
]

#: Features a cluster is named by.
DESCRIPTORS = 6


@dataclass(frozen=True)
class Cluster:
    """Cases that did the same distinctive work, and the features that weigh most across them."""

    cases: tuple[Case, ...]
    descriptors: tuple[str, ...]

    @property
    def sessions(self) -> int:
        """How many distinct sessions the cases come from: one session that worked many tasks is one."""
        return len({(c.harness, c.session) for c in self.cases})


@dataclass(frozen=True)
class Outlier:
    case: Case
    distance: float
    deletions: tuple[str, ...]  # the medoid's activities the outlier's trace lacks
    insertions: tuple[str, ...]  # the outlier's activities the medoid's trace lacks


@dataclass(frozen=True)
class Dispersion:
    """A cluster's medoid, the usual distance of its other cases from it, and the cases furthest from it."""

    medoid: Case
    median: float
    outliers: tuple[Outlier, ...]


def cluster_key(cluster: Cluster) -> str:
    """A stable id for a cluster: its descriptors, which name the work it groups."""
    return hashlib.sha1("|".join(sorted(cluster.descriptors)).encode()).hexdigest()[:12]


def _features(case: Case, stop: frozenset[str]) -> set[str]:
    return (
        {f"a:{a}" for a in case.activities if a not in stop}
        | {f"r:{r}" for r in case.reads}
        | {f"w:{w}" for w in case.writes}
    )


def _vectors(documents: list[set[str]], min_df: int, max_df: float) -> list[dict[str, float]]:
    """Each document as a unit TF-IDF vector over the features whose document frequency is in range."""
    frequency = Counter(f for document in documents for f in document)
    most = max_df * len(documents)
    idf = {f: math.log((1 + len(documents)) / (1 + n)) + 1 for f, n in frequency.items() if min_df <= n <= most}
    vectors = []
    for document in documents:
        weights = {f: idf[f] for f in document if f in idf}
        norm = math.sqrt(sum(w * w for w in weights.values()))
        vectors.append({f: w / norm for f, w in weights.items()} if norm else {})
    return vectors


def _nearness(vectors: Sequence[dict[str, float]]) -> dict[int, dict[int, float]]:
    """The cosine distance between each pair of unit `vectors` that share a feature; others are 1 apart, not stored."""
    postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for i, vector in enumerate(vectors):
        for f, w in vector.items():
            postings[f].append((i, w))
    dots: list[dict[int, float]] = [defaultdict(float) for _ in vectors]
    for members in postings.values():
        for a, (i, wi) in enumerate(members):
            row = dots[i]
            for j, wj in members[a + 1 :]:
                row[j] += wi * wj
    near: dict[int, dict[int, float]] = {i: {} for i in range(len(vectors))}
    for i, row in enumerate(dots):
        for j, dot in row.items():
            near[i][j] = near[j][i] = max(0.0, 1 - dot)
    return near


def partition(vectors: Sequence[dict[str, float]], threshold: float) -> list[list[int]]:
    """Average-linkage clusters of unit `vectors` on cosine distance: clusters merge, nearest pair first, while that
    pair is less than `threshold` apart."""
    near = _nearness(vectors)
    heap = [(d, i, j) for i, row in near.items() for j, d in row.items() if i < j and d < threshold]
    heapq.heapify(heap)
    members_of = {i: [i] for i in range(len(vectors))}
    fresh = len(vectors)
    while heap:
        d, i, j = heapq.heappop(heap)
        if i not in near or j not in near or near[i].get(j) != d:
            continue  # a cluster merged away, or its distance moved on
        size_i, size_j = len(members_of[i]), len(members_of[j])
        row: dict[int, float] = {}
        for k in near[i].keys() | near[j].keys():
            if k not in (i, j):
                # Lance-Williams for average linkage; a cluster not stored as near is 1 away.
                row[k] = (size_i * near[i].get(k, 1.0) + size_j * near[j].get(k, 1.0)) / (size_i + size_j)
        for gone in (i, j):
            for k in near.pop(gone):
                if k in near:
                    del near[k][gone]
        near[fresh] = row
        for k, distance in row.items():
            near[k][fresh] = distance
            if distance < threshold:
                heapq.heappush(heap, (distance, min(k, fresh), max(k, fresh)))
        members_of[fresh] = members_of.pop(i) + members_of.pop(j)
        fresh += 1
    return list(members_of.values())


def trace_clusters(
    found: Iterable[Case],
    *,
    stop: frozenset[str] = frozenset(),
    threshold: float = 0.8,
    min_df: int = 5,
    max_df: float = 0.10,
) -> list[Cluster]:
    """The clusters of the cases of `found` that made a tool call, most distinct sessions first, then most cases.

    Clusters of one case are clusters too; the reader decides how many sessions make recurrence."""
    working = [c for c in found if c.tool_calls > 0]
    vectors = _vectors([_features(c, stop) for c in working], min_df, max_df)
    rows = [i for i, v in enumerate(vectors) if v]
    if len(rows) < 2:
        return []
    clusters = []
    for members in partition([vectors[i] for i in rows], threshold):
        weights: dict[str, float] = defaultdict(float)
        for m in members:
            for f, w in vectors[rows[m]].items():
                weights[f] += w / len(members)
        descriptors = tuple(sorted(weights, key=lambda f: (-weights[f], f))[:DESCRIPTORS])
        clusters.append(Cluster(tuple(working[rows[m]] for m in sorted(members)), descriptors))
    return sorted(clusters, key=lambda c: (-c.sessions, -len(c.cases), c.descriptors))


def _masks(a: Sequence[Hashable]) -> dict[Hashable, int]:
    masks: dict[Hashable, int] = defaultdict(int)
    for i, x in enumerate(a):
        masks[x] |= 1 << i
    return masks


def _bit_rows(a: Sequence[Hashable], b: Sequence[Hashable], masks: dict[Hashable, int] | None = None) -> Iterator[int]:
    """The bit-parallel longest-common-subsequence row before `b` and after each of its items: a zero bit `k` of the
    row after `b[:j]` says the prefix `a[:k + 1]` gained a match, so the zeros below bit `i` are the LCS of `a[:i]`
    and `b[:j]`."""
    masks = _masks(a) if masks is None else masks
    full = row = (1 << len(a)) - 1
    yield row
    for y in b:
        mask = masks.get(y, 0)
        row = ((row + (row & mask)) | (row & ~mask)) & full
        yield row


def lcs_length(a: Sequence[Hashable], b: Sequence[Hashable], masks: dict[Hashable, int] | None = None) -> int:
    """The length of the longest common subsequence of `a` and `b`, by bit-parallel dynamic programming; `masks` is
    `_masks(a)` when the caller holds it."""
    masks = _masks(a) if masks is None else masks
    full = row = (1 << len(a)) - 1
    for y in b:
        mask = masks.get(y)
        if mask:  # an item of `a` nowhere leaves the row as it is
            row = ((row + (row & mask)) | (row & ~mask)) & full
    return len(a) - row.bit_count()


def trace(case: Case, stop: frozenset[str] = frozenset()) -> list[str]:
    """The case's activities without stop activities, repeats that dropping them made adjacent collapsed."""
    return [a for a, _ in groupby(a for a in case.activities if a not in stop)]


def _distance(a: Sequence[str], b: Sequence[str], masks: dict[Hashable, int] | None = None) -> float:
    longest = max(len(a), len(b))
    return 1 - lcs_length(a, b, masks) / longest if longest else 0.0


def _unmatched(reference: Sequence[str], observed: Sequence[str]) -> tuple[str, ...]:
    """The items of `reference` outside one longest common subsequence with `observed`, in reference order."""
    rows = list(_bit_rows(reference, observed))

    def common(i: int, j: int) -> int:
        return i - (rows[j] & ((1 << i) - 1)).bit_count()

    left, i, j = [], len(reference), len(observed)
    while i:
        if j and reference[i - 1] == observed[j - 1]:
            i, j = i - 1, j - 1
        elif j and common(i, j - 1) >= common(i - 1, j):
            j -= 1
        else:
            left.append(reference[i - 1])
            i -= 1
    return tuple(reversed(left))


def dispersion(cluster: Cluster, count: int, stop: frozenset[str] = frozenset()) -> Dispersion:
    """The cluster's medoid, the case closest to every other by normalized LCS distance between traces, and the
    `count` cases whose traces lie furthest from it."""
    traces = [trace(c, stop) for c in cluster.cases]
    distances = [[0.0] * len(traces) for _ in traces]
    for i, a in enumerate(traces):
        masks = _masks(a)
        for j in range(i + 1, len(traces)):
            distances[i][j] = distances[j][i] = _distance(a, traces[j], masks)
    medoid = min(range(len(traces)), key=lambda i: sum(distances[i]))
    others = [i for i in range(len(traces)) if i != medoid]
    ranked = sorted(others, key=lambda i: (-distances[medoid][i], cluster.cases[i].session))
    return Dispersion(
        cluster.cases[medoid],
        median(distances[medoid][i] for i in others) if others else 0.0,
        tuple(
            Outlier(
                cluster.cases[i],
                distances[medoid][i],
                _unmatched(traces[medoid], traces[i]),
                _unmatched(traces[i], traces[medoid]),
            )
            for i in ranked[:count]
        ),
    )
