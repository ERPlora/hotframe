"""Tests for hotframe.management.cli."""

import os

from typer.testing import CliRunner

from hotframe.management.cli import app

runner = CliRunner()


class TestCLI:
    def test_version(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "hotframe" in result.output

    def test_startproject(self, tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(app, ["startproject", "testproject"])
        assert result.exit_code == 0
        assert (tmp_path / "testproject").exists()
        assert (tmp_path / "testproject" / "main.py").exists()
        assert (tmp_path / "testproject" / "settings.py").exists()
        assert (tmp_path / "testproject" / "asgi.py").exists()
        assert (tmp_path / "testproject" / "manage.py").exists()
        assert (tmp_path / "testproject" / "pyproject.toml").exists()
        assert (tmp_path / "testproject" / ".gitignore").exists()
        assert (tmp_path / "testproject" / ".env").exists()
        assert (tmp_path / "testproject" / "apps").is_dir()
        assert (tmp_path / "testproject" / "modules").is_dir()
        assert (tmp_path / "testproject" / "tests").is_dir()

    def test_startproject_already_exists(self, tmp_path):
        os.chdir(tmp_path)
        (tmp_path / "existing").mkdir()
        result = runner.invoke(app, ["startproject", "existing"])
        assert result.exit_code == 1

    def test_startapp(self, tmp_path):
        os.chdir(tmp_path)
        (tmp_path / "apps").mkdir()
        result = runner.invoke(app, ["startapp", "accounts"])
        assert result.exit_code == 0
        assert (tmp_path / "apps" / "accounts" / "app.py").exists()
        assert (tmp_path / "apps" / "accounts" / "models.py").exists()
        assert (tmp_path / "apps" / "accounts" / "routes.py").exists()

    def test_startmodule(self, tmp_path):
        os.chdir(tmp_path)
        (tmp_path / "modules").mkdir()
        result = runner.invoke(app, ["startmodule", "blog"])
        assert result.exit_code == 0
        assert (tmp_path / "modules" / "blog" / "module.py").exists()
        assert (tmp_path / "modules" / "blog" / "models.py").exists()
        assert (tmp_path / "modules" / "blog" / "routes.py").exists()
