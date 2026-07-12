"""Tests for the VALD3-short-format parser in wave_explorer.vald."""
import textwrap

import pytest

from wave_explorer.vald import parse_vald_lines


VALD_SAMPLE = textwrap.dedent("""\
     700.00000, 1000.00000, 9913, 9817511, 1.0 Wavelength region, lines selected, lines processed, Vmicro
                                                     Damping parameters   Lande  Central
    Spec Ion      WL_vac(nm) Excit(eV) Vmic log gf*  Rad.   Stark  Waals  factor  depth  Reference
    'TiO 1',       700.00316,  0.9562, 1.0,  0.389, 6.944, 0.000, 0.000, 99.000, 0.123, '   1 wl:PPN2012 (48)TiO       '
    'Fe 1',        700.18136,  4.1034, 1.0, -1.560, 8.410,-5.270,-7.208,  1.410, 0.103, '   2 wl:K14   2 K14 Fe            '
    'Ca 2',        702.50000,  3.0000, 1.0,  0.500, 8.000, 0.000, 0.000,  1.000, 0.250, '   3 ref Ca            '
""")


def test_parse_skips_header_and_returns_entries(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE)
    entries = parse_vald_lines(p)
    assert len(entries) == 3
    e0 = entries[0]
    assert e0["element"] == "TiO"
    assert e0["ion"] == 1
    assert e0["wavelength_nm"] == pytest.approx(700.00316)
    assert e0["excit_ev"] == pytest.approx(0.9562)
    assert e0["log_gf"] == pytest.approx(0.389)
    assert e0["central_depth"] == pytest.approx(0.123)


def test_parse_handles_negative_log_gf_and_ion_2(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE)
    entries = parse_vald_lines(p)
    fe = entries[1]
    assert fe["element"] == "Fe" and fe["ion"] == 1
    assert fe["log_gf"] == pytest.approx(-1.560)
    ca = entries[2]
    assert ca["element"] == "Ca" and ca["ion"] == 2


def test_parse_ignores_blank_and_short_rows(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE + "\n   \nnot-a-line\n")
    entries = parse_vald_lines(p)
    assert len(entries) == 3


def test_parse_returns_sorted_by_wavelength(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE)
    entries = parse_vald_lines(p)
    assert entries == sorted(entries, key=lambda e: e["wavelength_nm"])


import json
import math

from wave_explorer.vald import build_vald_payload


def _entries():
    return [
        {"element": "Fe", "ion": 1, "wavelength_nm": 700.18,
         "excit_ev": 4.10, "log_gf": -1.56, "central_depth": 0.10},
        {"element": "TiO", "ion": 1, "wavelength_nm": 700.00,
         "excit_ev": 0.96, "log_gf":  0.39, "central_depth": 0.12},
        {"element": "Ca", "ion": 2, "wavelength_nm": 850.00,
         "excit_ev": 3.00, "log_gf":  0.50, "central_depth": 0.25},
    ]


def test_payload_clips_to_wavelength_range():
    p = build_vald_payload(_entries(), lambda_min=700.0, lambda_max=701.0)
    assert len(p["lines"]) == 2
    # sorted by wavelength
    assert [ln["wavelength_nm"] for ln in p["lines"]] == [700.00, 700.18]


def test_payload_uses_parallel_arrays():
    p = build_vald_payload(_entries(), lambda_min=600.0, lambda_max=900.0)
    assert p["count"] == 3
    assert "wavelengths" in p and "elements" in p and "ions" in p
    assert "depths" in p and "logGf" in p and "excitEv" in p
    assert len(p["wavelengths"]) == 3
    assert len(p["elements"]) == 3
    # alignment
    i_fe = p["elements"].index("Fe")
    assert p["ions"][i_fe] == 1
    assert math.isclose(p["wavelengths"][i_fe], 700.18)


def test_payload_is_json_serializable():
    p = build_vald_payload(_entries(), lambda_min=600.0, lambda_max=900.0)
    json.dumps(p, allow_nan=False)


def test_payload_handles_empty_input():
    p = build_vald_payload([], lambda_min=600.0, lambda_max=900.0)
    assert p == {"count": 0, "wavelengths": [], "elements": [], "ions": [],
                 "depths": [], "logGf": [], "excitEv": [], "lines": [],
                 "depthMin": 0.0, "depthMax": 0.0}


def test_payload_observed_ranges_filters_inter_order_gaps():
    p = build_vald_payload(
        _entries(),
        lambda_min=600.0, lambda_max=900.0,
        observed_ranges=[(699.5, 700.5), (849.5, 850.5)],
    )
    # All three entries (700.18, 700.00, 850.00) fall inside an observed span
    assert p["count"] == 3
    p2 = build_vald_payload(
        _entries(),
        lambda_min=600.0, lambda_max=900.0,
        observed_ranges=[(699.5, 700.5)],  # excludes 850.00
    )
    assert p2["count"] == 2
    assert 850.00 not in p2["wavelengths"]
