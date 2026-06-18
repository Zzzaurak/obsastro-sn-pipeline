from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from src import spectral_pipeline as sp


def absorption_spectrum(rest: float, center: float, *, depth: float = 0.35, width: float = 55.0) -> tuple[np.ndarray, np.ndarray]:
    wave = np.linspace(rest - 420.0, rest + 420.0, 421)
    continuum = 1.0 + 0.00008 * (wave - rest)
    trough = 1.0 - depth * np.exp(-0.5 * ((wave - center) / width) ** 2)
    return wave, continuum * trough


class SpectralPipelineLiteraturePolicyTests(unittest.TestCase):
    def test_literature_policy_keeps_si5972_as_visual_check_for_ia(self) -> None:
        row = {
            "target": "SNTEST",
            "file": "spec.fits",
            "date_obs": "2026-01-01",
            "phase_days": 5.0,
            "type": "SN Ia",
            "z": 0.01,
            "line": "SiII5972",
            "status": "ok",
            "velocity_kms": 9500.0,
            "FWHM_A": 90.0,
            "depth": 0.35,
            "pEW_A": 40.0,
        }

        out = sp.quality_flag_lines(pd.DataFrame([row]))

        self.assertEqual(out.loc[0, "qc_flag"], "check")
        self.assertIn("secondary line", out.loc[0, "qc_note"])

    def test_literature_policy_keeps_type_ii_balmer_lines_as_visual_check(self) -> None:
        row = {
            "target": "SNTEST",
            "file": "spec.fits",
            "date_obs": "2026-01-01",
            "phase_days": 5.0,
            "type": "SN II",
            "z": 0.001,
            "line": "Halpha",
            "status": "ok",
            "velocity_kms": 8500.0,
            "FWHM_A": 120.0,
            "depth": 0.30,
            "pEW_A": 35.0,
        }

        out = sp.quality_flag_lines(pd.DataFrame([row]))

        self.assertEqual(out.loc[0, "qc_flag"], "check")
        self.assertIn("secondary line", out.loc[0, "qc_note"])

    def test_absorption_measurement_reports_blend_notes_and_systematics(self) -> None:
        wave, flux = absorption_spectrum(6355.0, 6120.0)

        result = sp.measure_absorption_line(wave, flux, "SiII6355", include_systematics=True)

        self.assertEqual(result["fit_method"], "minimum_absorption")
        self.assertEqual(result["rest_wave_choice"], "single_line")
        self.assertGreater(result["n_systematic_variants"], 0)
        self.assertTrue(math.isfinite(result["velocity_sys_kms"]))
        self.assertTrue(math.isfinite(result["pEW_sys_A"]))
        self.assertTrue(math.isfinite(result["FWHM_sys_A"]))

    def test_ca_blends_are_labeled_as_proxy_measurements(self) -> None:
        wave, flux = absorption_spectrum(8579.0, 8220.0, depth=0.25, width=85.0)

        result = sp.measure_absorption_line(wave, flux, "CaIINIR", include_systematics=True)

        self.assertEqual(result["rest_wave_choice"], "blend_proxy")
        self.assertIn("blend", result["line_blend_note"].lower())

    def test_blackbody_temperature_can_be_demoted_for_non_ia_or_missing_redshift(self) -> None:
        adopted = {"T_bb_K": 7000.0, "T_qc_flag": "adopt", "T_qc_note": "residual bootstrap uncertainty"}

        demoted = sp.apply_temperature_context_qc(adopted, sn_type="SN II", z=0.001)
        missing_z = sp.apply_temperature_context_qc(adopted, sn_type="SN Ia", z=np.nan)

        self.assertEqual(demoted["T_qc_flag"], "check")
        self.assertIn("continuum proxy", demoted["T_qc_note"])
        self.assertEqual(missing_z["T_qc_flag"], "check")
        self.assertIn("missing redshift", missing_z["T_qc_note"])

    def test_host_summary_counts_instances_and_unique_lines_separately(self) -> None:
        host_lines = pd.DataFrame(
            [
                {"target": "SNTEST", "line": "Halpha", "status": "detected", "file": "a.fits", "flux_index": 3.0},
                {"target": "SNTEST", "line": "Halpha", "status": "detected", "file": "b.fits", "flux_index": 4.0},
                {"target": "SNTEST", "line": "Hbeta", "status": "weak/non-detection", "file": "a.fits", "flux_index": 1.0},
            ]
        )

        summary = sp.summarize_host_line_indices(host_lines)

        self.assertEqual(int(summary.loc[0, "n_detected_host_line_instances"]), 2)
        self.assertEqual(int(summary.loc[0, "unique_detected_host_lines"]), 1)
        self.assertEqual(summary.loc[0, "detected_lines"], "Halpha")
        self.assertTrue(math.isnan(float(summary.loc[0, "balmer_decrement_Ha_Hb"])))


if __name__ == "__main__":
    unittest.main()
