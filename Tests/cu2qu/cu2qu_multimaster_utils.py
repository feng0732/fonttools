"""Helpers shared by the tests that exercise cu2qu's multi-master support.

``curves_to_quadratic`` converts several (supposedly interpolation
compatible) cubics *at once* so that the resulting quadratic splines share a
common topology: same number of points, same segment boundaries.  The helpers
below keep the two aspects of that contract apart on purpose:

* :func:`assert_common_topology` / :func:`topology_mismatch` only look at the
  number of segments.  A conversion can be geometrically perfect for every
  master and still be useless for interpolation if these numbers differ.
* :func:`max_deviation` measures how far an individual master's spline strays
  from its source cubic, i.e. whether *that* master's ``max_err`` was honoured.

Tests that distinguish "tolerance satisfied but segment counts differ" from an
actual synchronisation failure combine the two.
"""

import math


def segment_counts(results):
    """Return the number of quadratic segments in each spline of ``results``.

    A cu2qu spline is stored as ``n + 2`` points (start point, ``n``
    off-curve points, end point), so the segment count is ``len(spline) - 2``.
    """
    return [len(spline) - 2 for spline in results]


def topology_mismatch(results):
    """Return per-master segment counts if they are not all equal, else None."""
    counts = segment_counts(results)
    return counts if len(set(counts)) != 1 else None


def assert_common_topology(results, context=None):
    """Assert that all splines share the same number of segments.

    This is the synchronisation contract of ``curves_to_quadratic``; it is
    deliberately independent of any geometric error check, so that a failure
    here is reported as "the masters were not synchronised" rather than as
    "the approximation was not accurate enough".
    """
    counts = topology_mismatch(results)
    assert counts is None, "%s: masters disagree on the number of quadratic " \
        "segments: %r" % (context or "curves_to_quadratic", counts)


def _midpoint(p0, p1):
    return ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)


def _cubic_at(curve, t):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve
    mt = 1.0 - t
    t2 = t * t
    mt2 = mt * mt
    a = mt2 * mt
    b = 3.0 * t * mt2
    c = 3.0 * t2 * mt
    d = t2 * t
    return (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)


def _quadratic_at(segment, t):
    (x0, y0), (x1, y1), (x2, y2) = segment
    mt = 1.0 - t
    a = mt * mt
    b = 2.0 * t * mt
    c = t * t
    return (a * x0 + b * x1 + c * x2, a * y0 + b * y1 + c * y2)


def spline_segments(spline):
    """Expand a cu2qu quadratic spline into explicit 3-point segments.

    ``spline`` is the list of ``n + 2`` points returned by cu2qu.  Consecutive
    off-curve points imply on-curve points halfway between them, exactly as in
    a TrueType ``glyf`` outline.

    Returns a list of ``(on_curve_start, off_curve, on_curve_end)`` triples.
    """
    points = [(float(x), float(y)) for x, y in spline]
    n = len(points) - 2
    assert n >= 1, "expected at least one quadratic segment, got %r" % (spline,)
    on_curve = [points[0]]
    for i in range(1, n):
        on_curve.append(_midpoint(points[i], points[i + 1]))
    on_curve.append(points[n + 1])
    return [(on_curve[i], points[i + 1], on_curve[i + 1]) for i in range(n)]


def max_deviation(cubic, spline, samples=32):
    """Maximum parametric distance between ``cubic`` and ``spline``.

    The cubic is sampled at ``(segment_index + t) / n`` in lockstep with the
    corresponding quadratic segment evaluated at ``t``.  This is the quantity
    ``cubic_approx_spline`` bounds with ``max_err`` (it is not a nearest-point
    distance, which would only make a spline look better).
    """
    segments = spline_segments(spline)
    n = len(segments)
    worst = 0.0
    for i, segment in enumerate(segments):
        for step in range(samples + 1):
            t = step / samples
            expected = _cubic_at(cubic, (i + t) / n)
            actual = _quadratic_at(segment, t)
            worst = max(
                worst, math.hypot(actual[0] - expected[0], actual[1] - expected[1])
            )
    return worst


def assert_within_tolerance(cubic, spline, max_err, context=None):
    """Assert that this particular master's approximation honours ``max_err``."""
    deviation = max_deviation(cubic, spline)
    assert deviation <= max_err + 1e-9, (
        "%s: geometric error %.6g exceeds the master's tolerance %.6g"
        % (context or "spline", deviation, max_err)
    )
    return deviation


def assert_endpoints_preserved(cubic, spline):
    """The first and last point must match the source cubic's on-curves."""
    assert tuple(spline[0]) == (float(cubic[0][0]), float(cubic[0][1]))
    assert tuple(spline[-1]) == (float(cubic[3][0]), float(cubic[3][1]))
    assert math.isfinite(spline[0][0]) and math.isfinite(spline[-1][1])


def assert_result_within_tolerance(
    cubic, result, max_err, all_quadratic=True, context=None
):
    """Check a conversion result against the master's tolerance.

    With ``all_quadratic=False``, cu2qu returns the source cubic unchanged
    (four points) when two segments would be enough; such a result is exact by
    construction and must not be measured as if it were a quadratic spline.  A
    four-point result in that mode that is *not* the source cubic is rejected
    explicitly.  With ``all_quadratic=True`` a four-point result is a genuine
    two-segment spline and is measured like any other.
    """
    if not all_quadratic and len(result) == 4:
        expected = [tuple(map(float, point)) for point in cubic]
        assert [tuple(map(float, point)) for point in result] == expected, (
            "%s: four-point result is neither the source cubic nor a spline"
            % (context or "spline")
        )
        return 0.0
    return assert_within_tolerance(cubic, result, max_err, context=context)
