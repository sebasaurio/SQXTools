"""Tests del parser de Custom Projects."""
import json
import zipfile
from pathlib import Path

import pytest

from sqxtools.project_parser import format_project, parse_project, project_to_dict

FIXTURES = Path(__file__).parent / "fixtures"


def _minimal_project(path: Path) -> None:
    """Crea un .cfx de project mínimo: 1 Build + 1 Retest + 1 Filtering + GoTo."""
    manifest = """<?xml version="1.0"?>
<Project name="Test Project" version="144.2938">
  <Tasks>
    <Task type="Build" name="Build 1" active="true" taskXMLFile="Build-Task1.xml"
          title="Build test" templateFile="C:\\x\\tpl.cfx" />
    <Task type="Retest" name="Retest 1" active="true" taskXMLFile="Retest-Task1.xml"
          title="Seq Opt" />
    <Task type="Filtering" name="Filter 1" active="true" taskXMLFile="Filtering-Task1.xml"
          title="Seq FAILED" />
    <Task type="GoToTask" name="Loop" active="true" taskXMLFile="GoToTask-Task1.xml" />
  </Tasks>
  <Databanks>
    <Databank name="Results" position="0" syncType="Auto-sync never" />
    <Databank name="FAILED" position="700" syncType="Auto-sync every 1 hour" />
  </Databanks>
</Project>"""
    build = """<?xml version="1.0"?>
<Settings>
  <Options customSettings="false"><BuildTradingOptions><Params>
    <Param key="DontTradeOnWeekends" className="DontTradeOnWeekends">true</Param>
    <Param key="MaxTradesPerDay" className="MaxTradesPerDay">6</Param>
    <Param key="SignalTimeRangeFrom" className="LimitTimeRange">28800</Param>
  </Params></BuildTradingOptions></Options>
  <Data><Setups><Setup dateFrom="2020.01.01" dateTo="2024.01.01" engine="MT5" slippage="2">
    <Chart symbol="USATECHIDXUSD_exness" timeframe="H1" spread="112" />
  </Setup></Setups>
  <OutOfSample showGraph="true">
    <Range dateFrom="2020.01.01" dateTo="2022.01.01" type="isv" />
    <Range dateFrom="2022.01.01" dateTo="2024.01.01" />
  </OutOfSample></Data>
  <Rankings type="never" />
  <Blocks type="simple" version="144.2938">
    <Block name="RSIFalling" type="signal" use="true"><Params /></Block>
    <Block name="Indicators.RSI" type="indicator"><Params /></Block>
  </Blocks>
</Settings>"""
    retest = """<?xml version="1.0"?>
<Settings>
  <Data><Setups><Setup dateFrom="2020.01.01" dateTo="2024.01.01" engine="MT5" slippage="2">
    <Chart symbol="USATECHIDXUSD_exness" timeframe="H1" />
  </Setup></Setups></Data>
  <CrossChecks use="true" evaluateAll="false">
    <SequentialOptimization use="true">
      <AcceptanceSettings><PctToPass>90</PctToPass><ResultsCount>20</ResultsCount></AcceptanceSettings>
    </SequentialOptimization>
    <MonteCarloRetest use="false" />
  </CrossChecks>
  <Databanks>
    <Databank label="Input databank" name="Input" value="Results" />
  </Databanks>
</Settings>"""
    filtering = """<?xml version="1.0"?>
<Settings>
  <Filtering><ActionType>2</ActionType><MaxStrategies>0</MaxStrategies>
    <ConditionsType>3</ConditionsType><Conditions /></Filtering>
  <Databanks>
    <Databank label="Source databank" name="Source" value="Results" />
    <Databank label="Target databank" name="Target" value="FAILED" />
  </Databanks>
</Settings>"""
    goto = """<?xml version="1.0"?>
<Settings><GoToTask task="Build 1"><Task /><Conditions /></GoToTask></Settings>"""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.xml", manifest)
        z.writestr("Build-Task1.xml", build)
        z.writestr("Retest-Task1.xml", retest)
        z.writestr("Filtering-Task1.xml", filtering)
        z.writestr("GoToTask-Task1.xml", goto)


@pytest.fixture(scope="module")
def project_cfx(tmp_path_factory):
    d = tmp_path_factory.mktemp("proj")
    p = d / "test_project.cfx"
    _minimal_project(p)
    return p


