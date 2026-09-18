"""Tests de la auditoría de swaps (`swap_audit`).

Verifican el cálculo con specs sintéticas en modo POINTS (el estándar de CFDs
de índice en Exness): la conversión de swap en puntos a % anualizado del
notional y el costo sobre el gross profit. Los valores del CSV de mt5-sync
siguen el formato "name;digits;point;spread;tick_value;tick_size;contract;
swap_long;swap_short;...".
"""

import pytest

from sqxtools.swap_audit import (annualized_swap_pct, audit, daily_swap_account_ccy,
                                 load_specs, point_value_per_lot, swap_drag)


def _make_csv(tmp_path, rows):
    p = tmp_path / "sqx_specs.csv"
    header = ("name;digits;point;spread;tick_value;tick_size;contract;"
              "swap_long;swap_short;description;path;exists")
    p.write_text(header + "\n" + "\n".join(rows), encoding="utf-8")
    return str(p)


@pytest.fixture
def specs_csv(tmp_path):
    # NAS100 a 20000, tick 0.01 = 1.0 USD, contrato 1.0. Swap short -0.7 pts/noche.
    return _make_csv(tmp_path, [
        "USTECm;2;0.01;112;1.0;0.01;1.0;-0.8;-0.7;Tech;.;1",
        "US30m;2;0.01;40;1.0;0.01;1.0;0.5;-0.3;Dow;.;1",
        "XAUUSDm;2;0.01;180;0.01;0.01;100.0;-1.0;0.2;Gold;.;1",
    ])


class TestPointValue:
    def test_point_value(self):
        # tick_value=1.0, tick_size=0.01, point=0.01 → point_value=1.0
        spec = {"tick_value": 1.0, "tick_size": 0.01, "point": 0.01}
        assert point_value_per_lot(spec) == pytest.approx(1.0)

    def test_zero_tick_size(self):
        assert point_value_per_lot({"tick_value": 1.0, "tick_size": 0.0,
                                    "point": 0.01}) == 0.0


class TestDailySwap:
    def test_short_swap_points(self, specs_csv):
        specs = load_specs(specs_csv)
        # _norm convierte USTECm → USTEC (sufijo broker)
        s = specs["USTEC"]
        # swap_short=-0.7 pts, point_value=1.0 → -0.7 por noche
        assert daily_swap_account_ccy(s, direction="short") == pytest.approx(-0.7)
        # swap_long=-0.8
        assert daily_swap_account_ccy(s, direction="long") == pytest.approx(-0.8)

    def test_scales_with_lots(self, specs_csv):
        specs = load_specs(specs_csv)
        s = specs["USTEC"]
        assert daily_swap_account_ccy(s, direction="short", lots=2.0) == pytest.approx(-1.4)


class TestAnnualized:
    def test_interest_roundtrip_logic(self, specs_csv):
        """En modo INTEREST el % anualizado es exactamente el swap; aquí con
        POINTS la conversión es la que le da sentido económico al número."""
        specs = load_specs(specs_csv)
        s = specs["USTEC"]
        swap, notional, pct_night, pct_year = annualized_swap_pct(
            s, direction="short", price=20000.0)
        # notional = 20000 * 1.0 * 1.0 = 20000
        assert notional == pytest.approx(20000.0)
        # swap/noche = -0.7 → pct_night = -0.7/20000*100 = -0.0035%
        assert pct_night == pytest.approx(-0.7 / 20000.0 * 100.0)
        assert pct_year == pytest.approx(pct_night * 360.0)


class TestSwapDrag:
    def test_drag_computation(self):
        d = swap_drag(swap_per_night=-0.7, avg_hold_nights=4.0,
                      n_trades=100, gross_profit=1000.0)
        # total = -0.7 * 4 * 100 = -280 → 28% del gross profit
        assert d["total_swap"] == pytest.approx(-280.0)
        assert d["swap_share_pct"] == pytest.approx(28.0)

    def test_drag_zero_gross(self):
        d = swap_drag(-0.7, 4.0, 100, gross_profit=0.0)
        assert d["swap_share_pct"] == 0.0


class TestAudit:
    def test_audit_render(self, specs_csv):
        a = audit(specs_csv, "USTECm", direction="short", price=20000.0,
                  avg_hold_nights=4.0, n_trades=100, gross_profit=1000.0)
        assert a.symbol == "USTECm"
        assert a.mode == "points"
        assert a.drag is not None
        txt = a.render()
        assert "Swap audit" in txt and "28.0% del gross profit" in txt

    def test_audit_unknown_symbol(self, specs_csv):
        with pytest.raises(ValueError):
            audit(specs_csv, "EURUSD")

    def test_normalization(self, specs_csv):
        """El sufijo _exness/mc se normaliza al buscar el símbolo."""
        a = audit(specs_csv, "USTECm_exness", direction="short", price=20000.0)
        assert a.symbol == "USTECm_exness"  # conserva lo pedido, busca normalizado
