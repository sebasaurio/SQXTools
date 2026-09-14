"""Tests de project_checks: sniff, inspect y check_project."""
import json
from pathlib import Path

import pytest

from sqxtools.project_checks import (
    Finding,
    check_project,
    format_findings,
    inspect_file,
    sniff,
)
from sqxtools.project_parser import parse_project

from .test_project import _minimal_project


@pytest.fixture(scope="module")
def project_cfx(tmp_path_factory):
    d = tmp_path_factory.mktemp("checks")
    p = d / "test_project.cfx"
    _minimal_project(p)
    return p


class TestSniff:
    def test_project(self, project_cfx):
        info = sniff(project_cfx)
        assert info["kind"] == "project"
        assert info["name"] == "Test Project"
        assert info["n_tasks"] == 4

    def test_no_zip(self, tmp_path):
        p = tmp_path / "x.cfx"
        p.write_bytes(b"not a zip")
        assert sniff(p)["kind"] == "unknown"

    def test_inexistente(self, tmp_path):
        assert sniff(tmp_path / "nope.cfx")["kind"] == "missing"


class TestInspect:
    def test_project_incluye_checks(self, project_cfx):
        r = inspect_file(project_cfx)
        assert r["kind"] == "project"
        assert r["project"]["name"] == "Test Project"
        assert isinstance(r["checks"], list)

    def test_json_serializable(self, project_cfx):
        r = inspect_file(project_cfx)
        json.dumps(r, ensure_ascii=False)  # no debe lanzar


class TestCheckProject:
    def test_workflow_minimo_sin_errores(self, project_cfx):
        """El fixture mínimo: Build→Retest(SeqOpt)→Filtering→GoTo al Build 1 (activo)."""
        proj = parse_project(project_cfx)
        findings = check_project(proj)
        errors = [f for f in findings if f.severity == "error"]
        assert errors == []

    def test_goto_a_task_inactiva_es_error(self, project_cfx):
        proj = parse_project(project_cfx)
        proj.tasks[0].active = False  # Build 1 objetivo del GoTo
        findings = check_project(proj)
        codes = {f.code for f in findings}
        assert "goto_a_inactiva" in codes

    def test_retest_sin_filtering(self, project_cfx):
        proj = parse_project(project_cfx)
        proj.tasks[2].active = False  # Filtering FAILED
        findings = check_project(proj)
        codes = {f.code for f in findings}
        assert "retest_sin_filtering" in codes

    def test_loop_sin_cleardatabanks(self, project_cfx):
        proj = parse_project(project_cfx)
        findings = check_project(proj)
        codes = {f.code for f in findings}
        assert "cleardatabanks_inactivo" in codes or "sin_cleardatabanks" in codes


class TestFinding:
    def test_repr_y_dict(self):
        f = Finding("warning", 5, "codigo", "mensaje", "sugerencia")
        assert "(task 5)" in repr(f)
        d = f.to_dict()
        assert d["task"] == 5 and d["suggestion"] == "sugerencia"

    def test_format_vacio(self):
        assert "Sin problemas" in format_findings([])


class TestProjectReal:
    """El project real del usuario (si está en cache)."""

    REAL = Path("/home/sebas/.hermes/cache/documents/doc_998bb3392d1f_NASDAQ - SELL - H1 BotPulse Academy.cfx")

    @pytest.mark.skipif(not REAL.exists(), reason="fixture real no disponible")
    def test_findings_conocidos(self):
        proj = parse_project(self.REAL)
        findings = check_project(proj)
        codes = {f.code for f in findings}
        # lo que el análisis manual detectó debe ser detectado mecánicamente
        assert "databank_desalineado" in codes      # Build escribe 'Last generation'
        assert "oos_desalineado" in codes           # cortes ISV/OOS difieren por task
        assert "cleardatabanks_inactivo" in codes   # loop sin limpieza
        # y no debe haber errores duros (el workflow es válido, mejorable)
        assert not [f for f in findings if f.severity == "error"]
