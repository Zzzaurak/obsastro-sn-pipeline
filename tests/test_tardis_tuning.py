from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from src import tardis_tuning as tt


class TardisTuningTests(unittest.TestCase):
    def test_candidate_grid_applies_offsets_and_limits_count(self) -> None:
        base = tt.TargetSeed(
            target="SNTEST",
            sn_type="SN Ia",
            sn_family="Ia",
            z=0.01,
            spectrum_file="data/SNTEST/spec.fits",
            log_lsun=9.2,
            time_explosion_days=18.0,
            v_start_kms=7000.0,
            v_stop_kms=16000.0,
        )

        candidates = tt.generate_candidates(
            base,
            luminosity_offsets=[0.0, 0.2],
            epoch_offsets=[0.0],
            velocity_scales=[1.0, 1.1],
            abundance_presets=["ia_standard"],
            density_profiles=["branch85_w7"],
            max_candidates=3,
        )

        self.assertEqual([c.candidate_id for c in candidates], ["SNTEST_c000", "SNTEST_c001", "SNTEST_c002"])
        self.assertEqual(candidates[1].log_lsun, 9.2)
        self.assertAlmostEqual(candidates[1].v_start_kms, 7700.0)
        self.assertEqual(candidates[2].log_lsun, 9.4)

    def test_continuum_normalize_recovers_absorption_trough(self) -> None:
        wave = np.linspace(5000.0, 7000.0, 401)
        continuum = 2.0 + 0.0002 * (wave - 6000.0)
        trough = 1.0 - 0.35 * np.exp(-0.5 * ((wave - 6100.0) / 80.0) ** 2)
        normalized = tt.continuum_normalize(wave, continuum * trough, window_pixels=61)

        idx = int(np.argmin(np.abs(wave - 6100.0)))
        self.assertLess(normalized[idx], 0.8)
        self.assertGreater(np.nanmedian(normalized), 0.9)

    def test_score_prefers_matching_trough_position(self) -> None:
        wave = np.linspace(5600.0, 6600.0, 501)
        obs_flux = 1.0 - 0.4 * np.exp(-0.5 * ((wave - 6100.0) / 60.0) ** 2)
        good_flux = 1.0 - 0.35 * np.exp(-0.5 * ((wave - 6110.0) / 65.0) ** 2)
        bad_flux = 1.0 - 0.35 * np.exp(-0.5 * ((wave - 6350.0) / 65.0) ** 2)

        good = tt.score_spectra(
            wave,
            obs_flux,
            wave,
            good_flux,
            line_windows=[tt.LineWindow("SiII6355", 5900.0, 6300.0)],
        )
        bad = tt.score_spectra(
            wave,
            obs_flux,
            wave,
            bad_flux,
            line_windows=[tt.LineWindow("SiII6355", 5900.0, 6300.0)],
        )

        self.assertLess(good.total_score, bad.total_score)
        self.assertLess(good.min_offset_A, bad.min_offset_A)

    def test_build_config_uses_project_atom_data_and_family_preset(self) -> None:
        candidate = tt.TardisCandidate(
            target="SN2026KIE",
            candidate_id="SN2026KIE_c000",
            sn_family="Ibc",
            log_lsun=8.9,
            time_explosion_days=24.0,
            v_start_kms=6000.0,
            v_stop_kms=18000.0,
            density_profile="power_law",
            abundance_preset="ic_oxygen_rich",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            config = tt.build_tardis_config(candidate, project_root=root, packet_scale="quick")

        self.assertEqual(config["atom_data"], str((root / "data" / "kurucz_cd23_chianti_H_He_latest.h5").resolve()))
        self.assertEqual(config["model"]["structure"]["density"]["type"], "power_law")
        self.assertEqual(config["model"]["abundances"]["type"], "uniform")
        self.assertIn("O", config["model"]["abundances"])
        self.assertEqual(config["montecarlo"]["iterations"], 3)


if __name__ == "__main__":
    unittest.main()
