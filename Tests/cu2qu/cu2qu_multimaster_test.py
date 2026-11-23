"""Tests for cu2qu's multi-master (interpolation compatible) conversion.

``curves_to_quadratic`` converts several cubics at once so that the resulting
quadratic splines can be interpolated: every master must come out with the
same number of segments and the same segment boundaries.  The cases below are
grouped as follows:

1. masters with compatible point counts but different curvature, where the
   segment count is driven by the "hardest" master;
2. per-master error arrays, ``all_quadratic`` on/off, already-quadratic and
   degenerate inputs;
3. assertions that tell "geometry is within tolerance but the topology is
   not shared" apart from a genuine synchronisation failure, plus guards for
   the single-curve API and the UFO/pen conversion paths.
"""

import math
import random

import pytest

from fontTools.cu2qu import curve_to_quadratic, curves_to_quadratic
from fontTools.cu2qu.errors import ApproxNotFoundError
from fontTools.pens.cu2quPen import Cu2QuMultiPen
from fontTools.pens.recordingPen import RecordingPen

from cu2qu_multimaster_utils import (
    assert_common_topology,
    assert_endpoints_preserved,
    assert_result_within_tolerance,
    assert_within_tolerance,
    max_deviation,
    segment_counts,
    topology_mismatch,
)

# Masters of a single (synthetic) letter, all running from x=0 to x=120 (or
# 90) with four control points, i.e. the same point count.  Their curvature
# covers the range from "almost a straight line" to "two inflections with
# large handles", so each one needs a different number of quadratic segments
# when converted on its own.
GENTLE = [(0, 0), (40, 15), (80, 15), (120, 0)]
ARCH = [(0, 0), (40, 80), (80, 80), (120, 0)]
S_CURVE = [(0, 0), (30, 60), (60, -60), (90, 0)]
ASYM = [(0, 0), (70, 25), (100, 5), (120, 0)]
TIGHT = [(0, 0), (20, 100), (40, -100), (60, 0)]
FAMILY = [GENTLE, ARCH, S_CURVE, ASYM, TIGHT]

# A cubic that is exactly a degree-elevated quadratic: converting it must give
# back a single quadratic segment, no matter how tight the tolerance is.
ELEVATED_QUADRATIC = [(0, 0), (50, 40), (100, 40), (150, 0)]
# Same, in the 0..120 coordinate space of FAMILY.
ELEVATED_QUADRATIC_120 = [(0, 0), (40, 32), (80, 32), (120, 0)]

# Degenerate cubics used by the single-curve tests (see cu2qu_test.py).
ALL_POINTS_EQUAL = [(5, 5), (5, 5), (5, 5), (5, 5)]
THREE_POINTS_EQUAL = [(5, 5), (5, 5), (5, 5), (5, 5.1)]
COLLINEAR = [
    (64.94, 550.998),
    (65.199, 550.032),
    (65.199, 550.032),
    (65.458, 549.066),
]
# A curve whose handles cross so violently that no spline up to MAX_N
# segments approximates it at an absurdly tight tolerance.
UNFITTABLE = [(0, 0), (1000, 1000), (-1000, 1000), (0, 0)]

ERROR_SET_VALUES = {
    "uniform-1.0": [1.0] * 5,
    "heterogeneous-a": [0.5, 1.0, 2.0, 5.0, 1.0],
    "heterogeneous-b": [5.0, 1.0, 2.0, 0.5, 1.0],
    "heterogeneous-c": [0.1, 10.0, 2.0, 1.0, 5.0],
    "uniform-2.0": [2.0] * 5,
    "uniform-10.0": [10.0] * 5,
}
# Pinned number of segments each of the above must produce.  These are
# regression values: they were verified by hand against a per-master
# conversion, and they must not silently drift.
EXPECTED_SYNC_SEGMENTS = {
    "uniform-1.0": 6,
    "heterogeneous-a": 6,
    "heterogeneous-b": 6,
    "heterogeneous-c": 4,
    "uniform-2.0": 5,
    "uniform-10.0": 3,
}


# ---------------------------------------------------------------------------
# 1. Compatible point counts, different curvature
# ---------------------------------------------------------------------------


def test_single_conversion_needs_different_segment_counts():
    """Sanity check on the fixtures: on its own, each master is converted with
    a different number of segments, so any shared count has to come from the
    synchronisation logic rather than from the inputs being alike."""
    counts = [len(curve_to_quadratic(curve, 1.0)) - 2 for curve in FAMILY]
    assert counts == [1, 1, 5, 3, 6]


