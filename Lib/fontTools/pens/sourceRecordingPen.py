from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.componentExpansionPen import ComponentExpansionPen

__all__ = ["SourceRecordingPen", "SelectiveDecomposingRecordingPen"]


class SourceRecordingPen(ComponentExpansionPen):
    """Selective expansion pen that records into an internal RecordingPen."""

    def __init__(self, glyphSet, expand=None, **kwargs):
        recorder = RecordingPen()
        super().__init__(recorder, glyphSet, expand, **kwargs)

    @property
    def recording(self):
        return self._outPen.value


class SelectiveDecomposingRecordingPen(SourceRecordingPen):
    pass
