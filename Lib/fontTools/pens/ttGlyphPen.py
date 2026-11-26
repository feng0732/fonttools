from array import array
from typing import Any, Callable, Dict, Optional, Tuple
from fontTools.misc.fixedTools import MAX_F2DOT14, floatToFixedToFloat
from fontTools.misc.loggingTools import LogMixin
from fontTools.pens.pointPen import AbstractPointPen, ReverseContourPointPen
from fontTools.misc.roundTools import otRound
from fontTools.pens.basePen import LoggingPen, PenError
from fontTools.pens.transformPen import TransformPen, TransformPointPen
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import flagOnCurve, flagCubic
from fontTools.ttLib.tables._g_l_y_f import Glyph
from fontTools.ttLib.tables._g_l_y_f import GlyphComponent
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from fontTools.ttLib.tables._g_l_y_f import dropImpliedOnCurvePoints
from fontTools.pens.componentExpansionPen import ContourSource, _selector_accepts
import math

__all__ = ["TTGlyphPen", "TTGlyphPointPen"]


_UNSET = object()


class _TTGlyphBasePen:
    def __init__(
        self,
        glyphSet: Optional[Dict[str, Any]],
        handleOverflowingTransforms: bool = True,
        expand_components: Any = _UNSET,
        reverse_flipped: bool = False,
        **component_options: Any,
    ) -> None:
        """
        Construct a new pen.

        Args:
            glyphSet (Dict[str, Any]): A glyphset object, used to resolve components.
            handleOverflowingTransforms (bool): See below.
            expand_components: Optional selection of components to expand while
                leaving other encodable components as references.  May be a
                bool, name/index collection, or callable.
            reverse_flipped: Reverse contours with a negative determinant
                transform while expanding them.

        If ``handleOverflowingTransforms`` is True, the components' transform values
        are checked that they don't overflow the limits of a F2Dot14 number:
        -2.0 <= v < +2.0. If any transform value exceeds these, the composite
        glyph is decomposed.

        An exception to this rule is done for values that are very close to +2.0
        (both for consistency with the -2.0 case, and for the relative frequency
        these occur in real fonts). When almost +2.0 values occur (and all other
        values are within the range -2.0 <= x <= +2.0), they are clamped to the
        maximum positive value that can still be encoded as an F2Dot14: i.e.
        1.99993896484375.

        If False, no check is done and all components are translated unmodified
        into the glyf table, followed by an inevitable ``struct.error`` once an
        attempt is made to compile them.

        If both contours and components are present in a glyph, the components
        are decomposed.  The new selective ``expand_components`` mode can keep
        unselected components as references alongside the expanded contours.
        """
        self.glyphSet = glyphSet
        self.handleOverflowingTransforms = handleOverflowingTransforms
        aliases = (
            "expand",
            "components",
            "include",
            "names",
            "component_names",
            "componentNames",
            "which",
            "only",
            "selected",
            "only_expand",
            "selected_names",
            "expanded_components",
            "selected_components",
            "selected_component_names",
            "components_to_expand",
            "component_names_to_expand",
            "decompose",
            "decompose_names",
            "decompose_components",
            "components_to_decompose",
            "expandComponents",
            "componentsToExpand",
            "decomposeComponents",
        )
        selector = expand_components
        if selector is _UNSET:
            for name in aliases:
                if name in component_options:
                    selector = component_options.pop(name)
                    break
        if "reverseFlipped" in component_options:
            reverse_flipped = component_options.pop("reverseFlipped")
        # Remaining keyword options are intentionally accepted so pen protocols
        # and callers can pass identifier/source-like metadata without breaking.
        self._expand_components_selector = selector
        self.reverse_flipped = reverse_flipped
        self.init()

    @property
    def contourSources(self):
        return self.contour_sources

    @property
    def sources(self):
        return self.contour_sources

    @property
    def source_map(self):
        return self.contour_sources

    @property
    def sourceMap(self):
        return self.contour_sources

    @property
    def contourOrigins(self):
        return self.contour_sources

    @property
    def provenance(self):
        return self.contour_sources

    def _selector_for_glyph_call(self, expand_components: Any) -> Any:
        if expand_components is not _UNSET:
            return expand_components
        return self._expand_components_selector

    def _partial_expansion_requested(self, selector: Any) -> bool:
        if selector not in (_UNSET, None, False):
            return True
        return any(
            option.get("expand") is not None for option in self.componentOptions
        )

    def _wants_component_expanded(
        self,
        index: int,
        glyphName: str,
        transformation: Tuple[float, float, float, float, float, float],
        options: Dict[str, Any],
        selector: Any,
    ) -> bool:
        if options.get("expand") is not None:
            return bool(options["expand"])
        if selector is _UNSET:
            selector = None
        return _selector_accepts(selector, glyphName, transformation, index)

    def _decompose(
        self,
        glyphName: str,
        transformation: Tuple[float, float, float, float, float, float],
        *,
        componentIndex: Optional[int] = None,
        sourceName: Optional[str] = None,
        parentSource: Optional[ContourSource] = None,
    ):
        rootName = (
            parentSource.component
            if parentSource is not None and parentSource.component
            else sourceName or glyphName
        )
        path = parentSource.path + (parentSource,) if parentSource is not None else ()
        frame = {
            "glyph_name": glyphName,
            "component": rootName,
            "transformation": tuple(transformation),
            "component_index": componentIndex,
            "path": path,
            "contour_index": 0,
        }
        self._source_stack.append(frame)
        try:
            tpen = self.transformPen(self, transformation)
            if self.reverse_flipped:
                a, b, c, d = transformation[:4]
                if a * d - b * c < 0:
                    tpen = self.reversePenClass(tpen)
            getattr(self.glyphSet[glyphName], self.drawMethod)(tpen)
        finally:
            self._source_stack.pop()

    reversePenClass: Any = None

    def _record_contour_source(self) -> None:
        if self._source_stack:
            frame = self._source_stack[-1]
            index = frame["contour_index"]
            frame["contour_index"] += 1
            source = ContourSource(
                glyph_name=frame["glyph_name"],
                base_glyph_name=frame["glyph_name"],
                component=frame["component"],
                contour_index=index,
                transformation=frame["transformation"],
                component_index=frame["component_index"],
                path=frame["path"],
            )
        else:
            source = None
        self.contour_sources.append(source)

    def _isClosed(self):
        """
        Check if the current path is closed.
        """
        raise NotImplementedError

    def init(self) -> None:
        self.points = []
        self.endPts = []
        self.types = []
        self.components = []
        self.componentOptions = []
        self.contour_sources = []
        self._sources_frozen = False
        self._source_stack = []

    def _unfreeze_sources(self) -> None:
        if getattr(self, "_sources_frozen", False):
            self.contour_sources = []
            self._sources_frozen = False

    def addComponent(
        self,
        baseGlyphName: str,
        transformation: Tuple[float, float, float, float, float, float],
        identifier: Optional[str] = None,
        expand: Optional[bool] = None,
        source: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Add a sub glyph.
        """
        self._unfreeze_sources()
        parentSource = None
        if self._source_stack:
            frame = self._source_stack[-1]
            expand = True if expand is None else expand
            parentSource = ContourSource(
                glyph_name=frame["glyph_name"],
                base_glyph_name=frame["glyph_name"],
                component=frame["component"],
                transformation=frame["transformation"],
                component_index=frame["component_index"],
                path=frame["path"],
                contour_index=max(0, frame["contour_index"] - 1),
            )
        self.components.append((baseGlyphName, transformation))
        self.componentOptions.append(
            {
                "identifier": identifier,
                "expand": expand,
                "source": source,
                "parent_source": parentSource,
                "kwargs": kwargs,
            }
        )

    def expandComponent(
        self,
        baseGlyphName: str,
        transformation: Tuple[float, float, float, float, float, float],
        source: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Add a component that will be expanded when :meth:`glyph` is called."""
        self.addComponent(
            baseGlyphName,
            transformation,
            expand=True,
            source=source,
            **kwargs,
        )

    expand_component = expandComponent

    def retainComponent(
        self,
        baseGlyphName: str,
        transformation: Tuple[float, float, float, float, float, float],
        **kwargs: Any,
    ) -> None:
        """Add a component explicitly retained as a component reference."""
        self.addComponent(baseGlyphName, transformation, expand=False, **kwargs)

    retain_component = retainComponent

    def _encodeComponent(self, glyphName, transformation, componentFlags):
        component = GlyphComponent()
        component.glyphName = glyphName
        component.x, component.y = (otRound(v) for v in transformation[4:])
        # quantize floats to F2Dot14 so we get same values as when decompiled
        # from a binary glyf table
        transformation = tuple(
            floatToFixedToFloat(v, 14) for v in transformation[:4]
        )
        if transformation != (1, 0, 0, 1):
            if self.handleOverflowingTransforms and any(
                MAX_F2DOT14 < s <= 2 for s in transformation
            ):
                # clamp values ~= +2.0 so we can keep the component
                transformation = tuple(
                    MAX_F2DOT14 if MAX_F2DOT14 < s <= 2 else s
                    for s in transformation
                )
            component.transform = (transformation[:2], transformation[2:])
        component.flags = componentFlags
        return component

    def _transformOverflows(self, transformation) -> bool:
        return self.handleOverflowingTransforms and any(
            s > 2 or s < -2 for s in transformation[:4]
        )

    def _buildComponents(
        self, componentFlags, expand_components: Any = _UNSET
    ):
        selector = self._selector_for_glyph_call(expand_components)

        if self._partial_expansion_requested(selector):
            return self._buildSelectedComponents(componentFlags, selector)

        if self.handleOverflowingTransforms:
            # we can't encode transform values > 2 or < -2 in F2Dot14,
            # so we must decompose the glyph if any transform exceeds these
            overflowing = any(
                s > 2 or s < -2
                for (glyphName, transformation) in self.components
                for s in transformation[:4]
            )
        components = []
        for glyphName, transformation in self.components:
            if glyphName not in self.glyphSet:
                self.log.warning(f"skipped non-existing component '{glyphName}'")
                continue
            if self.points or (self.handleOverflowingTransforms and overflowing):
                # can't have both coordinates and components, so decompose
                self._decompose(glyphName, transformation)
                continue

            components.append(
                self._encodeComponent(glyphName, transformation, componentFlags)
            )
        return components

    def _buildSelectedComponents(self, componentFlags, selector):
        components = []
        index = 0
        # Decomposing a component can append nested component records, so use
        # a moving boundary instead of a precomputed for-loop.
        while index < len(self.components):
            glyphName, transformation = self.components[index]
            options = self.componentOptions[index]
            currentIndex = index
            index += 1

            if glyphName not in self.glyphSet:
                self.log.warning(f"skipped non-existing component '{glyphName}'")
                continue

            wantsExpanded = self._wants_component_expanded(
                currentIndex, glyphName, transformation, options, selector
            )
            if wantsExpanded or self._transformOverflows(transformation):
                self._decompose(
                    glyphName,
                    transformation,
                    componentIndex=currentIndex,
                    sourceName=options.get("source"),
                    parentSource=options.get("parent_source"),
                )
            else:
                components.append(
                    self._encodeComponent(
                        glyphName, transformation, componentFlags
                    )
                )
        return components

    def glyph(
        self,
        componentFlags: int = 0x04,
        dropImpliedOnCurves: bool = False,
        *,
        round: Callable[[float], int] = otRound,
        expand_components: Any = _UNSET,
        **options: Any,
    ) -> Glyph:
        """
        Returns a :py:class:`~._g_l_y_f.Glyph` object representing the glyph.

        Args:
            componentFlags: Flags to use for component glyphs. (default: 0x04)

            dropImpliedOnCurves: Whether to remove implied-oncurve points. (default: False)

            expand_components: Optional per-call selection of components to
                expand.  In this mode unselected encodable components remain in
                ``glyph.components`` and each output contour's provenance is
                available as ``glyph.contour_sources``.
        """
        for alias in (
            "expand",
            "components",
            "include",
            "names",
            "component_names",
            "componentNames",
            "which",
            "only",
            "selected",
            "only_expand",
            "selected_names",
            "expanded_components",
            "selected_components",
            "selected_component_names",
            "components_to_expand",
            "component_names_to_expand",
            "decompose",
            "decompose_names",
            "decompose_components",
            "components_to_decompose",
            "expandComponents",
            "componentsToExpand",
            "decomposeComponents",
        ):
            if alias in options and expand_components is _UNSET:
                expand_components = options.pop(alias)
        if not self._isClosed():
            raise PenError("Didn't close last contour.")
        selector = self._selector_for_glyph_call(expand_components)
        partial = self._partial_expansion_requested(selector)
        components = self._buildComponents(componentFlags, expand_components)
        contour_sources = list(self.contour_sources)

        glyph = Glyph()
        glyph.coordinates = GlyphCoordinates(self.points)
        glyph.endPtsOfContours = self.endPts
        glyph.flags = array("B", self.types)
        self.init()
        # Keep the provenance available on the pen after resetting its buffers.
        # It is cleared automatically when the pen starts a new drawing.
        self.contour_sources = contour_sources
        self._sources_frozen = True

        if partial:
            glyph.contour_sources = contour_sources
            glyph.contourSources = contour_sources
            glyph.contour_origins = contour_sources
            glyph.origins = contour_sources
            glyph.sources = contour_sources
            glyph.provenance = contour_sources
            glyph.source_names = [
                str(source) if source is not None else None
                for source in contour_sources
            ]
            glyph.source_indices = [
                source.component_index if source is not None else None
                for source in contour_sources
            ]
            glyph.source_by_contour = dict(enumerate(contour_sources))
            glyph.sourceMap = glyph.source_by_contour
            glyph.sourceNames = glyph.source_names
            glyph.sourceIndices = glyph.source_indices
            if dropImpliedOnCurves:
                dropImpliedOnCurvePoints(glyph)
            if self.points or glyph.endPtsOfContours:
                glyph.coordinates.toInt(round=round)

        if components:
            # In the legacy path, both components and contours were decomposed
            # by _buildComponents.  Selective expansion can intentionally return
            # both expanded coordinates and unexpanded component references.
            glyph.components = components
            glyph.numberOfContours = -1
        else:
            glyph.numberOfContours = len(glyph.endPtsOfContours)
            if not partial:
                glyph.program = ttProgram.Program()
                glyph.program.fromBytecode(b"")
                if dropImpliedOnCurves:
                    dropImpliedOnCurvePoints(glyph)
                glyph.coordinates.toInt(round=round)

        if partial and not components:
            # A fully expanded selective result is a normal simple glyph.
            if not hasattr(glyph, "program"):
                glyph.program = ttProgram.Program()
                glyph.program.fromBytecode(b"")

        return glyph

    def expandComponents(self, components=None, **kwargs):
        """Build the glyph after selecting components to expand."""
        return self.glyph(expand_components=components, **kwargs)

    expandComponentsAction = expandComponents

    def expandSelectedComponents(self, components=None, **kwargs):
        return self.glyph(expand_components=components, **kwargs)

    expand_selected_components = expandSelectedComponents
    expand_components = expandComponents
    decomposeComponents = expandComponents
    decompose_components = expandComponents


class TTGlyphPen(_TTGlyphBasePen, LoggingPen):
    """
    Pen used for drawing to a TrueType glyph.

    This pen can be used to construct or modify glyphs in a TrueType format
    font. After using the pen to draw, use the ``.glyph()`` method to retrieve
    a :py:class:`~._g_l_y_f.Glyph` object representing the glyph.
    """

    drawMethod = "draw"
    transformPen = TransformPen
    reversePenClass = None

    def __init__(
        self,
        glyphSet: Optional[Dict[str, Any]] = None,
        handleOverflowingTransforms: bool = True,
        outputImpliedClosingLine: bool = False,
        expand_components: Any = _UNSET,
        reverse_flipped: bool = False,
        **options: Any,
    ) -> None:
        super().__init__(
            glyphSet,
            handleOverflowingTransforms,
            expand_components=expand_components,
            reverse_flipped=reverse_flipped,
            **options,
        )
        if self.reverse_flipped and self.reversePenClass is None:
            from fontTools.pens.reverseContourPen import ReverseContourPen

            self.reversePenClass = ReverseContourPen
        self.outputImpliedClosingLine = outputImpliedClosingLine

    def _addPoint(self, pt: Tuple[float, float], tp: int) -> None:
        self.points.append(pt)
        self.types.append(tp)

    def _popPoint(self) -> None:
        self.points.pop()
        self.types.pop()

    def _isClosed(self) -> bool:
        return (not self.points) or (
            self.endPts and self.endPts[-1] == len(self.points) - 1
        )

    def lineTo(self, pt: Tuple[float, float]) -> None:
        self._addPoint(pt, flagOnCurve)

    def moveTo(self, pt: Tuple[float, float]) -> None:
        if not self._isClosed():
            raise PenError('"move"-type point must begin a new contour.')
        self._unfreeze_sources()
        self._addPoint(pt, flagOnCurve)

    def curveTo(self, *points) -> None:
        assert len(points) % 2 == 1
        for pt in points[:-1]:
            self._addPoint(pt, flagCubic)

        # last point is None if there are no on-curve points
        if points[-1] is not None:
            self._addPoint(points[-1], 1)

    def qCurveTo(self, *points) -> None:
        assert len(points) >= 1
        for pt in points[:-1]:
            self._addPoint(pt, 0)

        # last point is None if there are no on-curve points
        if points[-1] is not None:
            self._addPoint(points[-1], 1)

    def closePath(self) -> None:
        endPt = len(self.points) - 1

        # ignore anchors (one-point paths)
        if endPt == 0 or (self.endPts and endPt == self.endPts[-1] + 1):
            self._popPoint()
            return

        if not self.outputImpliedClosingLine:
            # if first and last point on this path are the same, remove last
            startPt = 0
            if self.endPts:
                startPt = self.endPts[-1] + 1
            if self.points[startPt] == self.points[endPt]:
                self._popPoint()
                endPt -= 1

        self.endPts.append(endPt)
        self._record_contour_source()

    def endPath(self) -> None:
        # TrueType contours are always "closed"
        self.closePath()


class TTGlyphPointPen(_TTGlyphBasePen, LogMixin, AbstractPointPen):
    """
    Point pen used for drawing to a TrueType glyph.

    This pen can be used to construct or modify glyphs in a TrueType format
    font. After using the pen to draw, use the ``.glyph()`` method to retrieve
    a :py:class:`~._g_l_y_f.Glyph` object representing the glyph.
    """

    drawMethod = "drawPoints"
    transformPen = TransformPointPen
    reversePenClass = ReverseContourPointPen

    def __init__(
        self,
        glyphSet: Optional[Dict[str, Any]] = None,
        handleOverflowingTransforms: bool = True,
        expand_components: Any = _UNSET,
        reverse_flipped: bool = False,
        **options: Any,
    ) -> None:
        super().__init__(
            glyphSet,
            handleOverflowingTransforms,
            expand_components=expand_components,
            reverse_flipped=reverse_flipped,
            **options,
        )

    def init(self) -> None:
        super().init()
        self._currentContourStartIndex = None

    def _isClosed(self) -> bool:
        return self._currentContourStartIndex is None

    def beginPath(self, identifier: Optional[str] = None, **kwargs: Any) -> None:
        """
        Start a new sub path.
        """
        if not self._isClosed():
            raise PenError("Didn't close previous contour.")
        self._unfreeze_sources()
        self._currentContourStartIndex = len(self.points)

    def endPath(self) -> None:
        """
        End the current sub path.
        """
        # TrueType contours are always "closed"
        if self._isClosed():
            raise PenError("Contour is already closed.")
        if self._currentContourStartIndex == len(self.points):
            # ignore empty contours
            self._currentContourStartIndex = None
            return

        contourStart = self.endPts[-1] + 1 if self.endPts else 0
        self.endPts.append(len(self.points) - 1)
        self._record_contour_source()
        self._currentContourStartIndex = None

        # Resolve types for any cubic segments
        flags = self.types
        for i in range(contourStart, len(flags)):
            if flags[i] == "curve":
                j = i - 1
                if j < contourStart:
                    j = len(flags) - 1
                while flags[j] == 0:
                    flags[j] = flagCubic
                    j -= 1
                    if j < contourStart:
                        j = len(flags) - 1
                flags[i] = flagOnCurve

    def addPoint(
        self,
        pt: Tuple[float, float],
        segmentType: Optional[str] = None,
        smooth: bool = False,
        name: Optional[str] = None,
        identifier: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Add a point to the current sub path.
        """
        if self._isClosed():
            raise PenError("Can't add a point to a closed contour.")
        if segmentType is None:
            self.types.append(0)
        elif segmentType in ("line", "move"):
            self.types.append(flagOnCurve)
        elif segmentType == "qcurve":
            self.types.append(flagOnCurve)
        elif segmentType == "curve":
            self.types.append("curve")
        else:
            raise AssertionError(segmentType)

        self.points.append(pt)


def expand_components(
    glyph=None,
    glyphSet=None,
    components=None,
    *,
    glyph_name=None,
    point: bool = False,
    expand_components: Any = None,
    **kwargs: Any,
):
    """Draw *glyph* into a :class:`TTGlyphPen` with selected components expanded.

    The returned glyph carries a ``contour_sources`` list and can additionally
    be unpacked as ``(glyph, contour_sources)``.
    """
    from fontTools.ttLib.tables._g_l_y_f import _ComponentExpansionResult

    selector = expand_components if expand_components is not None else components
    if isinstance(glyph, str) and glyph_name is None:
        glyph_name, glyph = glyph, None
    if glyph is None:
        if glyph_name is None or glyphSet is None:
            raise TypeError("glyph or (glyphSet and glyph_name) is required")
        glyph = glyphSet[glyph_name]

    penClass = TTGlyphPointPen if point else TTGlyphPen
    pen = penClass(glyphSet, expand_components=selector, **kwargs)
    if point:
        glyph.drawPoints(pen)
    else:
        glyph.draw(pen)
    result = pen.glyph()
    return _ComponentExpansionResult(result, list(pen.contour_sources))


expandComponents = expand_components


decompose_components = expand_components
decomposeComponents = expandComponents
