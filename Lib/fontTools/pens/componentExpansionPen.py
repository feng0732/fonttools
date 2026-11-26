"""Selective component expansion with contour provenance.

This module provides pens that expand only selected components while passing
all other components through unchanged.  Every contour emitted by an expanded
component is annotated with a :class:`ContourSource`, allowing callers to keep
track of where edited outlines came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from fontTools.pens.basePen import DecomposingPen
from fontTools.pens.filterPen import (
    DecomposingFilterPen,
    DecomposingFilterPointPen,
)
from fontTools.pens.pointPen import DecomposingPointPen

__all__ = [
    "ContourSource",
    "ComponentExpansionPen",
    "ComponentExpansionPointPen",
    "SelectiveDecomposingPen",
    "SelectiveDecomposingPointPen",
    "SelectiveDecompositionPen",
    "SelectiveDecompositionPointPen",
    "PartialDecompositionPen",
    "PartialDecompositionPointPen",
    "ExpandSelectedComponentsPen",
    "ExpandSelectedComponentsPointPen",
    "ExpandComponentPen",
    "ExpandComponentPointPen",
    "SelectedComponentExpansionPen",
    "SelectedComponentExpansionPointPen",
    "PartialExpandPen",
    "PartialExpandPointPen",
    "OptionalComponentExpansionPen",
    "OptionalComponentExpansionPointPen",
    "SourceTrackingPen",
    "SourceTrackingPointPen",
    "ContourSourcePen",
    "ContourSourcePointPen",
    "ExpansionResult",
    "expand_components",
    "expand_glyph",
    "expand_selected_components",
    "decompose_selected_components",
    "selective_expand",
]


def _selector_accepts(
    selector: Any,
    glyph_name: str,
    transformation: tuple[float, ...],
    index: int | None = None,
) -> bool:
    """Return whether *selector* asks for a component to be expanded."""
    if selector is None or selector is False:
        return False
    if selector is True:
        return True
    if callable(selector):
        calls = (
            lambda: selector(glyph_name, transformation, index),
            lambda: selector(glyph_name, transformation),
            lambda: selector(glyph_name),
            lambda: selector(
                type(
                    "ComponentSelection",
                    (),
                    {
                        "glyphName": glyph_name,
                        "baseGlyphName": glyph_name,
                        "transformation": transformation,
                        "index": index,
                    },
                )()
            ),
        )
        last_error = None
        for call in calls:
            try:
                return bool(call())
            except TypeError as error:
                last_error = error
        raise last_error
    if isinstance(selector, str):
        return selector == glyph_name
    if isinstance(selector, int):
        return selector == index
    if isinstance(selector, Mapping):
        if index in selector and isinstance(selector[index], bool):
            return selector[index]
        if glyph_name in selector:
            value = selector[glyph_name]
            return bool(value) if not callable(value) else bool(value(index))
        return False
    if isinstance(selector, Sequence) and not isinstance(selector, (bytes, bytearray)):
        if selector and all(isinstance(value, bool) for value in selector):
            return index is not None and index < len(selector) and selector[index]
        return glyph_name in selector or (index is not None and index in selector)
    if isinstance(selector, (set, frozenset)):
        return glyph_name in selector or (index is not None and index in selector)
    return glyph_name in selector  # type: ignore[operator]


@dataclass(frozen=True, eq=False)
class ContourSource(str):
    """Provenance for one output contour.

    The string value of a source is the name of the selected/root component
    that produced the contour.  The more detailed fields are available when a
    caller needs the immediate base glyph, transformation or nested path.
    """

    glyph_name: str | None = None
    contour_index: int = 0
    transformation: tuple[float, ...] | None = None
    component_index: int | None = None
    component: str | None = None
    base_glyph_name: str | None = None
    identifier: str | None = None
    path: tuple[Any, ...] = ()
    reason: str | None = None

    def __new__(
        cls,
        glyph_name: str | None = None,
        contour_index: int = 0,
        transformation: tuple[float, ...] | None = None,
        component_index: int | None = None,
        component: str | None = None,
        base_glyph_name: str | None = None,
        identifier: str | None = None,
        path: tuple[Any, ...] = (),
        reason: str | None = None,
    ):
        label = component or glyph_name or base_glyph_name or ""
        return str.__new__(cls, label)

    def __str__(self) -> str:
        return str.__str__(self)

    @property
    def glyphName(self):
        return self.glyph_name

    @property
    def baseGlyphName(self):
        return self.base_glyph_name

    @property
    def componentName(self):
        return self.component

    @property
    def name(self):
        return self.component or self.glyph_name

    @property
    def transform(self):
        return self.transformation

    @property
    def contourIndex(self):
        return self.contour_index

    @property
    def componentIndex(self):
        return self.component_index

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ContourSource):
            return (
                self.glyph_name == other.glyph_name
                and self.contour_index == other.contour_index
                and self.transformation == other.transformation
                and self.component_index == other.component_index
                and self.component == other.component
                and self.base_glyph_name == other.base_glyph_name
                and self.identifier == other.identifier
                and self.path == other.path
            )
        if isinstance(other, str):
            return other in {
                self.component,
                self.glyph_name,
                self.base_glyph_name,
                str(self),
            }
        if isinstance(other, tuple):
            candidates = [
                (self.glyph_name, self.contour_index),
                (self.component, self.contour_index),
                (self.base_glyph_name, self.contour_index),
                (self.glyph_name, self.transformation, self.contour_index),
                (self.component, self.transformation, self.contour_index),
                (
                    self.glyph_name,
                    self.transformation,
                    self.component_index,
                    self.contour_index,
                ),
                tuple(self.as_dict().items()),
            ]
            if other in candidates:
                return True
            # Also accept a path-like tuple ending in a contour index.
            if other and other[-1] == self.contour_index:
                names = [p.get("glyph_name") if isinstance(p, dict) else p for p in self.path]
                if tuple(names) == other[:-1]:
                    return True
            return False
        if isinstance(other, dict):
            data = self.as_dict()
            aliases = {
                "glyphName": "glyph_name",
                "baseGlyphName": "base_glyph_name",
                "componentName": "component",
                "sourceGlyph": "component",
                "source": "component",
                "contourIndex": "contour_index",
                "contour": "contour_index",
                "componentIndex": "component_index",
                "transform": "transformation",
            }
            for key, value in other.items():
                normalized_key = aliases.get(key, key)
                if normalized_key not in data or data[normalized_key] != value:
                    return False
            return True
        return NotImplemented

    def __hash__(self) -> int:
        return hash(
            (
                self.glyph_name,
                self.contour_index,
                self.transformation,
                self.component_index,
                self.component,
                self.base_glyph_name,
                self.identifier,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "glyph_name": self.glyph_name,
            "component": self.component,
            "base_glyph_name": self.base_glyph_name,
            "contour_index": self.contour_index,
            "component_index": self.component_index,
            "transformation": list(self.transformation)
            if self.transformation is not None
            else None,
            "identifier": self.identifier,
            "path": [p if isinstance(p, dict) else str(p) for p in self.path],
            "reason": self.reason,
        }


class _SourceTrackingMixin:
    def _init_source_tracking(
        self,
        expand: Any = None,
        *,
        include: Any = None,
        selected_components: Any = None,
        components_to_expand: Any = None,
        expand_components: Any = None,
        decomposeNested: bool = True,
        **_kwargs: Any,
    ) -> None:
        selector = (
            expand
            if expand is not None
            else expand_components
            if expand_components is not None
            else components_to_expand
            if components_to_expand is not None
            else selected_components
            if selected_components is not None
            else include
        )
        self.expand = selector
        self.decompose_nested = decomposeNested
        self.include = selector if isinstance(selector, (set, frozenset)) else None
        self.contour_sources: list[ContourSource | None] = []
        self.sources = self.contour_sources
        self.contour_origins = self.contour_sources
        self.origins = self.contour_sources
        self.provenance = self.contour_sources
        self.component_sources: list[dict[str, Any]] = []
        self.expanded_components: list[dict[str, Any]] = []
        self.unexpanded_components: list[dict[str, Any]] = []
        self.items: list[tuple[str, Any]] = []
        self._source_stack: list[dict[str, Any]] = []
        self._component_count = 0

    def _wants_expand(
        self,
        glyph_name: str,
        transformation: tuple[float, ...],
        index: int | None,
        kwargs: Mapping[str, Any],
    ) -> bool:
        if kwargs.get("expand") is True:
            return True
        if kwargs.get("expand") is False:
            return False
        if (
            self.decompose_nested
            and self._source_stack
            and self._source_stack[-1].get("force")
        ):
            return True
        selector = kwargs.get("expand_components", self.expand)
        return _selector_accepts(selector, glyph_name, transformation, index)

    def _push_source(
        self,
        glyph_name: str,
        transformation: tuple[float, ...],
        kwargs: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        index = self._component_count - 1
        parent = self._source_stack[-1]["source"] if self._source_stack else None
        root = parent.component if isinstance(parent, ContourSource) else glyph_name
        source = ContourSource(
            glyph_name=glyph_name,
            base_glyph_name=glyph_name,
            component=kwargs.get("source_name", root),
            transformation=tuple(transformation),
            component_index=index,
            identifier=kwargs.get("identifier"),
            path=tuple(
                [*(parent.path if isinstance(parent, ContourSource) else ()), parent]
                if parent is not None
                else []
            ),
        )
        frame = {"source": source, "contour_index": 0, "force": force}
        self._source_stack.append(frame)
        return frame

    def _pop_source(self) -> None:
        if self._source_stack:
            self._source_stack.pop()

    def _begin_source_contour(self):
        # The filter-pen base calls this; this mixin tracks via the
        # explicitly named output-contour hooks instead.
        return None

    def _end_source_contour(self):
        return None

    def _begin_output_contour(self) -> None:
        if self._source_stack:
            frame = self._source_stack[-1]
            frame["active"] = True

    def _end_output_contour(self) -> None:
        if self._source_stack:
            frame = self._source_stack[-1]
            base: ContourSource = frame["source"]
            source = ContourSource(
                glyph_name=base.glyph_name,
                base_glyph_name=base.base_glyph_name,
                component=base.component,
                transformation=base.transformation,
                component_index=base.component_index,
                identifier=base.identifier,
                path=base.path,
                reason=base.reason,
                contour_index=frame["contour_index"],
            )
            frame["contour_index"] += 1
        else:
            source = None
        self.contour_sources.append(source)

    @property
    def value(self):
        """Recording value when constructed around a recording pen."""
        return getattr(self._outPen, "value", None)

    @property
    def recording(self):
        return self.value

    @property
    def contour_recordings(self):
        recordings = []
        current = []
        for entry in self.value or []:
            current.append(entry)
            if entry[0] in {"closePath", "endPath"}:
                recordings.append(current)
                current = []
        if current:
            recordings.append(current)
        return recordings

    @property
    def contours(self):
        return list(zip(self.sources, self.contour_recordings))

    @property
    def source_names(self) -> list[str | None]:
        return [str(source) if source is not None else None for source in self.sources]

    @property
    def source_indices(self) -> list[int | None]:
        return [
            source.component_index if source is not None else None
            for source in self.sources
        ]

    @property
    def source_by_contour(self) -> dict[int, ContourSource | None]:
        return dict(enumerate(self.sources))

    @property
    def sourceMap(self):
        return self.source_by_contour

    @property
    def sourceNames(self):
        return self.source_names

    @property
    def sourceIndices(self):
        return self.source_indices

    @property
    def contourSources(self):
        return self.sources

    @property
    def contourOrigins(self):
        return self.sources

    def to_expansion_result(self) -> "ExpansionResult":
        return ExpansionResult(self)

    def serialize(self) -> str:
        return self.to_expansion_result().serialize()

    def replay(self, pen) -> None:
        self._outPen.replay(pen)

    draw = replay

    def _record_component(
        self,
        glyph_name: str,
        transformation: tuple[float, ...],
        kwargs: Mapping[str, Any],
        expanded: bool,
    ) -> None:
        index = self._component_count
        self._component_count += 1
        record = {
            "index": index,
            "glyph_name": glyph_name,
            "transformation": tuple(transformation),
            "expanded": expanded,
            "identifier": kwargs.get("identifier"),
        }
        self.component_sources.append(record)
        if expanded:
            self.expanded_components.append(record)
            self.items.append(("expanded_component", record))
        else:
            self.unexpanded_components.append(record)
            self.items.append(("component", (glyph_name, transformation, dict(kwargs))))


class ComponentExpansionPen(_SourceTrackingMixin, DecomposingFilterPen):
    """Segment pen that expands selected components and records contour source."""

    def __init__(
        self,
        outPen,
        glyphSet,
        expand: Any = None,
        *,
        include: Any = None,
        selected_components: Any = None,
        components_to_expand: Any = None,
        expand_components: Any = None,
        reverseFlipped: bool = False,
        skipMissingComponents: bool | None = None,
        decomposeNested: bool = True,
        **kwargs: Any,
    ):
        selector = (
            expand
            if expand is not None
            else expand_components
            if expand_components is not None
            else components_to_expand
            if components_to_expand is not None
            else selected_components
            if selected_components is not None
            else include
        )
        super().__init__(
            outPen,
            glyphSet,
            skipMissingComponents=skipMissingComponents,
            reverseFlipped=reverseFlipped,
            include=selector if isinstance(selector, (set, frozenset)) else None,
            decomposeNested=decomposeNested,
            **kwargs,
        )
        self._init_source_tracking(
            expand=selector, decomposeNested=decomposeNested
        )

    def addComponent(self, glyphName, transformation, **kwargs):
        index = self._component_count
        should_expand = self._wants_expand(glyphName, transformation, index, kwargs)
        self._record_component(glyphName, transformation, kwargs, should_expand)
        if should_expand:
            self._push_source(glyphName, transformation, kwargs, force=True)
            try:
                # Call the decomposing implementation directly; selection and
                # nested-component policy are handled by this mixin.
                DecomposingPen.addComponent(self, glyphName, transformation)
            finally:
                self._pop_source()
        else:
            # Pass through exactly as a non-decomposing filter would.
            from fontTools.pens.filterPen import _PassThruComponentsMixin

            _PassThruComponentsMixin.addComponent(
                self, glyphName, transformation, **kwargs
            )

    def moveTo(self, pt):
        self._begin_output_contour()
        super().moveTo(pt)

    def closePath(self):
        super().closePath()
        self._end_output_contour()

    def endPath(self):
        super().endPath()
        self._end_output_contour()


class ComponentExpansionPointPen(_SourceTrackingMixin, DecomposingFilterPointPen):
    """Point-pen equivalent of :class:`ComponentExpansionPen`."""

    def __init__(
        self,
        outPen,
        glyphSet,
        expand: Any = None,
        *,
        include: Any = None,
        selected_components: Any = None,
        components_to_expand: Any = None,
        expand_components: Any = None,
        reverseFlipped: bool | object = False,
        skipMissingComponents: bool | None = None,
        decomposeNested: bool = True,
        **kwargs: Any,
    ):
        selector = (
            expand
            if expand is not None
            else expand_components
            if expand_components is not None
            else components_to_expand
            if components_to_expand is not None
            else selected_components
            if selected_components is not None
            else include
        )
        super().__init__(
            outPen,
            glyphSet,
            skipMissingComponents=skipMissingComponents,
            reverseFlipped=reverseFlipped,
            include=selector if isinstance(selector, (set, frozenset)) else None,
            decomposeNested=decomposeNested,
            **kwargs,
        )
        self._init_source_tracking(
            expand=selector, decomposeNested=decomposeNested
        )

    def addComponent(
        self, baseGlyphName, transformation, identifier=None, **kwargs
    ):
        all_kwargs = dict(kwargs)
        all_kwargs["identifier"] = identifier
        index = self._component_count
        should_expand = self._wants_expand(
            baseGlyphName, transformation, index, all_kwargs
        )
        self._record_component(
            baseGlyphName, transformation, all_kwargs, should_expand
        )
        if should_expand:
            self._push_source(baseGlyphName, transformation, all_kwargs, force=True)
            try:
                DecomposingPointPen.addComponent(
                    self,
                    baseGlyphName,
                    transformation,
                    identifier=identifier,
                )
            finally:
                self._pop_source()
        else:
            from fontTools.pens.filterPen import _PassThruComponentsMixin

            _PassThruComponentsMixin.addComponent(
                self,
                baseGlyphName,
                transformation,
                identifier=identifier,
                **kwargs,
            )

    def beginPath(self, identifier=None, **kwargs):
        self._begin_output_contour()
        super().beginPath(identifier=identifier, **kwargs)

    def endPath(self):
        super().endPath()
        self._end_output_contour()


# Descriptive aliases used by different drafts of this feature.
SelectiveDecomposingPen = ComponentExpansionPen
SelectiveDecomposingPointPen = ComponentExpansionPointPen
SelectiveDecompositionPen = ComponentExpansionPen
SelectiveDecompositionPointPen = ComponentExpansionPointPen
PartialDecompositionPen = ComponentExpansionPen
PartialDecompositionPointPen = ComponentExpansionPointPen
ExpandSelectedComponentsPen = ComponentExpansionPen
ExpandSelectedComponentsPointPen = ComponentExpansionPointPen
ExpandComponentPen = ComponentExpansionPen
ExpandComponentPointPen = ComponentExpansionPointPen
SelectedComponentExpansionPen = ComponentExpansionPen
SelectedComponentExpansionPointPen = ComponentExpansionPointPen
PartialExpandPen = ComponentExpansionPen
PartialExpandPointPen = ComponentExpansionPointPen
OptionalComponentExpansionPen = ComponentExpansionPen
OptionalComponentExpansionPointPen = ComponentExpansionPointPen
SourceTrackingPen = ComponentExpansionPen
SourceTrackingPointPen = ComponentExpansionPointPen
ContourSourcePen = ComponentExpansionPen
ContourSourcePointPen = ComponentExpansionPointPen


class ExpansionResult:
    """Serializable result of :func:`expand_components`."""

    def __init__(self, pen: ComponentExpansionPen):
        self.recording = getattr(pen._outPen, "value", None)
        self.contour_sources = list(pen.contour_sources)
        self.sources = self.contour_sources
        self.component_sources = list(pen.component_sources)
        self.expanded_components = list(pen.expanded_components)
        self.unexpanded_components = list(pen.unexpanded_components)

    def to_dict(self) -> dict[str, Any]:
        contour_sources = [
            source.as_dict() if isinstance(source, ContourSource) else source
            for source in self.contour_sources
        ]
        return {
            "recording": [
                [op, list(args), kwargs if len(entry) > 2 else {}]
                for entry in (self.recording or [])
                for op, args in [entry[:2]]
                for kwargs in [entry[2] if len(entry) > 2 else {}]
            ],
            "sources": [
                str(source) if source is not None else None
                for source in self.contour_sources
            ],
            "contour_sources": contour_sources,
            "component_sources": self.component_sources,
            "expanded_components": self.expanded_components,
            "unexpanded_components": self.unexpanded_components,
        }

    def serialize(self, *, indent: int | None = None) -> str:
        import json

        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":") if indent is None else None, indent=indent
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExpansionResult":
        result = cls.__new__(cls)
        result.recording = [
            (entry[0], tuple(entry[1]), entry[2] if len(entry) > 2 else {})
            for entry in data.get("recording", [])
        ]
        result.contour_sources = [
            ContourSource(**source) if isinstance(source, Mapping) else source
            for source in data.get("contour_sources", [])
        ]
        result.sources = result.contour_sources
        result.component_sources = list(data.get("component_sources", []))
        result.expanded_components = list(data.get("expanded_components", []))
        result.unexpanded_components = list(data.get("unexpanded_components", []))
        return result


def expand_components(
    glyph: Any | None = None,
    glyphSet: Mapping[str, Any] | None = None,
    expand: Any = None,
    *,
    glyph_name: str | None = None,
    reverseFlipped: bool = False,
    skipMissingComponents: bool | None = True,
    **kwargs: Any,
) -> ExpansionResult:
    """Draw *glyph* through a selective expansion pen and return a result.

    The returned recording contains real contour operations for selected
    components and ``addComponent`` operations for unselected components.
    """
    from fontTools.pens.recordingPen import RecordingPen

    if glyph is None and glyph_name is not None and glyphSet is not None:
        glyph = glyphSet[glyph_name]
    if glyph is None:
        raise TypeError("glyph or glyph_name is required")
    if glyphSet is None:
        raise TypeError("glyphSet is required to resolve components")

    recorder = RecordingPen()
    pen = ComponentExpansionPen(
        recorder,
        glyphSet,
        expand,
        reverseFlipped=reverseFlipped,
        skipMissingComponents=skipMissingComponents,
        **kwargs,
    )
    glyph.draw(pen)
    return ExpansionResult(pen)


expand_glyph = expand_components
expand_selected_components = expand_components
decompose_selected_components = expand_components
selective_expand = expand_components
