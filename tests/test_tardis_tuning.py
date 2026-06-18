from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts import run_tardis_tuning as runner
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

    def test_build_config_can_use_literature_photospheric_plasma_preset(self) -> None:
        candidate = tt.TardisCandidate(
            target="SN2026FVX",
            candidate_id="SN2026FVX_c000",
            sn_family="Ia",
            log_lsun=9.4,
            time_explosion_days=20.0,
            v_start_kms=5000.0,
            v_stop_kms=15000.0,
            density_profile="branch85_w7",
            abundance_preset="ia_standard",
            physics_preset="literature_photospheric",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            config = tt.build_tardis_config(candidate, project_root=root, packet_scale="quick")

        self.assertEqual(config["plasma"]["ionization"], "nebular")
        self.assertEqual(config["plasma"]["excitation"], "dilute-lte")
        self.assertEqual(config["plasma"]["line_interaction_type"], "macroatom")

    def test_generate_candidates_can_include_literature_physics_variant(self) -> None:
        seed = tt.TargetSeed(
            target="SN2026FVX",
            sn_type="SN Ia",
            sn_family="Ia",
            z=0.02,
            spectrum_file="data/SN2026FVX/spec.fits",
            log_lsun=9.4,
            time_explosion_days=24.0,
            v_start_kms=5000.0,
            v_stop_kms=16000.0,
        )

        candidates = tt.generate_candidates(
            seed,
            luminosity_offsets=[0.0],
            epoch_offsets=[0.0],
            velocity_scales=[1.0],
            abundance_presets=["ia_standard"],
            density_profiles=["branch85_w7"],
            physics_presets=["current_lte", "literature_photospheric"],
        )

        self.assertEqual([candidate.physics_preset for candidate in candidates], ["current_lte", "literature_photospheric"])

    def test_model_resource_candidate_builds_csvy_config(self) -> None:
        candidate = tt.TardisCandidate(
            target="SN2026FVX",
            candidate_id="SN2026FVX_c000",
            sn_family="Ia",
            log_lsun=9.4,
            time_explosion_days=24.0,
            v_start_kms=5000.0,
            v_stop_kms=16000.0,
            density_profile="csvy_model",
            abundance_preset="ia_ddt_n100_comp",
            model_resource="ia/ddt_n100_comp.csvy",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "tardis_models" / "ia").mkdir(parents=True)
            csvy = root / "data" / "tardis_models" / "ia" / "ddt_n100_comp.csvy"
            csvy.write_text("velocity,density,C,O\n9000,5e-10,0.1,0.9\n", encoding="utf-8")
            config = tt.build_tardis_config(candidate, project_root=root, packet_scale="quick")

        self.assertEqual(config["csvy_model"], str(csvy.resolve()))
        self.assertNotIn("model", config)
        self.assertEqual(config["plasma"]["ionization"], "nebular")
        self.assertEqual(config["plasma"]["excitation"], "dilute-lte")
        self.assertEqual(config["plasma"]["line_interaction_type"], "scatter")

    def test_generate_candidates_can_include_ia_model_resources(self) -> None:
        seed = tt.TargetSeed(
            target="SN2026FVX",
            sn_type="SN Ia",
            sn_family="Ia",
            z=0.02,
            spectrum_file="data/SN2026FVX/spec.fits",
            log_lsun=9.4,
            time_explosion_days=24.0,
            v_start_kms=5000.0,
            v_stop_kms=16000.0,
        )

        candidates = tt.generate_candidates(
            seed,
            luminosity_offsets=[0.0],
            epoch_offsets=[0.0],
            velocity_scales=[1.0],
            abundance_presets=["ia_standard"],
            density_profiles=["branch85_w7"],
            model_resources=["ia/ddt_n100_comp.csvy", "ia/merger_2012_comp.csvy"],
        )

        self.assertEqual(len(candidates), 3)
        self.assertIsNone(candidates[0].model_resource)
        self.assertEqual(candidates[1].model_resource, "ia/ddt_n100_comp.csvy")
        self.assertEqual(candidates[1].candidate_id, "SN2026FVX_m000")
        self.assertEqual(candidates[1].density_profile, "csvy_model")
        self.assertEqual(candidates[2].abundance_preset, "ia/merger_2012_comp.csvy")

    def test_generate_candidates_can_run_model_resources_without_analytic_grid(self) -> None:
        seed = tt.TargetSeed(
            target="SN2026FVX",
            sn_type="SN Ia",
            sn_family="Ia",
            z=0.02,
            spectrum_file="data/SN2026FVX/spec.fits",
            log_lsun=9.4,
            time_explosion_days=24.0,
            v_start_kms=5000.0,
            v_stop_kms=16000.0,
        )

        candidates = tt.generate_candidates(
            seed,
            luminosity_offsets=[-0.2, 0.0],
            epoch_offsets=[0.0, 4.0],
            velocity_scales=[1.0],
            abundance_presets=[],
            density_profiles=[],
            model_resources=["ia/ddt_n100_comp.csvy"],
        )

        self.assertEqual(len(candidates), 4)
        self.assertTrue(all(candidate.model_resource == "ia/ddt_n100_comp.csvy" for candidate in candidates))
        self.assertEqual([candidate.candidate_id for candidate in candidates], ["SN2026FVX_m000", "SN2026FVX_m001", "SN2026FVX_m002", "SN2026FVX_m003"])
        self.assertEqual([candidate.log_lsun for candidate in candidates], [9.2, 9.2, 9.4, 9.4])
        self.assertEqual([candidate.time_explosion_days for candidate in candidates], [24.0, 28.0, 24.0, 28.0])

    def test_available_model_resources_returns_relative_ia_csvy_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "tardis_models" / "ia").mkdir(parents=True)
            (root / "data" / "tardis_models" / "ia" / "b.csvy").write_text("b", encoding="utf-8")
            (root / "data" / "tardis_models" / "ia" / "a.csvy").write_text("a", encoding="utf-8")

            self.assertEqual(tt.available_model_resources(root, "Ia"), ["ia/a.csvy", "ia/b.csvy"])
            self.assertEqual(tt.available_model_resources(root, "II"), [])

    def test_extract_tardis_arrays_skips_nan_integrated_spectrum(self) -> None:
        class Quantity:
            def __init__(self, values: list[float]) -> None:
                self.value = np.asarray(values, dtype=float)

        class Spectrum:
            def __init__(self, wave: list[float], flux: list[float]) -> None:
                self.wavelength = Quantity(wave)
                self.luminosity_density_lambda = Quantity(flux)

        class Solver:
            spectrum_integrated = Spectrum([np.nan], [np.nan])
            spectrum_virtual_packets = Spectrum([7000.0, 5000.0], [2.0, 1.0])
            spectrum_real_packets = Spectrum([6000.0], [3.0])

        class Simulation:
            spectrum_solver = Solver()

        wave, flux = runner.extract_tardis_arrays(Simulation())

        np.testing.assert_allclose(wave, [5000.0, 7000.0])
        np.testing.assert_allclose(flux, [1.0, 2.0])

    def test_tuning_target_dir_uses_run_label_suffix(self) -> None:
        root = Path("/project")

        self.assertEqual(runner.tuning_target_dir(root, "SN2026FVX", ""), Path("/project/output/tardis_tuning/SN2026FVX"))
        self.assertEqual(
            runner.tuning_target_dir(root, "SN2026FVX", "csvy Ia pass"),
            Path("/project/output/tardis_tuning/SN2026FVX__csvy_Ia_pass"),
        )


if __name__ == "__main__":
    unittest.main()