@pytest.mark.parametrize("case", list(ERROR_SET_VALUES))
def test_synchronised_segment_count(case):
    """All masters come out with the same number of segments, equal to the
    largest count any single master needs."""
    max_errors = ERROR_SET_VALUES[case]
    singles = [curve_to_quadratic(curve, err) for curve, err in zip(FAMILY, max_errors)]
    expected = max(len(single) for single in singles)

    results = curves_to_quadratic(FAMILY, max_errors)

    assert_common_topology(results)
    assert segment_counts(results) == [EXPECTED_SYNC_SEGMENTS[case]] * len(FAMILY)
    # The shared topology is the one dictated by the hardest master: no master
    # gets fewer points than it needs on its own.
    assert len(results[0]) == expected


@pytest.mark.parametrize("case", list(ERROR_SET_VALUES))
def test_synchronised_splines_start_and_end_on_the_cubic_endpoints(case):
    """Synchronisation must not move the masters' on-curve end points."""
    results = curves_to_quadratic(FAMILY, ERROR_SET_VALUES[case])
    for curve, spline in zip(FAMILY, results):
        assert_endpoints_preserved(curve, spline)


@pytest.mark.parametrize("case", list(ERROR_SET_VALUES))
def test_each_master_respects_its_own_tolerance(case):
    """Every master is checked against its own ``max_err``: a shared topology
    is only acceptable if the extra segments also keep each master accurate."""
    max_errors = ERROR_SET_VALUES[case]
    results = curves_to_quadratic(FAMILY, max_errors)
    for name, curve, err, spline in zip(
        ["gentle", "arch", "s-curve", "asymmetric", "tight"],
        FAMILY,
        max_errors,
        results,
    ):
        deviation = assert_within_tolerance(curve, spline, err, context=name)
        assert math.isfinite(deviation)


def test_hardest_master_keeps_its_single_curve_result():
    """The master that dictates the segment count is approximated exactly as
    it would be on its own; the other masters are the ones that pay for the
    shared topology."""
    singles = [curve_to_quadratic(curve, 1.0) for curve in FAMILY]
    binding = max(range(len(FAMILY)), key=lambda i: len(singles[i]))
    assert binding == len(FAMILY) - 1  # TIGHT

    results = curves_to_quadratic(FAMILY, [1.0] * len(FAMILY))

    assert results[binding] == singles[binding]
    # Every other master was split further than it needed to be.
    for i, (single, result) in enumerate(zip(singles, results)):
        if i != binding:
            assert len(result) > len(single)


def test_shared_topology_follows_the_hardest_master_not_the_first():
    """Reordering the masters must not change the resulting splines."""
    errors = [5.0, 1.0, 2.0, 0.5, 1.0]
    baseline = curves_to_quadratic(FAMILY, errors)
    # TIGHT (the binding master) first, the easiest last.
    order = [4, 3, 2, 1, 0]
    reordered = curves_to_quadratic(
        [FAMILY[i] for i in order], [errors[i] for i in order]
    )
    for new_position, old_position in enumerate(order):
        assert reordered[new_position] == baseline[old_position]


def test_all_masters_share_the_same_interpolatable_spline_length():
    """Every result is a full spline (n + 2 points) of the same length, so
    master pairs can be blended point by point."""
    results = curves_to_quadratic(FAMILY, [0.5, 1.0, 2.0, 5.0, 1.0])
    lengths = {len(result) for result in results}
    assert len(lengths) == 1
    assert len(results[0]) == len(results[1]) == len(results[-1])


# ---------------------------------------------------------------------------
# 2a. all_quadratic on and off
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", list(ERROR_SET_VALUES))
def test_all_quadratic_false_shares_the_topology_too(case):
    """With ``all_quadratic=False`` the loop stops at n=2 (returning the input
    cubic), which is the cheapest topology that can still be interpolated, so
    the same synchronisation guarantee must hold."""
    results = curves_to_quadratic(FAMILY, ERROR_SET_VALUES[case], all_quadratic=False)
    assert_common_topology(results)
    assert segment_counts(results) == [2] * len(FAMILY)


