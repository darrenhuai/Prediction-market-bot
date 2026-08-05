"""Unit tests for src.common.util.package.package_data."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from src.common.util.package import package_data


class TestPackageData:
    def test_missing_data_dir_returns_false(self, tmp_path):
        missing_dir = tmp_path / "does-not-exist"
        output_path = tmp_path / "data.tar.zst"
        assert package_data(data_dir=missing_dir, output_path=output_path) is False
        assert not output_path.exists()

    def test_successful_package_returns_true_and_invokes_tar_zstd(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        output_path = tmp_path / "data.tar.zst"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            assert package_data(data_dir=data_dir, output_path=output_path) is True

        mock_run.assert_called_once_with(
            ["tar", "--zstd", "-cf", str(output_path), str(data_dir)],
            capture_output=True,
            text=True,
        )

    def test_tar_failure_returns_false(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        output_path = tmp_path / "data.tar.zst"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="tar: some error"
            )
            assert package_data(data_dir=data_dir, output_path=output_path) is False
