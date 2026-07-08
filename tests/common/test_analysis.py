"""Unit tests for src.common.analysis.Analysis.save()."""

from __future__ import annotations

import pandas as pd
import pytest

from src.common.analysis import Analysis, AnalysisOutput


class _FigureOnlyAnalysis(Analysis):
    def __init__(self):
        super().__init__(name="figure_only", description="test")

    def run(self) -> AnalysisOutput:
        fig, ax = plt_figure()
        ax.plot([1, 2, 3], [1, 4, 9])
        return AnalysisOutput(figure=fig)


class _DataOnlyAnalysis(Analysis):
    def __init__(self):
        super().__init__(name="data_only", description="test")

    def run(self) -> AnalysisOutput:
        return AnalysisOutput(data=pd.DataFrame({"x": [1, 2], "y": [3, 4]}))


class _FigureAndDataAnalysis(Analysis):
    def __init__(self):
        super().__init__(name="figure_and_data", description="test")

    def run(self) -> AnalysisOutput:
        fig, ax = plt_figure()
        ax.plot([1, 2], [3, 4])
        return AnalysisOutput(figure=fig, data=pd.DataFrame({"x": [1, 2]}))


def plt_figure():
    import matplotlib.pyplot as plt

    return plt.subplots()


class TestSave:
    def test_saves_default_formats_for_figure_and_data(self, tmp_path):
        analysis = _FigureAndDataAnalysis()
        saved = analysis.save(tmp_path)
        assert set(saved.keys()) == {"png", "pdf", "csv"}
        for path in saved.values():
            assert path.exists()

    def test_figure_only_skips_csv(self, tmp_path):
        analysis = _FigureOnlyAnalysis()
        saved = analysis.save(tmp_path)
        assert "csv" not in saved
        assert "png" in saved and saved["png"].exists()

    def test_data_only_skips_figure_formats(self, tmp_path):
        analysis = _DataOnlyAnalysis()
        saved = analysis.save(tmp_path)
        assert set(saved.keys()) == {"csv"}
        assert saved["csv"].exists()

    def test_respects_explicit_formats_list(self, tmp_path):
        analysis = _FigureAndDataAnalysis()
        saved = analysis.save(tmp_path, formats=["svg"])
        assert set(saved.keys()) == {"svg"}
        assert saved["svg"].exists()
        assert not (tmp_path / "figure_and_data.png").exists()

    def test_creates_output_directory_if_missing(self, tmp_path):
        nested = tmp_path / "does" / "not" / "exist" / "yet"
        analysis = _DataOnlyAnalysis()
        saved = analysis.save(nested)
        assert nested.exists()
        assert saved["csv"].parent == nested

    def test_csv_content_matches_dataframe(self, tmp_path):
        analysis = _DataOnlyAnalysis()
        saved = analysis.save(tmp_path)
        written = pd.read_csv(saved["csv"])
        pd.testing.assert_frame_equal(written, pd.DataFrame({"x": [1, 2], "y": [3, 4]}))

    def test_closes_figure_after_saving(self, tmp_path):
        import matplotlib.pyplot as plt

        plt.close("all")
        analysis = _FigureOnlyAnalysis()
        analysis.save(tmp_path)
        assert plt.get_fignums() == []

    def test_output_filename_uses_analysis_name(self, tmp_path):
        analysis = _DataOnlyAnalysis()
        saved = analysis.save(tmp_path)
        assert saved["csv"].name == "data_only.csv"


class TestAnalysisIsAbstract:
    def test_cannot_instantiate_analysis_directly(self):
        with pytest.raises(TypeError):
            Analysis(name="x", description="y")  # missing run() implementation