def test_all_quadratic_false_returns_every_master_as_its_own_cubic():
    """With ``all_quadratic=False`` the search stops at n=2, where the source
    cubic is returned unconditionally.  The synchronisation loop therefore
    converges on "keep the cubics" for the whole group, even though some
    masters (GENTLE, ARCH) could have been a single quadratic."""
    results = curves_to_quadratic(FAMILY, [10.0] * len(FAMILY), all_quadratic=False)
    assert [len(result) for result in results] == [4] * len(FAMILY)
    for curve, result in zip(FAMILY, results):
        assert result == [tuple(map(float, point)) for point in curve]


def test_all_quadratic_false_keeps_a_group_of_quadratics_quadratic():
    """When every master fits in a single quadratic, no cubic is reintroduced."""
    group = [GENTLE, ARCH, ELEVATED_QUADRATIC_120]
    results = curves_to_quadratic(group, [1.0, 1.0, 1e-3], all_quadratic=False)
    assert_common_topology(results)
    assert [len(result) for result in results] == [3, 3, 3]
    assert results[0] == curve_to_quadratic(GENTLE, 1.0, all_quadratic=False)
    assert results[1] == curve_to_quadratic(ARCH, 1.0, all_quadratic=False)


def test_all_quadratic_toggle_changes_what_a_two_segment_fit_looks_like():
    """``all_quadratic=False`` caps the search at n=2, where a cubic is
    returned verbatim; the group is still synchronised, just as cubics.  With
    ``all_quadratic=True`` the same group gets a quadratic spline long enough
    for the tightest master."""
    true_results = curves_to_quadratic([GENTLE, S_CURVE], [0.1, 1.0])
    false_results = curves_to_quadratic(
        [GENTLE, S_CURVE], [0.1, 1.0], all_quadratic=False
    )

    assert_common_topology(true_results)
    assert_common_topology(false_results)
    assert segment_counts(true_results) == [5, 5]
    assert [len(result) for result in false_results] == [4, 4]
    for curve, result in zip([GENTLE, S_CURVE], false_results):
        assert result == [tuple(map(float, point)) for point in curve]
    for curve, err, spline in zip([GENTLE, S_CURVE], [0.1, 1.0], true_results):
        assert_result_within_tolerance(curve, spline, err, all_quadratic=True)


# ---------------------------------------------------------------------------
# 2b. Already quadratic inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("all_quadratic", [True, False])
def test_degree_elevated_quadratic_stays_a_single_quadratic(all_quadratic):
    result = curve_to_quadratic(ELEVATED_QUADRATIC, 1e-3, all_quadratic=all_quadratic)
    assert result == pytest.approx([(0, 0), (75, 60), (150, 0)])


@pytest.mark.parametrize(
    "all_quadratic, expected_points, expected_segments",
    [
        pytest.param(True, [7, 7], [5, 5], id="quadratic-spline"),
        pytest.param(False, [4, 4], [2, 2], id="cubics"),
    ],
)
def test_degree_elevated_quadratic_is_resplit_to_match_a_curvier_master(
    all_quadratic, expected_points, expected_segments
):
    """An already-quadratic master is not special-cased: it is resplit to the
    common topology.  With ``all_quadratic=False`` the shared topology is the
    cubic itself, so no split happens at all."""
    group = [ELEVATED_QUADRATIC_120, S_CURVE]
    errors = [1e-3, 1.0]
    results = curves_to_quadratic(group, errors, all_quadratic=all_quadratic)

    assert_common_topology(results)
    assert [len(result) for result in results] == expected_points
    assert segment_counts(results) == expected_segments
    # On its own the elevated quadratic is a single segment; the shared spline
    # is longer, and still a perfect fit.
    assert len(curve_to_quadratic(ELEVATED_QUADRATIC_120, 1e-3)) == 3
    for curve, err, result in zip(group, errors, results):
        assert_result_within_tolerance(curve, result, err, all_quadratic=all_quadratic)
    if all_quadratic:
        assert max_deviation(ELEVATED_QUADRATIC_120, results[0]) == pytest.approx(
            0, abs=1e-9
        )


def test_group_of_only_already_quadratic_masters():
    group = [GENTLE, ARCH, ELEVATED_QUADRATIC_120]
    errors = [1.0, 1.0, 1e-3]
    results = curves_to_quadratic(group, errors)
    assert_common_topology(results)
    assert segment_counts(results) == [1, 1, 1]
    for curve, err, spline in zip(group, errors, results):
        assert_result_within_tolerance(curve, spline, err)