class TestParseProject:
    def test_lee_manifiesto(self, project_cfx):
        proj = parse_project(project_cfx)
        assert proj.name == "Test Project"
        assert proj.version == "144.2938"
        assert len(proj.tasks) == 4
        assert len(proj.databanks) == 2

    def test_tipos_y_orden(self, project_cfx):
        proj = parse_project(project_cfx)
        assert [t.type for t in proj.tasks] == ["Build", "Retest", "Filtering", "GoToTask"]
        assert [t.index for t in proj.tasks] == [1, 2, 3, 4]

    def test_build_digest(self, project_cfx):
        proj = parse_project(project_cfx)
        build = proj.by_type("Build")[0]
        assert build.digest["data"]["symbol"] == "USATECHIDXUSD_exness"
        assert build.digest["data"]["timeframe"] == "H1"
        assert build.digest["trading"]["MaxTradesPerDay"] == 6
        assert build.digest["trading"]["SignalTimeRangeFrom"] == "08:00"  # 28800 segs
        assert build.digest["blocks"]["total"] == 2
        assert build.digest["blocks"]["active"] == 1

    def test_oos_ranges(self, project_cfx):
        proj = parse_project(project_cfx)
        build = proj.by_type("Build")[0]
        ranges = build.digest["data"]["oos_ranges"]
        assert [r["type"] for r in ranges] == ["isv", "oos"]

    def test_retest_un_crosscheck(self, project_cfx):
        proj = parse_project(project_cfx)
        retest = proj.by_type("Retest")[0]
        assert retest.cross_check() == "SequentialOptimization"
        cc = retest.digest["cross_checks"]["active"][0]
        assert cc["PctToPass"] == 90

    def test_filtering_databanks(self, project_cfx):
        proj = parse_project(project_cfx)
        filt = proj.by_type("Filtering")[0]
        assert filt.digest["filtering"]["action"] == "move"
        assert filt.digest["databanks"]["source"] == "Results"
        assert filt.digest["databanks"]["target"] == "FAILED"

    def test_goto(self, project_cfx):
        proj = parse_project(project_cfx)
        goto = proj.tasks[-1]
        assert goto.digest["goto"] == "Build 1"

    def test_no_es_project_lanza(self, tmp_path):
        p = tmp_path / "no_project.cfx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("otro.xml", "<x/>")
        with pytest.raises(ValueError):
            parse_project(p)


class TestFormat:
    def test_markdown_workflow_y_pipeline(self, project_cfx):
        md = format_project(parse_project(project_cfx))
        assert "# Custom Project: Test Project" in md
        assert "[Build] Build test" in md
        assert "cross-check: **SequentialOptimization**" in md
        assert "Pipeline de robustez" in md
        assert "→ vuelve a **Build 1** (loop)" in md
        assert "move → FAILED" in md

    def test_markdown_trading_con_hora(self, project_cfx):
        md = format_project(parse_project(project_cfx))
        assert "MaxTradesPerDay=6" in md
        assert "SignalTimeRangeFrom=08:00" in md

    def test_json_roundtrip(self, project_cfx):
        d = project_to_dict(parse_project(project_cfx))
        s = json.dumps(d, ensure_ascii=False)
        assert json.loads(s)["n_tasks"] == 4
        tasks = d["tasks"]
        assert tasks[1]["cross_check"] == "SequentialOptimization"
        assert tasks[3]["digest"]["goto"] == "Build 1"


class TestProjectReal:
    """El Custom Project real del usuario (si existe en cache)."""

    REAL = Path("/home/sebas/.hermes/cache/documents/doc_998bb3392d1f_NASDAQ - SELL - H1 BotPulse Academy.cfx")

    @pytest.mark.skipif(not REAL.exists(), reason="fixture real no disponible")
    def test_workflow_completo(self):
        proj = parse_project(self.REAL)
        assert len(proj.tasks) == 21
        assert len(proj.by_type("Build")) == 4
        assert len(proj.by_type("Retest")) == 6
        assert len(proj.by_type("Filtering")) == 8
        # cada retest corre exactamente un cross-check
        retests = proj.by_type("Retest")
        checks = {t.cross_check() for t in retests}
        assert checks == {
            "SequentialOptimization", "RetestWithHigherPrecision",
            "MonteCarloManipulation", "WalkForwardMatrix",
            "MonteCarloRetest", "OptProfileSysParamPermutation",
        }
        # build activo usa la plantilla v8
        activos = [t for t in proj.by_type("Build") if t.active]
        assert len(activos) == 1
        assert activos[0].template_file.endswith("v8_robustez.cfx")
        # databank PASS existe
        assert any(d["name"] == "✅ PASS" for d in proj.databanks)
