from fontTools.varLib.models import (
    normalizeLocation,
    normalizeValue,
    supportScalar,
    VariationModel,
    VariationModelError,
)
from fontTools.varLib import instancer
import pytest


def test_normalizeLocation():
    axes = {"wght": (100, 400, 900)}
    assert normalizeLocation({"wght": 400}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": 100}, axes) == {"wght": -1.0}
    assert normalizeLocation({"wght": 900}, axes) == {"wght": 1.0}
    assert normalizeLocation({"wght": 650}, axes) == {"wght": 0.5}
    assert normalizeLocation({"wght": 1000}, axes) == {"wght": 1.0}
    assert normalizeLocation({"wght": 0}, axes) == {"wght": -1.0}

    axes = {"wght": (0, 0, 1000)}
    assert normalizeLocation({"wght": 0}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": -1}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": 1000}, axes) == {"wght": 1.0}
    assert normalizeLocation({"wght": 500}, axes) == {"wght": 0.5}
    assert normalizeLocation({"wght": 1001}, axes) == {"wght": 1.0}

    axes = {"wght": (0, 1000, 1000)}
    assert normalizeLocation({"wght": 0}, axes) == {"wght": -1.0}
    assert normalizeLocation({"wght": -1}, axes) == {"wght": -1.0}
    assert normalizeLocation({"wght": 500}, axes) == {"wght": -0.5}
    assert normalizeLocation({"wght": 1000}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": 1001}, axes) == {"wght": 0.0}


@pytest.mark.parametrize(
    "axes, location, expected",
    [
        # lower != default != upper
        ({"wght": (100, 400, 900)}, {"wght": 1000}, {"wght": 1.2}),
        ({"wght": (100, 400, 900)}, {"wght": 900}, {"wght": 1.0}),
        ({"wght": (100, 400, 900)}, {"wght": 650}, {"wght": 0.5}),
        ({"wght": (100, 400, 900)}, {"wght": 400}, {"wght": 0.0}),
        ({"wght": (100, 400, 900)}, {"wght": 250}, {"wght": -0.5}),
        ({"wght": (100, 400, 900)}, {"wght": 100}, {"wght": -1.0}),
        ({"wght": (100, 400, 900)}, {"wght": 25}, {"wght": -1.25}),
        # lower == default != upper
        (
            {"wght": (400, 400, 900), "wdth": (100, 100, 150)},
            {"wght": 1000, "wdth": 200},
            {"wght": 1.2, "wdth": 2.0},
        ),
        (
            {"wght": (400, 400, 900), "wdth": (100, 100, 150)},
            {"wght": 25, "wdth": 25},
            {"wght": -0.75, "wdth": -1.5},
        ),
        # lower != default == upper
        (
            {"wght": (100, 400, 400), "wdth": (50, 100, 100)},
            {"wght": 700, "wdth": 150},
            {"wght": 1.0, "wdth": 1.0},
        ),
        (
            {"wght": (100, 400, 400), "wdth": (50, 100, 100)},
            {"wght": -50, "wdth": 25},
            {"wght": -1.5, "wdth": -1.5},
        ),
        # degenerate case with lower == default == upper, normalized location always 0
        ({"wght": (400, 400, 400)}, {"wght": 100}, {"wght": 0.0}),
        ({"wght": (400, 400, 400)}, {"wght": 400}, {"wght": 0.0}),
        ({"wght": (400, 400, 400)}, {"wght": 700}, {"wght": 0.0}),
    ],
)
def test_normalizeLocation_extrapolate(axes, location, expected):
    assert normalizeLocation(location, axes, extrapolate=True) == expected


def test_supportScalar():
    assert supportScalar({}, {}) == 1.0
    assert supportScalar({"wght": 0.2}, {}) == 1.0
    assert supportScalar({"wght": 0.2}, {"wght": (0, 2, 3)}) == 0.1
    assert supportScalar({"wght": 2.5}, {"wght": (0, 2, 4)}) == 0.75
    assert supportScalar({"wght": 3}, {"wght": (0, 2, 2)}) == 0.0
    assert (
        supportScalar(
            {"wght": 3},
            {"wght": (0, 2, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == 1.5
    )
    assert (
        supportScalar(
            {"wght": -1},
            {"wght": (0, 2, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == -0.5
    )
    assert (
        supportScalar(
            {"wght": 3},
            {"wght": (0, 1, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == -1.0
    )
    assert (
        supportScalar(
            {"wght": -1},
            {"wght": (0, 1, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == -1.0
    )
    assert (
        supportScalar(
            {"wght": 2},
            {"wght": (0, 0.75, 1)},
            extrapolate=True,
            axisRanges={"wght": (0, 1)},
        )
        == -4.0
    )
    with pytest.raises(TypeError):
        supportScalar(
            {"wght": 2}, {"wght": (0, 0.75, 1)}, extrapolate=True, axisRanges=None
        )


def test_model_extrapolate():
    locations = [{}, {"a": 1}, {"b": 1}, {"a": 1, "b": 1}]
    model = VariationModel(locations, extrapolate=True)
    masterValues = [100, 200, 300, 400]
    testLocsAndValues = [
        ({"a": -1, "b": -1}, -200),
        ({"a": -1, "b": 0}, 0),
        ({"a": -1, "b": 1}, 200),
        ({"a": -1, "b": 2}, 400),
        ({"a": 0, "b": -1}, -100),
        ({"a": 0, "b": 0}, 100),
        ({"a": 0, "b": 1}, 300),
        ({"a": 0, "b": 2}, 500),
        ({"a": 1, "b": -1}, 0),
        ({"a": 1, "b": 0}, 200),
        ({"a": 1, "b": 1}, 400),
        ({"a": 1, "b": 2}, 600),
        ({"a": 2, "b": -1}, 100),
        ({"a": 2, "b": 0}, 300),
        ({"a": 2, "b": 1}, 500),
        ({"a": 2, "b": 2}, 700),
    ]
    for loc, expectedValue in testLocsAndValues:
        assert expectedValue == model.interpolateFromMasters(loc, masterValues)


@pytest.mark.parametrize(
    "numLocations, numSamples",
    [
        pytest.param(127, 509, marks=pytest.mark.slow),
        (31, 251),
    ],
)
def test_modeling_error(numLocations, numSamples):
    # https://github.com/fonttools/fonttools/issues/2213
    locations = [{"axis": float(i) / numLocations} for i in range(numLocations)]
    masterValues = [100.0 if i else 0.0 for i in range(numLocations)]

    model = VariationModel(locations)

    for i in range(numSamples):
        loc = {"axis": float(i) / numSamples}
        scalars = model.getScalars(loc)

        deltas_float = model.getDeltas(masterValues)
        deltas_round = model.getDeltas(masterValues, round=round)

        expected = model.interpolateFromDeltasAndScalars(deltas_float, scalars)
        actual = model.interpolateFromDeltasAndScalars(deltas_round, scalars)

        err = abs(actual - expected)
        assert err <= 0.5, (i, err)

        # This is how NOT to round deltas.
        # deltas_late_round = [round(d) for d in deltas_float]
        # bad = model.interpolateFromDeltasAndScalars(deltas_late_round, scalars)
        # err_bad = abs(bad - expected)
        # if err != err_bad:
        #    print("{:d}	{:.2}	{:.2}".format(i, err, err_bad))


locationsA = [{}, {"wght": 1}, {"wdth": 1}]
locationsB = [{}, {"wght": 1}, {"wdth": 1}, {"wght": 1, "wdth": 1}]
locationsC = [
    {},
    {"wght": 0.5},
    {"wght": 1},
    {"wdth": 1},
    {"wght": 1, "wdth": 1},
]


class VariationModelTest(object):
    @pytest.mark.parametrize(
        "locations, axisOrder, sortedLocs, supports, deltaWeights",
        [
            (
                [
                    {"wght": 0.55, "wdth": 0.0},
                    {"wght": -0.55, "wdth": 0.0},
                    {"wght": -1.0, "wdth": 0.0},
                    {"wght": 0.0, "wdth": 1.0},
                    {"wght": 0.66, "wdth": 1.0},
                    {"wght": 0.66, "wdth": 0.66},
                    {"wght": 0.0, "wdth": 0.0},
                    {"wght": 1.0, "wdth": 1.0},
                    {"wght": 1.0, "wdth": 0.0},
                ],
                ["wght"],
                [
                    {},
                    {"wght": -0.55},
                    {"wght": -1.0},
                    {"wght": 0.55},
                    {"wght": 1.0},
                    {"wdth": 1.0},
                    {"wdth": 1.0, "wght": 1.0},
                    {"wdth": 1.0, "wght": 0.66},
                    {"wdth": 0.66, "wght": 0.66},
                ],
                [
                    {},
                    {"wght": (-1.0, -0.55, 0)},
                    {"wght": (-1.0, -1.0, -0.55)},
                    {"wght": (0, 0.55, 1.0)},
                    {"wght": (0.55, 1.0, 1.0)},
                    {"wdth": (0, 1.0, 1.0)},
                    {"wdth": (0, 1.0, 1.0), "wght": (0, 1.0, 1.0)},
                    {"wdth": (0, 1.0, 1.0), "wght": (0, 0.66, 1.0)},
                    {"wdth": (0, 0.66, 1.0), "wght": (0, 0.66, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 4: 1.0, 5: 1.0},
                    {
                        0: 1.0,
                        3: 0.7555555555555555,
                        4: 0.24444444444444444,
                        5: 1.0,
                        6: 0.66,
                    },
                    {
                        0: 1.0,
                        3: 0.7555555555555555,
                        4: 0.24444444444444444,
                        5: 0.66,
                        6: 0.43560000000000004,
                        7: 0.66,
                    },
                ],
            ),
            (
                [
                    {},
                    {"bar": 0.5},
                    {"bar": 1.0},
                    {"foo": 1.0},
                    {"bar": 0.5, "foo": 1.0},
                    {"bar": 1.0, "foo": 1.0},
                ],
                None,
                [
                    {},
                    {"bar": 0.5},
                    {"bar": 1.0},
                    {"foo": 1.0},
                    {"bar": 0.5, "foo": 1.0},
                    {"bar": 1.0, "foo": 1.0},
                ],
                [
                    {},
                    {"bar": (0, 0.5, 1.0)},
                    {"bar": (0.5, 1.0, 1.0)},
                    {"foo": (0, 1.0, 1.0)},
                    {"bar": (0, 0.5, 1.0), "foo": (0, 1.0, 1.0)},
                    {"bar": (0.5, 1.0, 1.0), "foo": (0, 1.0, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 1: 1.0, 3: 1.0},
                    {0: 1.0, 2: 1.0, 3: 1.0},
                ],
            ),
            (
                [
                    {},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                ],
                None,
                [
                    {},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                ],
                [
                    {},
                    {"bar": (0.0, 0.25, 1.0)},
                    {"bar": (0.25, 0.75, 1.0)},
                    {"bar": (0.75, 1.0, 1.0)},
                    {"foo": (0.0, 0.25, 1.0)},
                    {"foo": (0.25, 0.5, 1.0)},
                    {"foo": (0.5, 0.75, 1.0)},
                    {"foo": (0.75, 1.0, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0, 1: 0.3333333333333333},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 4: 0.6666666666666666},
                    {0: 1.0, 4: 0.3333333333333333, 5: 0.5},
                    {0: 1.0},
                ],
            ),
            (
                [
                    {},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                ],
                None,
                [
                    {},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                ],
                [
                    {},
                    {"bar": (0, 0.25, 1.0)},
                    {"bar": (0.25, 0.75, 1.0)},
                    {"bar": (0.75, 1.0, 1.0)},
                    {"foo": (0, 0.25, 1.0)},
                    {"foo": (0.25, 0.5, 1.0)},
                    {"foo": (0.5, 0.75, 1.0)},
                    {"foo": (0.75, 1.0, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0, 1: 0.3333333333333333},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 4: 0.6666666666666666},
                    {0: 1.0, 4: 0.3333333333333333, 5: 0.5},
                    {0: 1.0},
                ],
            ),
        ],
    )
    def test_init(self, locations, axisOrder, sortedLocs, supports, deltaWeights):
        model = VariationModel(locations, axisOrder=axisOrder)

        assert model.locations == sortedLocs
        assert model.supports == supports
        assert model.deltaWeights == deltaWeights

    def test_init_duplicate_locations(self):
        with pytest.raises(VariationModelError, match="Locations must be unique."):
            VariationModel(
                [
                    {"foo": 0.0, "bar": 0.0},
                    {"foo": 1.0, "bar": 1.0},
                    {"bar": 1.0, "foo": 1.0},
                ]
            )

    def test_init_duplicate_locations_after_stripping_zero_axes(self):
        with pytest.raises(VariationModelError, match="Locations must be unique."):
            VariationModel([{}, {"foo": 0.0}])

    def test_getSubModel_preserves_extrapolate_and_axisRanges(self):
        axisRanges = {"foo": (-2.0, 2.0)}
        model = VariationModel(
            [{}, {"foo": 1.0}, {"foo": 2.0}],
            extrapolate=True,
            axisRanges=axisRanges,
        )

        subModel, items = model.getSubModel([1, None, 3])

        assert items == [1, 3]
        assert subModel.extrapolate is True
        assert subModel.axisRanges == axisRanges
        assert subModel.interpolateFromMasters({"foo": 3.0}, [100, 200]) == 250

    @pytest.mark.parametrize(
        "locations, axisOrder, masterValues, instanceLocation, expectedValue, masterScalars",
        [
            (
                [
                    {},
                    {"axis_A": 1.0},
                    {"axis_B": 1.0},
                    {"axis_A": 1.0, "axis_B": 1.0},
                    {"axis_A": 0.5, "axis_B": 1.0},
                    {"axis_A": 1.0, "axis_B": 0.5},
                ],
                ["axis_A", "axis_B"],
                [
                    0,
                    10,
                    20,
                    70,
                    50,
                    60,
                ],
                {
                    "axis_A": 0.5,
                    "axis_B": 0.5,
                },
                37.5,
                [0.25, 0.0, 0.0, -0.25, 0.5, 0.5],
            ),
        ],
    )
    def test_interpolation(
        self,
        locations,
        axisOrder,
        masterValues,
        instanceLocation,
        expectedValue,
        masterScalars,
    ):
        model = VariationModel(locations, axisOrder=axisOrder)

        interpolatedValue = model.interpolateFromMasters(instanceLocation, masterValues)
        assert interpolatedValue == expectedValue

        assert masterScalars == model.getMasterScalars(instanceLocation)

        assert model.interpolateFromValuesAndScalars(
            masterValues, masterScalars
        ) == pytest.approx(interpolatedValue)

    @pytest.mark.parametrize(
        "masterLocations, location, expected",
        [
            (locationsA, {"wght": 0, "wdth": 0}, [1, 0, 0]),
            (
                locationsA,
                {"wght": 0.5, "wdth": 0},
                [0.5, 0.5, 0],
            ),
            (locationsA, {"wght": 1, "wdth": 0}, [0, 1, 0]),
            (
                locationsA,
                {"wght": 0, "wdth": 0.5},
                [0.5, 0, 0.5],
            ),
            (locationsA, {"wght": 0, "wdth": 1}, [0, 0, 1]),
            (locationsA, {"wght": 1, "wdth": 1}, [-1, 1, 1]),
            (
                locationsA,
                {"wght": 0.5, "wdth": 0.5},
                [0, 0.5, 0.5],
            ),
            (
                locationsA,
                {"wght": 0.75, "wdth": 0.75},
                [-0.5, 0.75, 0.75],
            ),
            (
                locationsB,
                {"wght": 1, "wdth": 1},
                [0, 0, 0, 1],
            ),
            (
                locationsB,
                {"wght": 0.5, "wdth": 0},
                [0.5, 0.5, 0, 0],
            ),
            (
                locationsB,
                {"wght": 1, "wdth": 0.5},
                [0, 0.5, 0, 0.5],
            ),
            (
                locationsB,
                {"wght": 0.5, "wdth": 0.5},
                [0.25, 0.25, 0.25, 0.25],
            ),
            (
                locationsC,
                {"wght": 0.5, "wdth": 0},
                [0, 1, 0, 0, 0],
            ),
            (
                locationsC,
                {"wght": 0.25, "wdth": 0},
                [0.5, 0.5, 0, 0, 0],
            ),
            (
                locationsC,
                {"wght": 0.75, "wdth": 0},
                [0, 0.5, 0.5, 0, 0],
            ),
            (
                locationsC,
                {"wght": 0.5, "wdth": 1},
                [-0.5, 1, -0.5, 0.5, 0.5],
            ),
            (
                locationsC,
                {"wght": 0.75, "wdth": 1},
                [-0.25, 0.5, -0.25, 0.25, 0.75],
            ),
        ],
    )
    def test_getMasterScalars(self, masterLocations, location, expected):
        model = VariationModel(masterLocations)
        assert model.getMasterScalars(location) == expected


# ---------------------------------------------------------------------------
# Partial axis pinning narrows the reachable support domain.  Checking only
# final interpolated coordinates is not enough: a wrongly clipped tent and a
# correctly clipped tent can both evaluate to zero at the sampled points.
# The tests below therefore pair structural assertions (the exact support
# triples / culling decision) with numerical assertions (scalars and
# recalibrated deltas), and every failure message names the offending
# boundary coordinate.
# ---------------------------------------------------------------------------


class SupportScalarPinDomainTest(object):
    """Group 1/2: supportScalar over asymmetric, crossing and multi-axis tents."""

    @pytest.mark.parametrize(
        "location, expected",
        [
            # interval endpoints evaluate to zero on both sides
            pytest.param({"wght": 0.0}, 0.0, id="lower-endpoint"),
            pytest.param({"wght": 1.0}, 0.0, id="upper-endpoint"),
            # the peak is the unique point with unit scalar
            pytest.param({"wght": 0.5}, 1.0, id="peak"),
            # linear ramps on either side of the peak
            pytest.param({"wght": 0.25}, 0.5, id="lower-ramp-midpoint"),
            pytest.param({"wght": 0.75}, 0.5, id="upper-ramp-midpoint"),
            # locations outside the closed interval are clipped to zero
            pytest.param({"wght": -0.1}, 0.0, id="outside-below"),
            pytest.param({"wght": 1.1}, 0.0, id="outside-above"),
        ],
    )
    def test_symmetric_tent_endpoints_and_outside(self, location, expected):
        support = {"wght": (0.0, 0.5, 1.0)}
        assert supportScalar(location, support) == expected

    @pytest.mark.parametrize(
        "location, expected",
        [
            pytest.param({"wght": -1.0}, 0.0, id="negative-lower-endpoint"),
            pytest.param({"wght": 0.0}, 0.0, id="negative-upper-endpoint"),
            pytest.param({"wght": -0.5}, 1.0, id="negative-peak"),
            pytest.param({"wght": 0.1}, 0.0, id="outside-above-zero"),
        ],
    )
    def test_negative_side_tent_endpoints(self, location, expected):
        support = {"wght": (-1.0, -0.5, 0.0)}
        assert supportScalar(location, support) == expected

    @pytest.mark.parametrize(
        "location, support, expected",
        [
            # asymmetric positive interval: lower distance 0.5, upper distance 0.25
            (
                {"wght": 0.25},
                {"wght": (0.0, 0.5, 0.75)},
                0.5,
            ),
            (
                {"wght": 0.625},
                {"wght": (0.0, 0.5, 0.75)},
                0.5,
            ),
            # asymmetric negative interval: lower distance 0.25, upper distance 0.5
            (
                {"wght": -0.875},
                {"wght": (-1.0, -0.75, -0.25)},
                0.5,
            ),
            (
                {"wght": -0.5},
                {"wght": (-1.0, -0.75, -0.25)},
                0.5,
            ),
            # asymmetric tent clipped by the reachable range endpoint
            (
                {"wght": 0.75},
                {"wght": (0.0, 0.5, 0.75)},
                0.0,
            ),
            (
                {"wght": -1.0},
                {"wght": (-1.0, -0.75, -0.25)},
                0.0,
            ),
        ],
    )
    def test_asymmetric_tent_ramps(self, location, support, expected):
        scalar = supportScalar(location, support)
        assert scalar == pytest.approx(expected), (
            f"asymmetric tent {support} at {location}: expected {expected}, "
            f"got {scalar}"
        )

    def test_zero_peak_axis_does_not_participate(self):
        # OpenType rule: a zero peak means the axis is neutral, regardless of
        # the current coordinate. The remaining axis still contributes.
        support = {"a": (0.0, 1.0, 1.0), "b": (-1.0, 0.0, 1.0)}
        assert supportScalar({"a": 0.5, "b": 0.5}, support) == 0.5
        assert supportScalar({"a": 0.5, "b": -0.5}, support) == 0.5
        # Without the OpenType rule the zero-peak axis is an ordinary tent.
        assert (
            supportScalar({"a": 0.5, "b": 0.5}, support, ot=False) == 0.25
        )

    def test_axis_absent_from_location_is_neutral(self):
        # An axis missing from the evaluation location reads as zero, which
        # lies outside this positive tent, so the whole scalar is zero.
        assert supportScalar({}, {"wdth": (0.0, 0.5, 1.0)}) == 0.0
        # Extra axes in the location that the support does not mention are
        # simply ignored.
        assert (
            supportScalar(
                {"a": 0.5, "b": 0.9}, {"a": (0.0, 1.0, 1.0)}
            )
            == 0.5
        )

    def test_invalid_and_crossing_tents_are_neutral(self):
        # start > peak and tents straddling zero have constant unit support
        # under OpenType, so pinning logic must never cull them as dead.
        assert supportScalar({"wght": 0.5}, {"wght": (0.8, 0.5, 1.0)}) == 1.0
        assert supportScalar({"wght": 0.5}, {"wght": (-0.5, 0.5, 1.0)}) == 1.0
        assert supportScalar({"wght": -0.5}, {"wght": (-0.5, 0.5, 1.0)}) == 1.0

    @pytest.mark.parametrize(
        "location, support, axisRanges, expected",
        [
            # one-sided peak sitting exactly on the reachable maximum: linear
            # extrapolation continues past it instead of clipping
            (
                {"wght": 1.5},
                {"wght": (0.0, 1.0, 1.0)},
                {"wght": (0.0, 1.0)},
                1.5,
            ),
            # two-sided tent extrapolates negatively beyond the upper end
            (
                {"wght": 1.5},
                {"wght": (0.0, 0.5, 1.0)},
                {"wght": (0.0, 1.0)},
                -1.0,
            ),
            # below the reachable minimum
            (
                {"wght": -0.5},
                {"wght": (0.0, 0.5, 1.0)},
                {"wght": (0.0, 1.0)},
                -1.0,
            ),
            # asymmetric reachable range (-0.5, 1.0): negative-side tent
            (
                {"wght": -1.0},
                {"wght": (-0.5, -0.25, 0.0)},
                {"wght": (-0.5, 1.0)},
                -2.0,
            ),
        ],
    )
    def test_explicit_extrapolation(self, location, support, axisRanges, expected):
        scalar = supportScalar(
            location,
            support,
            extrapolate=True,
            axisRanges=axisRanges,
        )
        assert scalar == pytest.approx(expected), (
            f"extrapolated tent {support} at {location} over {axisRanges}: "
            f"expected {expected}, got {scalar}"
        )

    def test_extrapolation_requires_axis_ranges(self):
        with pytest.raises(TypeError):
            supportScalar(
                {"wght": 1.5},
                {"wght": (0.0, 1.0, 1.0)},
                extrapolate=True,
            )


class NormalizedLocationPinDomainTest(object):
    """Group 1: normalization with asymmetric intervals and biased defaults."""

    @pytest.mark.parametrize(
        "value, triple, expected",
        [
            # default biased towards the minimum: 300 sits between 100 and 900
            pytest.param(100, (100, 300, 900), -1.0, id="min"),
            pytest.param(300, (100, 300, 900), 0.0, id="biased-default"),
            pytest.param(900, (100, 300, 900), 1.0, id="max"),
            pytest.param(200, (100, 300, 900), -0.5, id="negative-half"),
            pytest.param(600, (100, 300, 900), 0.5, id="positive-half"),
        ],
    )
    def test_biased_default_normalization(self, value, triple, expected):
        assert normalizeValue(value, triple) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value, triple, expected",
        [
            # without extrapolation, out-of-range values clamp to +/- 1
            pytest.param(50, (100, 300, 900), -1.0, id="below-clamps"),
            pytest.param(950, (100, 300, 900), 1.0, id="above-clamps"),
        ],
    )
    def test_biased_default_clamps_without_extrapolation(
        self, value, triple, expected
    ):
        assert normalizeValue(value, triple) == expected

    @pytest.mark.parametrize(
        "value, triple, expected",
        [
            # explicit extrapolation keeps the biased slope on each side
            pytest.param(50, (100, 300, 900), -1.25, id="below-extrapolates"),
            pytest.param(950, (100, 300, 900), 1.0 + 50 / 600, id="above-extrapolates"),
            # one-sided axis: no negative room, positive slope extends down
            pytest.param(-100, (0, 0, 500), -0.2, id="one-sided-negative"),
        ],
    )
    def test_biased_default_extrapolation(self, value, triple, expected):
        result = normalizeValue(value, triple, extrapolate=True)
        assert result == pytest.approx(expected), (
            f"normalizeValue({value}, {triple}, extrapolate=True): "
            f"expected {expected}, got {result}"
        )

    def test_location_fills_missing_axis_with_default(self):
        axes = {"wght": (100, 400, 900), "wdth": (50, 100, 150)}
        # An axis that does not participate in the source location is placed
        # at its default, i.e. normalized zero.
        assert normalizeLocation({"wght": 650}, axes) == {
            "wght": 0.5,
            "wdth": 0.0,
        }

    def test_location_outside_range_clamps_per_axis(self):
        axes = {"wght": (100, 400, 900), "wdth": (50, 100, 150)}
        assert normalizeLocation({"wght": 0, "wdth": 200}, axes) == {
            "wght": -1.0,
            "wdth": 1.0,
        }


class VariationModelPinDomainTest(object):
    """Group 1: supports, normalized locations and recalibrated deltas."""

    def test_asymmetric_axis_range_clips_support_triples(self):
        # The pinned reachable range (-0.5, 1.0) replaces the implicit
        # (-1, 1): every region triple must be bounded by that interval.
        locations = [{}, {"wght": -0.25}, {"wght": 0.5}]
        axisRanges = {"wght": (-0.5, 1.0)}
        model = VariationModel(locations, axisRanges=axisRanges)

        # Structural assertion: exact support triples, not just outputs.
        assert model.supports == [
            {},
            {"wght": (-0.5, -0.25, 0.0)},
            {"wght": (0.0, 0.5, 1.0)},
        ]
        for support in model.supports:
            for axis, (lower, peak, upper) in support.items():
                lo, hi = axisRanges[axis]
                assert lo <= lower <= peak <= upper <= hi, (
                    f"support {support} escapes pinned range {axisRanges[axis]}"
                )

    def test_asymmetric_model_recalibrated_deltas_and_interpolation(self):
        locations = [{}, {"wght": -0.25}, {"wght": 0.5}]
        axisRanges = {"wght": (-0.5, 1.0)}
        model = VariationModel(locations, axisRanges=axisRanges)
        masterValues = [100.0, 80.0, 200.0]
        deltas = model.getDeltas(masterValues)

        # Structural/numerical: deltas are recomputed against the clipped
        # supports, so interior points follow the new tents exactly.
        assert deltas == [100.0, -20.0, 100.0]
        # master locations are reproduced exactly through the delta path
        for loc, value in zip(locations, masterValues):
            assert model.interpolateFromDeltas(loc, deltas) == value
        # hand-computed interior points on each asymmetric ramp
        assert model.interpolateFromMasters(
            {"wght": 0.25}, masterValues
        ) == pytest.approx(150.0)
        assert model.interpolateFromMasters(
            {"wght": -0.375}, masterValues
        ) == pytest.approx(90.0)
        # outside the pinned domain: no extrapolation -> base master only
        assert model.interpolateFromMasters(
            {"wght": 1.2}, masterValues
        ) == pytest.approx(100.0)
        assert model.interpolateFromMasters(
            {"wght": -0.7}, masterValues
        ) == pytest.approx(100.0)

    def test_crossing_peak_splits_support_box(self):
        # Three positive masters force two box splits; the middle master's
        # support is the narrow tent between its neighbours' peaks.
        locations = [{}, {"wght": 0.5}, {"wght": 0.75}, {"wght": 1.0}]
        model = VariationModel(locations)

        assert model.supports == [
            {},
            {"wght": (0.0, 0.5, 1.0)},
            {"wght": (0.5, 0.75, 1.0)},
            {"wght": (0.75, 1.0, 1.0)},
        ]
        # Numerical cross-check of the split weights.
        assert model.deltaWeights == [
            {},
            {0: 1.0},
            {0: 1.0, 1: 0.5},
            {0: 1.0},
        ]
        masterValues = [0.0, 100.0, 100.0, 100.0]
        deltas = model.getDeltas(masterValues)
        # every master location must still reconstruct its own value even
        # though the supports were split around interior peaks
        for loc, value in zip(locations, masterValues):
            assert model.interpolateFromDeltas(loc, deltas) == value

    def test_multi_axis_supports_are_product_of_clipped_tents(self):
        axisRanges = {"a": (-0.5, 0.5), "b": (0.0, 1.0)}
        locations = [
            {},
            {"a": -0.25},
            {"a": 0.25},
            {"b": 0.5},
            {"a": 0.25, "b": 0.5},
        ]
        model = VariationModel(
            locations, axisOrder=["a", "b"], axisRanges=axisRanges
        )

        # Structural: each axis triple stays inside its pinned range and the
        # corner region carries both clipped tents.
        assert model.supports == [
            {},
            {"a": (-0.5, -0.25, 0.0)},
            {"a": (0.0, 0.25, 0.5)},
            {"b": (0.0, 0.5, 1.0)},
            {
                "a": (0.0, 0.25, 0.5),
                "b": (0.0, 0.5, 1.0),
            },
        ]

        masterValues = [100.0, 80.0, 140.0, 200.0, 260.0]
        deltas = model.getDeltas(masterValues)
        assert deltas == [100.0, -20.0, 40.0, 100.0, 20.0]
        for loc, value in zip(locations, masterValues):
            assert model.interpolateFromDeltas(loc, deltas) == value

        # Numerical: scalar at (.1, .25) is the product 0.4 * 0.5 = 0.2 on the
        # corner region, combined with the single-axis contributions.
        scalars = model.getScalars({"a": 0.1, "b": 0.25})
        assert scalars == pytest.approx([1.0, 0.0, 0.4, 0.5, 0.2])
        assert model.interpolateFromMasters(
            {"a": 0.1, "b": 0.25}, masterValues
        ) == pytest.approx(170.0)

    def test_pinned_axis_dropped_from_locations(self):
        # Zero coordinates are stripped at construction, so a location on an
        # axis pinned at its default carries no region for that axis; the
        # surviving location only mentions the unpinned axis.
        locations = [{}, {"wght": 0.0, "wdth": 0.5}, {"wdth": 1.0}]
        model = VariationModel(locations)
        assert model.locations == [{}, {"wdth": 0.5}, {"wdth": 1.0}]
        assert all("wght" not in support for support in model.supports)

    @pytest.mark.parametrize(
        "locations",
        [
            pytest.param([{}, {"foo": 0.0}], id="zero-axis-duplicate"),
            pytest.param(
                [{"foo": 1.0, "bar": 0.0}, {"bar": 0.0, "foo": 1.0}],
                id="reordered-duplicate",
            ),
            pytest.param(
                [{"foo": 1.0}, {"foo": 1.0}],
                id="identical-duplicate",
            ),
        ],
    )
    def test_duplicate_locations_rejected_after_zero_merge(self, locations):
        with pytest.raises(VariationModelError, match="Locations must be unique."):
            VariationModel(locations)

    def test_extrapolate_model_uses_reachable_ranges_outside_domain(self):
        axisRanges = {"wght": (0.0, 1.0)}
        locations = [{}, {"wght": 0.5}, {"wght": 1.0}]
        masterValues = [100.0, 150.0, 200.0]

        clipped = VariationModel(locations, axisRanges=axisRanges)
        # Without extrapolation the tent is dead past the upper endpoint.
        assert clipped.interpolateFromMasters(
            {"wght": 1.5}, masterValues
        ) == pytest.approx(100.0)

        extrapolating = VariationModel(
            locations, extrapolate=True, axisRanges=axisRanges
        )
        assert extrapolating.interpolateFromMasters(
            {"wght": 1.5}, masterValues
        ) == pytest.approx(250.0)
        assert extrapolating.interpolateFromMasters(
            {"wght": -0.5}, masterValues
        ) == pytest.approx(50.0)


class PinnedDomainCullingRegressionTest(object):
    """Group 3: structural culling vs. numerically-coincidental zeros.

    Partial pinning restricts each axis to a reachable interval.  A tent is
    dead only when its scalar is zero at *every* reachable coordinate; the
    instancer's structural predicate (``_isTupleVariationDead``) must agree
    with an exhaustive numerical evaluation of ``supportScalar``, including
    the boundary cases where endpoint-only sampling would give the wrong
    answer.
    """

    @pytest.mark.parametrize(
        "support, reachable, structurally_dead",
        [
            pytest.param((0.5, 0.75, 1.0), (0.0, 0.5), True, id="positive-dead"),
            pytest.param((-1.0, -0.75, -0.5), (-0.5, 0.0), True, id="negative-dead"),
            pytest.param((-1.0, -1.0, 0.0), (0.0, 0.25), True, id="one-sided-dead"),
            pytest.param(
                (0.0, 1.0, 1.0), (-0.25, 0.0), True, id="upper-one-sided-dead"
            ),
            # peak exactly on the reachable boundary: scalar is 1 there, live
            pytest.param((0.5, 0.5, 1.0), (0.0, 0.5), False, id="boundary-peak-live"),
            pytest.param(
                (-1.0, -0.5, -0.5), (-0.5, 0.0), False, id="negative-boundary-peak-live"
            ),
            # reachable interval reaches the peak
            pytest.param((0.5, 0.75, 1.0), (0.0, 0.75), False, id="peak-reachable"),
            # neutral / invalid tents are never culled structurally
            pytest.param((-1.0, 0.0, 1.0), (0.0, 0.0), False, id="neutral-zero-peak"),
            pytest.param((0.5, 0.25, 1.0), (0.0, 0.25), False, id="inverted-tent"),
        ],
    )
    def test_structural_predicate_matches_exhaustive_scalars(
        self, support, reachable, structurally_dead
    ):
        lo, hi = reachable
        tuple_variation = type("TV", (), {"axes": {"wght": support}})()

        decision = instancer._isTupleVariationDead(
            tuple_variation, {"wght": reachable}
        )
        # Structural assertion with a message naming the exact boundary.
        assert decision is structurally_dead, (
            f"culling decision for tent {support} over reachable "
            f"[{lo}, {hi}]: expected dead={structurally_dead}, got {decision}"
        )

        # Numerical assertion: dense grid including both endpoints and the
        # peak. Endpoint-only samples cannot distinguish a dead tent from a
        # live one whose ramp starts just inside the interval.
        samples = [lo + (hi - lo) * i / 256 for i in range(257)]
        scalars = [
            supportScalar({"wght": v}, {"wght": support}) for v in samples
        ]
        max_abs = max(abs(s) for s in scalars)
        if structurally_dead:
            assert max_abs == 0.0, (
                f"tent {support} declared dead but scalar reaches {max_abs} "
                f"inside reachable [{lo}, {hi}]"
            )
        else:
            assert max_abs > 0.0, (
                f"tent {support} kept alive but every scalar is zero inside "
                f"reachable [{lo}, {hi}]"
            )

    def test_endpoint_only_sampling_is_insufficient(self):
        # Regression guard for the testing methodology itself: this live tent
        # is zero at the reachable lower endpoint but non-zero immediately
        # inside the interval. A test comparing only endpoint coordinates
        # would cull it wrongly.
        support = {"wght": (0.0, 0.5, 1.0)}
        lo, hi = 0.0, 0.5
        assert supportScalar({"wght": lo}, support) == 0.0
        assert supportScalar({"wght": 0.25}, support) == 0.5
        tuple_variation = type("TV", (), {"axes": support})()
        assert not instancer._isTupleVariationDead(
            tuple_variation, {"wght": (lo, hi)}
        )

    def test_multi_axis_region_dead_when_one_axis_tent_is_dead(self):
        # A region scalar is the product of per-axis tents, so one dead axis
        # kills the whole region everywhere reachable.
        support = {"a": (0.5, 0.75, 1.0), "b": (0.0, 0.5, 1.0)}
        reachable = {"a": (0.0, 0.5), "b": (-1.0, 1.0)}
        tuple_variation = type("TV", (), {"axes": support})()

        assert instancer._isTupleVariationDead(tuple_variation, reachable)

        # Numerical confirmation over a 2-D grid of the reachable box.
        grid_a = [0.5 * i / 20 for i in range(21)]
        grid_b = [-1.0 + 2.0 * j / 20 for j in range(21)]
        for a in grid_a:
            for b in grid_b:
                scalar = supportScalar({"a": a, "b": b}, support)
                assert scalar == 0.0, (
                    f"culled region {support} live at (a={a}, b={b}): "
                    f"scalar={scalar}"
                )

    def test_multi_axis_region_live_inside_reachable_box(self):
        # Same shape but with the reachable interval extended past the dead
        # tent's endpoint: the region must survive and produce non-zero scalars.
        support = {"a": (0.5, 0.75, 1.0), "b": (0.0, 0.5, 1.0)}
        reachable = {"a": (0.0, 0.8), "b": (-1.0, 1.0)}
        tuple_variation = type("TV", (), {"axes": support})()

        assert not instancer._isTupleVariationDead(tuple_variation, reachable)
        assert (
            supportScalar({"a": 0.75, "b": 0.5}, support) == 1.0
        )