# ---------------------------------------------------------------------------
# 2c. Degenerate curves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("all_quadratic", [True, False])
def test_degenerate_masters_join_the_common_topology(all_quadratic):
    """A curve whose four points coincide is a valid master: on its own it
    collapses to one (or two) segments, but next to a curvier master it takes
    the shared spline length without breaking."""
    group = [ALL_POINTS_EQUAL, THREE_POINTS_EQUAL, S_CURVE]
    results = curves_to_quadratic(group, [0.1] * 3, all_quadratic=all_quadratic)

    assert_common_topology(results)
    if all_quadratic:
        assert segment_counts(results) == [10, 10, 10]
    else:
        assert segment_counts(results) == [2, 2, 2]
    for curve, spline in zip(group, results):
        assert_endpoints_preserved(curve, spline)
        assert_result_within_tolerance(curve, spline, 0.1, all_quadratic=all_quadratic)


@pytest.mark.parametrize(
    "max_err, expected_lengths",
    [
        pytest.param(0.1, [3, 3], id="coarse"),
        pytest.param(0.01, [4, 4], id="tight"),
    ],
)
def test_collapsed_group_is_still_synchronised(max_err, expected_lengths):
    """Both degenerate masters collapse to the same spline length when they
    are the only inputs."""
    results = curves_to_quadratic(
        [ALL_POINTS_EQUAL, THREE_POINTS_EQUAL], [max_err, max_err]
    )
    assert_common_topology(results)
    assert [len(result) for result in results] == expected_lengths


def test_collinear_degenerate_master():
    """A cubic whose four points are collinear is still converted and still
    synchronised with a well-behaved master."""
    results = curves_to_quadratic([COLLINEAR, S_CURVE], [1.0, 1.0])
    assert_common_topology(results)
    assert segment_counts(results) == [5, 5]
    assert_endpoints_preserved(COLLINEAR, results[0])
    assert_within_tolerance(COLLINEAR, results[0], 1.0)
    assert_within_tolerance(S_CURVE, results[1], 1.0)


def test_degenerate_master_alone_matches_single_curve_api():
    """Regression guard: a collapsed curve in a one-element group produces the
    same result as ``curve_to_quadratic``."""
    for curve in (ALL_POINTS_EQUAL, THREE_POINTS_EQUAL):
        assert curves_to_quadratic([curve], [0.01]) == [curve_to_quadratic(curve, 0.01)]


# ---------------------------------------------------------------------------
# 3a. Telling topology failures apart from geometric failures
# ---------------------------------------------------------------------------


def test_topology_helpers_distinguish_mismatch_from_geometric_error():
    """The helpers used above must be able to express the two failure modes
    independently: a list of splines can satisfy every master's tolerance and
    still be unusable because the segment counts differ."""
    fitted = [curve_to_quadratic(curve, 1.0) for curve in [GENTLE, S_CURVE]]
    # Each spline is a perfect fit for its own master...
    assert max_deviation(GENTLE, fitted[0]) < 1.0
    assert max_deviation(S_CURVE, fitted[1]) < 1.0
    # ... but the pair is not interpolatable.
    assert topology_mismatch(fitted) == [1, 5]
    with pytest.raises(AssertionError, match="disagree on the number of"):
        assert_common_topology(fitted, context="hand-built")
    # The real conversion fixes exactly that, without changing the geometry.
    synced = curves_to_quadratic([GENTLE, S_CURVE], [1.0, 1.0])
    assert_common_topology(synced)
    assert segment_counts(synced) == [5, 5]


def test_synchronised_result_reports_geometry_errors_separately():
    """When a master's tolerance is impossible to satisfy, the failure is an
    ``ApproxNotFoundError`` from the single-master algorithm, not a topology
    mismatch: the exception carries the offending curve."""
    with pytest.raises(ApproxNotFoundError) as excinfo:
        curves_to_quadratic([GENTLE, UNFITTABLE], [1.0, 1e-9])
    # The error is raised for the whole group, and the message contains the
    # curves rather than a segment count complaint.
    assert "no approximation found" in str(excinfo.value)
    assert "segments" not in str(excinfo.value)
    # The same curve on its own fails identically; the synchronisation loop
    # did not mask or reinterpret the error.
    with pytest.raises(ApproxNotFoundError):
        curve_to_quadratic(UNFITTABLE, 1e-9)


def test_large_segment_counts_stay_synchronised_and_accurate():
    """Tight tolerances push the shared count well past the single-curve counts
    of the easy masters; every master must still be accurate."""
    errors = [1e-3, 1e-3, 1e-3]
    group = [S_CURVE, GENTLE, ARCH]
    results = curves_to_quadratic(group, errors)
    assert_common_topology(results)
    assert segment_counts(results) == [47, 47, 47]
    for curve, spline in zip(group, results):
        assert_within_tolerance(curve, spline, 1e-3)


