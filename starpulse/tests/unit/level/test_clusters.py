"""Trace clusters: TF-IDF on a case's activities and areas, average-linkage cut, worked out by hand."""

import hashlib
import math
import random

import pytest

from starpulse._internal.level.clusters import Cluster, cluster_key, dispersion, lcs_length, partition, trace_clusters
from starpulse._internal.level.traces import Case

NOISE = ("git status", "gh pr view", "Read", "Edit")


def case(
    n: int, *work: str, session: str | None = None, reads: tuple[str, ...] = (), writes: tuple[str, ...] = ()
) -> Case:
    """A case that did `NOISE` and then `work`."""
    return Case(
        harness="claude-code",
        session=session or f"s{n}",
        task=f"TASK-{n}",
        kind="interactive",
        tool_calls=len(NOISE) + len(work),
        activities=(*NOISE, *work),
        reads=reads,
        writes=writes,
        skills=(),
        last_seen=float(n),
    )


def corpus() -> list[Case]:
    """Sixty cases: six of one kind of work, six of another, and the delivery noise every case does."""
    obs = [case(n, "bin/obs.py", "psql", "bin/obs.py") for n in range(6)]
    media = [case(n, "ffmpeg", writes=("media/encode",)) for n in range(6, 12)]
    return [*obs, *media, *(case(n) for n in range(12, 60))]


def test_partition_is_average_linkage_cut_below_the_threshold() -> None:
    a, b, c = {"x": 1.0}, {"x": 0.8, "y": 0.6}, {"y": 1.0}  # d(a,b)=.2, d(b,c)=.4, d(a,c)=1

    assert sorted(map(sorted, partition([a, b, c], 0.5))) == [[0, 1], [2]]  # single link would chain c in at .4
    assert sorted(map(sorted, partition([a, b, c], 0.8))) == [[0, 1, 2]]  # (1 + .4) / 2 = .7 < .8


def test_a_pair_exactly_the_threshold_apart_stays_apart() -> None:
    near = [{"x": 1.0}, {"x": 0.75, "y": math.sqrt(1 - 0.75**2)}]  # 1 - 0.75 is exactly 0.25

    assert partition(near, 0.25) == [[0], [1]]
    assert partition(near, 0.26) == [[0, 1]]


def test_lcs_length_is_the_longest_common_subsequence() -> None:
    assert lcs_length("abcbdab", "bdcaba") == 4
    assert lcs_length([], ["a"]) == 0
    rng = random.Random(7)
    for _ in range(200):
        a = [rng.choice("abcd") for _ in range(rng.randrange(12))]
        b = [rng.choice("abcd") for _ in range(rng.randrange(12))]
        table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i, x in enumerate(a):
            for j, y in enumerate(b):
                table[i + 1][j + 1] = table[i][j] + 1 if x == y else max(table[i][j + 1], table[i + 1][j])
        assert lcs_length(a, b) == table[-1][-1]


def test_recurring_work_is_a_cluster_and_the_delivery_every_case_does_is_not() -> None:
    found = trace_clusters(corpus())

    assert [(c.descriptors, len(c.cases)) for c in found] == [
        (("a:bin/obs.py", "a:psql"), 6),
        (("a:ffmpeg", "w:media/encode"), 6),
    ]


def test_a_cluster_key_is_the_digest_of_its_sorted_descriptors() -> None:
    [obs, _] = trace_clusters(corpus())

    assert cluster_key(obs) == hashlib.sha1(b"a:bin/obs.py|a:psql").hexdigest()[:12]
    assert cluster_key(obs) == "05fcaeed5e96"


def test_clusters_rank_by_distinct_sessions_not_by_cases() -> None:
    # six cases of one session's work on six tasks is one session of recurrence; five sessions of media work are five.
    repeated = [case(n, "bin/obs.py", "psql", session="one") for n in range(6)]
    media = [case(n, "ffmpeg", session=f"m{n}") for n in range(6, 11)]
    found = trace_clusters([*repeated, *media, *(case(n) for n in range(11, 60))])

    assert [(c.descriptors[0], c.sessions, len(c.cases)) for c in found] == [("a:ffmpeg", 5, 5), ("a:bin/obs.py", 1, 6)]


def test_a_stop_activity_never_defines_a_cluster_and_a_case_left_with_no_feature_joins_none() -> None:
    cases = [case(n, "ScheduleWakeup") for n in range(6)] + [case(n) for n in range(6, 60)]

    assert trace_clusters(cases, stop=frozenset({"ScheduleWakeup"})) == []
    assert [c.descriptors for c in trace_clusters(cases)] == [("a:ScheduleWakeup",)]


def test_a_case_with_no_tool_call_is_not_clustered() -> None:
    idle = [Case("h", f"i{n}", None, "unknown", 0, ("ffmpeg",), (), (), (), 0.0) for n in range(6)]

    assert trace_clusters([*idle, *(case(n) for n in range(54))]) == []


@pytest.mark.parametrize("size", [0, 1])
def test_fewer_than_two_cases_have_no_clusters(size: int) -> None:
    assert trace_clusters([case(n, "ffmpeg") for n in range(size)]) == []


def _traced(session: str, *activities: str) -> Case:
    return Case("claude-code", session, None, "interactive", len(activities), activities, (), (), (), 0.0)


def test_dispersion_names_the_medoid_and_each_outliers_edits_from_it() -> None:
    cluster = Cluster(
        (
            _traced("a", "x", "y", "z"),
            _traced("b", "x", "y", "z"),
            _traced("c", "x", "z", "w"),
            _traced("d", "q", "r", "s"),
        ),
        ("a:x",),
    )

    found = dispersion(cluster, 2)

    assert found.medoid.session == "a"  # the first of the two cases nearest every other
    assert found.median == pytest.approx(1 / 3)  # distances from a: b 0, c 1/3, d 1
    assert [(o.case.session, o.distance, o.deletions, o.insertions) for o in found.outliers] == [
        ("d", 1.0, ("x", "y", "z"), ("q", "r", "s")),
        ("c", pytest.approx(1 / 3), ("y",), ("w",)),
    ]


def test_dispersion_compares_traces_without_stop_activities_or_adjacent_repeats() -> None:
    cluster = Cluster((_traced("a", "x", "Skill", "x", "y"), _traced("b", "x", "y", "y")), ())

    found = dispersion(cluster, 1, stop=frozenset({"Skill"}))

    assert [(o.distance, o.deletions, o.insertions) for o in found.outliers] == [(0.0, (), ())]


def test_a_cluster_of_one_has_a_medoid_and_no_spread() -> None:
    found = dispersion(Cluster((_traced("a", "x"),), ()), 3)

    assert (found.medoid.session, found.median, found.outliers) == ("a", 0.0, ())