def test_randomised_family_invariants():
    """Seeded random masters: the shared count is always the maximum of the
    single-curve counts and every master stays inside its own tolerance."""
    rng = random.Random(20240531)
    for _ in range(15):
        size = rng.choice([2, 3, 4])
        masters = [
            [
                (round(rng.uniform(0, 100), 3), round(rng.uniform(0, 100), 3))
                for _ in range(4)
            ]
            for _ in range(size)
        ]
        errors = [rng.choice([0.1, 1.0, 10.0]) for _ in range(size)]
        singles = [
            curve_to_quadratic(curve, err) for curve, err in zip(masters, errors)
        ]
        expected = max(len(single) - 2 for single in singles)

        results = curves_to_quadratic(masters, errors)

        assert_common_topology(results)
        assert segment_counts(results) == [expected] * size
        for curve, err, spline in zip(masters, errors, results):
            assert_within_tolerance(curve, spline, err)


# ---------------------------------------------------------------------------
# 3b. Guards for the single-curve API and the pen/UFO conversion paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("all_quadratic", [True, False])
@pytest.mark.parametrize("max_err", [0.01, 0.1, 1.0, 10.0])
def test_one_element_group_matches_curve_to_quadratic(all_quadratic, max_err):
    """``curves_to_quadratic`` with a single curve is exactly
    ``curve_to_quadratic``; the synchronisation loop must not perturb it."""
    curves = FAMILY + [
        ELEVATED_QUADRATIC,
        ALL_POINTS_EQUAL,
        THREE_POINTS_EQUAL,
        COLLINEAR,
    ]
    for curve in curves:
        expected = curve_to_quadratic(curve, max_err, all_quadratic=all_quadratic)
        actual = curves_to_quadratic([curve], [max_err], all_quadratic=all_quadratic)
        assert actual == [expected]


def test_single_curve_api_is_unaffected_by_the_group_size():
    """The same curve converted alone, and as the easy member of a pair, has
    the same endpoints and a spline that is at least as accurate."""
    alone = curve_to_quadratic(GENTLE, 1.0)
    in_group = curves_to_quadratic([GENTLE, S_CURVE], [1.0, 1.0])[0]

    assert len(alone) == 3
    assert len(in_group) == 7
    assert in_group[0] == pytest.approx(alone[0])
    assert in_group[-1] == pytest.approx(alone[-1])
    assert max_deviation(GENTLE, in_group) <= max_deviation(GENTLE, alone) + 1e-9


def test_multi_pen_shares_topology_across_pens():
    """``Cu2QuMultiPen`` goes through ``curves_to_quadratic``; the two output
    pens must receive the same number of off-curves."""
    pens = [RecordingPen(), RecordingPen()]
    pen = Cu2QuMultiPen(pens, 1.0)
    pen.moveTo([((0, 0),), ((0, 0),)])
    pen.curveTo([tuple(GENTLE[1:]), tuple(S_CURVE[1:])])
    pen.closePath()

    offcurve_counts = []
    for recording, curve in zip(pens, [GENTLE, S_CURVE]):
        qcurves = [args for op, args in recording.value if op == "qCurveTo"]
        assert len(qcurves) == 1
        # qCurveTo''s last argument is the on-curve end point.
        spline = [(0, 0)] + list(qcurves[0])
        offcurve_counts.append(len(spline) - 2)
        assert_endpoints_preserved(curve, spline)
    assert offcurve_counts == [5, 5]


def test_multi_pen_uses_synchronised_topology_from_curves_to_quadratic():
    """The pen's output for each master equals the library result for the
    corresponding curve."""
    pens = [RecordingPen(), RecordingPen()]
    pen = Cu2QuMultiPen(pens, 0.1)
    pen.moveTo([((0, 0),), ((0, 0),)])
    pen.curveTo([tuple(GENTLE[1:]), tuple(S_CURVE[1:])])
    pen.closePath()

    expected = curves_to_quadratic([GENTLE, S_CURVE], [0.1, 0.1])
    for recording, spline in zip(pens, expected):
        qcurve = [args for op, args in recording.value if op == "qCurveTo"][0]
        assert list(qcurve) == pytest.approx(list(spline[1:]))
