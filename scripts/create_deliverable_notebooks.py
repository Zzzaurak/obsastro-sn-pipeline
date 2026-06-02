"""生成当前项目使用的精简版 notebook。

仓库里原来有较多探索 notebook。这个脚本只生成 4 个稳定入口，旧版探索
notebook 保留在 `notebooks/legacy/` 里用于追溯，不再作为主流程入口。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"


def md(source: str) -> dict:
    cleaned = textwrap.dedent(source).strip()
    return {"cell_type": "markdown", "metadata": {}, "source": cleaned.splitlines(True)}


def code(source: str) -> dict:
    cleaned = textwrap.dedent(source).strip("\n")
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": cleaned.splitlines(True),
    }


def notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python (astro_env)", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(name: str, cells: list[dict]) -> Path:
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTEBOOK_DIR / name
    path.write_text(json.dumps(notebook(cells), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


OBSERVING_NOTEBOOK = [
    md(
        """
        # 01 数据获取与观测准备

        这个 notebook 是目标获取和观测准备的稳定入口。它汇总 `README.md` 里的 TNS、Lasair、WISeREP 流程，并把远程下载设为手动开启，方便汇报时安全打开。

        科学作用：在进入光谱分析前，先整理候选体元数据、可观测窗口、找星图、公开光谱和光变曲线。
        """
    ),
    code(
        """
        from pathlib import Path
        import json
        import subprocess
        import sys

        import matplotlib.pyplot as plt
        import matplotlib.pyplot as plt
        import matplotlib.pyplot as plt
        import pandas as pd
        from IPython.display import display, Markdown, Image

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        OUTPUT_DIR = PROJECT_ROOT / "output"
        ANALYSIS_DIR = OUTPUT_DIR / "analysis_pipeline"
        CONFIG_PATH = PROJECT_ROOT / "configs" / "sn_parameter.json"
        """
    ),
    md(
        """
        ## 配置快照

        主观测流水线读取 `configs/sn_parameter.json`。TNS 和 Lasair 凭证从 `.env` 读取；`.env` 不提交到 git。
        """
    ),
    code(
        """
        config = json.loads(CONFIG_PATH.read_text())
        display(config)
        """
    ),
    md(
        """
        ## 可选：刷新远程数据

        平时写报告时保持 `RUN_REMOTE_FETCH = False`。只有需要重新拉取 TNS、找星图、Lasair 光变曲线和 WISeREP 光谱时，才把它改成 `True`。
        """
    ),
    code(
        """
        RUN_REMOTE_FETCH = False

        if RUN_REMOTE_FETCH:
            subprocess.run([sys.executable, "scripts/fetch_target_params.py"], cwd=PROJECT_ROOT, check=True)
            subprocess.run([sys.executable, "scripts/fetch_aux_data.py"], cwd=PROJECT_ROOT, check=True)
        else:
            print("跳过远程刷新，使用现有 output/ 和 data/ 产物。")
        """
    ),
    md(
        """
        ## 已有目标产物盘点

        下面统计已经生成的观测报告、找星图、光变曲线、光谱和模型输出。
        """
    ),
    code(
        """
        products = []
        for path in sorted(OUTPUT_DIR.glob("*")):
            if not path.is_dir() or path.name == "analysis_pipeline":
                continue
            products.append({
                "target": path.name,
                "reports": len(list(path.glob("sn_report_*.txt"))),
                "finder_charts": len(list(path.glob("finder_*"))),
                "lightcurve_files": len(list((path / "lightcurve").glob("*"))) if (path / "lightcurve").exists() else 0,
                "spectra_files": len(list((path / "spectrum").glob("*"))) if (path / "spectrum").exists() else 0,
                "superfit_files": len(list((path / "superfit").glob("*"))) if (path / "superfit").exists() else 0,
                "tardis_files": len(list((path / "tardis").glob("*"))) if (path / "tardis").exists() else 0,
            })
        products_df = pd.DataFrame(products)
        display(products_df)
        """
    ),
    md(
        """
        ## 光谱分析 pipeline 给出的目标状态

        运行 `02_spectral_analysis_pipeline.ipynb` 或 `scripts/build_analysis_products.py` 后，这里会显示最新的目标状态表。
        """
    ),
    code(
        """
        status_path = ANALYSIS_DIR / "target_status.csv"
        if status_path.exists():
            display(pd.read_csv(status_path))
        else:
            print(f"缺少 {status_path}。请先运行光谱分析 pipeline。")
        """
    ),
]


SPECTRAL_NOTEBOOK = [
    md(
        """
        # 02 光谱诊断与手动调参

        这个 notebook 是当前主要的数据处理和调参入口，形式接近旧版 `legacy/spectral_diagnostics.ipynb`：先集中设置参数，再读取光谱、测量科学量、逐项画图，最后提供单条谱线的局部检查图。

        批量读谱、谱线库、平滑、连续谱和质检规则主要调用 `src.spectral_pipeline`。Notebook 里保留的是方便手动调整的包装函数和可视化函数。
        """
    ),
    code(
        """
        %matplotlib inline

        from pathlib import Path
        import sys

        import matplotlib.pyplot as plt
        import pandas as pd
        from IPython.display import display
        from importlib import reload

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        sys.path.insert(0, str(PROJECT_ROOT))

        from src import spectral_pipeline as sp
        from src import spectral_notebook_tools as snt

        ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"
        """
    ),
    md(
        """
        ## 1. 配置和调参位置

        常用调参只改这个 cell：

        - `TARGETS`：空列表表示处理所有 `data/SN*/` 光谱。
        - `TARGET_METADATA`：只放你手动确认的信息；默认不读 TNS catalog，也不读 `output/`。
        - `REDSHIFT_MEASUREMENTS`：手动测得的宿主窄线红移表。多条光谱/多条谱线时，目标级红移取中位数并显示 scatter。
        - `TARGET_LINES`：为某个目标指定要测的谱线。
        - `LINE_PARAM_OVERRIDES`：按谱线、目标+谱线、目标+文件+谱线覆盖半宽、平滑窗口、连续谱边缘比例。
        - 红移检查第 4 节里只改“选取的发射线”和“手动观测波长”。
        - `CHECK_*`：控制最后的单条谱线局部检查图。
        """
    ),
    code(
        """
        TARGETS = []  # 例如 ["SN2026KID"]; 空列表表示全部目标

        TARGET_METADATA = {
            # 只填自己确认的信息；不要从 data/tns_public_objects.csv 复制。
            # "SN2026KID": {"type": "SN II", "discoverydate": "2026-04-22 00:00:00"},
        }

        REDSHIFT_MEASUREMENTS = [
            # 建议优先用宿主星系窄发射线；不要默认用 SN 宽吸收线算宇宙学红移。
            # {"target": "SN2026KID", "file": "data/SN2026kid/xxx.fits", "line": "Halpha", "kind": "host/emission", "rest_wave": 6562.8, "observed_wave": 6701.2},
        ]

        TARGET_LINES = {
            # "SN2026KID": ["Halpha", "Hbeta", "FeII5169"],
            # "SN2026JLM": ["SiII6355", "CaIIHK", "SII5640"],
        }

        LINE_HALF_WIDTH = 420.0
        LINE_SMOOTH_WINDOW = 21
        LINE_EDGE_FRACTION = 0.18
        BB_WAVE_RANGE = (4200.0, 7600.0)

        LINE_PARAM_OVERRIDES = {
            # "SiII6355": {"half_width": 500.0},
            # ("SN2026KID", "Halpha"): {"half_width": 650.0, "smooth_window": 31},
            # ("SN2026JLM", "SN2026jlm_bfosc_20260510.fits", "SiII6355"): {"edge_fraction": 0.22},
        }

        SAVE_PRODUCTS = False  # 红移确认前建议先别覆盖 output/analysis_pipeline/*.csv
        SAVE_FIGURES = True
        PRODUCT_PREFIX = ""  # 例如 "trial_" 可避免覆盖正式 CSV

        FIT_VISUAL_GAUSSIAN = True  # 只用于局部检查图的可视化，不作为强物理模型
        DIAGNOSTIC_TARGET = None  # 图形诊断网格只看某个目标；None 表示全部
        MAX_DIAGNOSTIC_PANELS = 12

        REDSHIFT_CHECK_TARGET = None
        REDSHIFT_CHECK_INDEX = 0
        REDSHIFT_HALF_WIDTH = 160.0

        CHECK_TARGET = None
        CHECK_LINE = None
        CHECK_INDEX = 0
        """
    ),
    md(
        """
        ## 2. 导入 notebook 工具函数

        大段调参辅助函数已经放到 `src/spectral_notebook_tools.py`，这里保持 notebook 简洁。你修改 `src/` 后可以重新运行这个 cell。
        """
    ),
    code(
        """
        reload(snt)
        print("Loaded src.spectral_notebook_tools")
        """
    ),
    md(
        """
        ## 3. 读取本地观测光谱

        这里只读取 `data/` 下的一维 FITS 光谱，不读 `data/tns_public_objects.csv`，也不读 `output/`。因此初始红移通常是空的，除非你在 `TARGET_METADATA` 里手动填了 `z`。
        """
    ),
    code(
        """
        spectra_raw, skipped_fits = snt.load_observed_spectra(PROJECT_ROOT, TARGET_METADATA)
        if TARGETS:
            wanted = {snt.target_key(t) for t in TARGETS}
            spectra_raw = [spec for spec in spectra_raw if spec["target"] in wanted]

        if not spectra_raw:
            raise RuntimeError("没有找到可处理的一维 FITS 光谱。请检查 data/SN*/ 下的文件。")

        summary_raw = sp.build_summary(spectra_raw)
        display(summary_raw)
        print("z_source 说明：unset=未设置；manual_config=来自 TARGET_METADATA；manual=来自后面手动测红移。")
        if not skipped_fits.empty:
            print("跳过的 FITS：")
            display(skipped_fits)
        """
    ),
    md(
        """
        ## 4. 手动测红移：局部放大关键谱线

        这一步只建议用于宿主星系窄发射线，例如 Halpha、Hbeta、[O III]。超新星自身的宽吸收线会被膨胀速度蓝移，不能直接当作宇宙学红移。

        在下面的 code cell 顶部只改 `SELECTED_EMISSION_LINE` 和 `MANUAL_OBSERVED_WAVE`。`z_guess` 会优先由手动波长推断；手动波长为空时，再用已有 `REDSHIFT_MEASUREMENTS` 或已设置的目标红移。

        如果一个目标有多条光谱，建议在 `REDSHIFT_MEASUREMENTS` 里填多条记录；后面会按目标取中位数红移，并显示 scatter。
        """
    ),
    code(
        """
        # 本 cell 通常只需要改这两项。
        SELECTED_EMISSION_LINE = "Halpha"  # 可选示例：Halpha, Hbeta, OIII5007, OIII4959, SII6716
        MANUAL_OBSERVED_WAVE = None  # 看图后填观测波长，例如 6701.2；第一次看图可先保留 None

        redshift_check_target = summary_raw.iloc[0]["target"] if REDSHIFT_CHECK_TARGET is None else REDSHIFT_CHECK_TARGET
        redshift_rest_wave = snt.line_rest_wave(SELECTED_EMISSION_LINE)
        redshift_z_guess = snt.redshift_guess_for_line(
            spectra_raw,
            redshift_check_target,
            SELECTED_EMISSION_LINE,
            redshift_rest_wave,
            manual_observed_wave=MANUAL_OBSERVED_WAVE,
            measurements=REDSHIFT_MEASUREMENTS,
        )

        redshift_items = sorted(
            [spec for spec in spectra_raw if spec["target"] == snt.target_key(redshift_check_target)],
            key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
        )
        redshift_spec = redshift_items[int(REDSHIFT_CHECK_INDEX)]
        redshift_plot, z_preview = snt.plot_redshift_zoom(
            redshift_spec,
            SELECTED_EMISSION_LINE,
            rest_wave=redshift_rest_wave,
            z_guess=redshift_z_guess,
            half_width=REDSHIFT_HALF_WIDTH,
            manual_observed_wave=MANUAL_OBSERVED_WAVE,
            mode="emission",
        )
        print(f"line = {SELECTED_EMISSION_LINE}, rest_wave = {redshift_rest_wave:.3f} A")
        print(f"plot z_guess = {redshift_z_guess:.6f}")
        print(f"auto/adopted preview z = {z_preview:.6f}")
        print(f"auto/adopted preview lambda = {redshift_plot['adopted_wave']:.3f} A")
        print(f"file = {redshift_spec['file']}")
        print("如果紫色线位置可靠，把下面这条记录复制进 REDSHIFT_MEASUREMENTS；否则先改 MANUAL_OBSERVED_WAVE 后重跑本 cell。")
        print({
            "target": redshift_spec["target"],
            "file": redshift_spec["file"],
            "line": SELECTED_EMISSION_LINE,
            "kind": "host/emission",
            "rest_wave": redshift_rest_wave,
            "observed_wave": redshift_plot["adopted_wave"],
        })
        """
    ),
    md("## 5. 汇总手动红移，并应用到光谱"),
    code(
        """
        redshift_table, redshift_summary, MANUAL_REDSHIFT_BY_TARGET = snt.redshift_table_from_measurements(REDSHIFT_MEASUREMENTS)
        display(redshift_table)
        display(redshift_summary)

        spectra = snt.apply_redshift_overrides(spectra_raw, MANUAL_REDSHIFT_BY_TARGET)
        summary = sp.build_summary(spectra)
        display(summary)
        """
    ),
    md(
        """
        ## 6. 多历元光谱序列

        下轴是观测波长，上轴是按当前目标红移换算后的静止系波长。谱线竖线画在观测波长位置，即 `rest_wave * (1 + z)`；如果目标还没有红移，就只能暂时画在静止波长位置。
        """
    ),
    code(
        """
        for target in sorted(summary["target"].unique()):
            snt.plot_spectral_sequence_dual_axis(
                target,
                spectra,
                target_lines=TARGET_LINES,
                fig_dir=FIG_DIR,
                save_figures=SAVE_FIGURES,
            )
        """
    ),
    md(
        """
        ## 7. 批量测量谱线、黑体颜色温度和宿主线

        这一步使用第 5 节得到的手动红移。如果某个目标还没有红移，速度和静止系谱线测量只是占位结果，不应写入科学结论。
        """
    ),
    code(
        """
        measure_kwargs = dict(
            line_half_width=LINE_HALF_WIDTH,
            line_smooth_window=LINE_SMOOTH_WINDOW,
            line_edge_fraction=LINE_EDGE_FRACTION,
            line_param_overrides=LINE_PARAM_OVERRIDES,
            fit_visual_gaussian=FIT_VISUAL_GAUSSIAN,
        )

        summary, line_df, line_qc, bb_df, host_lines, host_summary, target_status = snt.measure_all_features(
            spectra,
            target_lines=TARGET_LINES,
            bb_wave_range=BB_WAVE_RANGE,
            **measure_kwargs,
        )

        display(target_status)
        display(line_qc[["target", "file", "line", "velocity_kms", "pEW_A", "FWHM_A", "depth", "qc_flag", "qc_note"]].head(20))
        """
    ),
    md("## 8. 谱线局部诊断图：中心、吸收谷、拟合和 pEW 区域"),
    code(
        """
        snt.plot_line_diagnostics_grid(
            spectra,
            line_qc,
            target=DIAGNOSTIC_TARGET,
            max_panels=MAX_DIAGNOSTIC_PANELS,
            fig_dir=FIG_DIR,
            save_figures=SAVE_FIGURES,
            **measure_kwargs,
        )
        """
    ),
    md("## 9. 黑体连续谱拟合图"),
    code(
        """
        snt.plot_blackbody_fit_grid(
            spectra,
            target=DIAGNOSTIC_TARGET,
            wave_range=BB_WAVE_RANGE,
            fig_dir=FIG_DIR,
            save_figures=SAVE_FIGURES,
        )
        """
    ),
    md("## 10. 科学量图：谱线速度"),
    code(
        """
        snt.plot_quantity_by_target(line_qc, "velocity_kms", "Velocity (km/s)", "Line velocity evolution", "line_velocity_evolution.png", FIG_DIR, save_figures=SAVE_FIGURES)
        """
    ),
    md("## 11. 科学量图：pseudo-equivalent width"),
    code(
        """
        snt.plot_quantity_by_target(line_qc, "pEW_A", "pEW (Angstrom)", "Pseudo-equivalent width evolution", "pew_evolution.png", FIG_DIR, save_figures=SAVE_FIGURES)
        """
    ),
    md("## 12. 科学量图：FWHM"),
    code(
        """
        snt.plot_quantity_by_target(line_qc, "FWHM_A", "FWHM (Angstrom)", "Line FWHM evolution", "fwhm_evolution.png", FIG_DIR, save_figures=SAVE_FIGURES)
        """
    ),
    md("## 13. 科学量图：线深"),
    code(
        """
        snt.plot_quantity_by_target(line_qc, "depth", "Line depth", "Absorption-line depth evolution", "line_depth_evolution.png", FIG_DIR, save_figures=SAVE_FIGURES)
        """
    ),
    md("## 14. 科学量图：连续谱黑体颜色温度"),
    code(
        """
        ok_bb = bb_df[bb_df["status"].eq("ok")].copy()
        if ok_bb.empty:
            print("没有成功的黑体颜色温度拟合。")
        else:
            plt.figure(figsize=(10, 5))
            for target, group in ok_bb.groupby("target"):
                x = group["phase_days"] if group["phase_days"].notna().any() else pd.to_datetime(group["date_obs"])
                plt.errorbar(x, group["T_bb_K"], yerr=group["T_err_K"], marker="o", capsize=2, lw=1.2, label=target)
            plt.ylabel("Blackbody color temperature (K)")
            plt.xlabel("Days since discovery / obs date")
            plt.title("Continuum blackbody color-temperature estimate")
            plt.grid(alpha=0.25)
            plt.legend(fontsize=8)
            snt.save_figure(plt.gcf(), FIG_DIR, "blackbody_temperature.png", enabled=SAVE_FIGURES)
            plt.show()
        display(bb_df)
        """
    ),
    md("## 15. 科学量图：宿主/环境窄线指标"),
    code(
        """
        snt.plot_host_line_grid(host_lines, target=DIAGNOSTIC_TARGET, fig_dir=FIG_DIR, save_figures=SAVE_FIGURES)
        display(host_summary)
        display(host_lines)
        """
    ),
    md(
        """
        ## 16. 单条谱线局部检查图

        改 `CHECK_TARGET`、`CHECK_LINE`、`CHECK_INDEX`，或回到配置区改 `LINE_PARAM_OVERRIDES` 后重新运行。

        图中：

        - 灰色：局部原始光谱。
        - 黑色：平滑后的真实观测谱线轮廓。
        - 橙色：局部线性连续谱。
        - 紫色：为了可视化而拟合的高斯吸收轮廓，不作为强物理模型。
        - 红虚线：谱线静止波长；绿虚线：自动选择的吸收谷。
        """
    ),
    code(
        """
        if CHECK_TARGET is None:
            CHECK_TARGET = summary.iloc[0]["target"]
        if CHECK_LINE is None:
            first_spec = next(spec for spec in spectra if spec["target"] == snt.target_key(CHECK_TARGET))
            CHECK_LINE = snt.line_keys_for(first_spec, TARGET_LINES)[0]

        check_result, _ = snt.plot_line_check(
            spectra,
            target=CHECK_TARGET,
            line_key=CHECK_LINE,
            spectrum_index=CHECK_INDEX,
            fig_dir=FIG_DIR,
            save_figures=SAVE_FIGURES,
            **measure_kwargs,
        )
        display(check_result)
        """
    ),
    md("## 17. 保存 CSV 汇总"),
    code(
        """
        def output_path(name):
            ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
            return ANALYSIS_DIR / f"{PRODUCT_PREFIX}{name}"


        if SAVE_PRODUCTS:
            outputs = {
                "spectra_summary": output_path("spectra_summary.csv"),
                "line_diagnostics_raw": output_path("line_diagnostics_raw.csv"),
                "line_diagnostics_qc": output_path("line_diagnostics_qc.csv"),
                "blackbody_temperature": output_path("blackbody_temperature.csv"),
                "host_environment_lines": output_path("host_environment_lines.csv"),
                "host_environment_summary": output_path("host_environment_summary.csv"),
                "target_status": output_path("target_status.csv"),
                "manual_redshift_measurements": output_path("manual_redshift_measurements.csv"),
                "manual_redshift_summary": output_path("manual_redshift_summary.csv"),
                "skipped_fits": output_path("skipped_fits.csv"),
            }
            summary.to_csv(outputs["spectra_summary"], index=False)
            line_df.to_csv(outputs["line_diagnostics_raw"], index=False)
            line_qc.to_csv(outputs["line_diagnostics_qc"], index=False)
            bb_df.to_csv(outputs["blackbody_temperature"], index=False)
            host_lines.to_csv(outputs["host_environment_lines"], index=False)
            host_summary.to_csv(outputs["host_environment_summary"], index=False)
            target_status.to_csv(outputs["target_status"], index=False)
            redshift_table.to_csv(outputs["manual_redshift_measurements"], index=False)
            redshift_summary.to_csv(outputs["manual_redshift_summary"], index=False)
            skipped_fits.to_csv(outputs["skipped_fits"], index=False)
            for label, path in outputs.items():
                print(f"{label}: {path}")
        else:
            print("SAVE_PRODUCTS=False，未写出 CSV。")
        """
    ),
    md(
        """
        ## 18. 下一步人工确认

        正式报告里建议只引用：

        1. 由宿主窄线手动测得并写入 `REDSHIFT_MEASUREMENTS` 的红移；
        2. `qc_flag=adopt` 的自动测量；
        3. 或者经过上面局部检查图确认后的 `qc_flag=check` 测量。

        如果某条线的吸收谷选错，优先在配置区用 `LINE_PARAM_OVERRIDES` 调整 `half_width`、`smooth_window`、`edge_fraction`，然后重新运行批量测量之后的 cells。
        """
    ),
]


TARDIS_NOTEBOOK = [
    md(
        """
        # 03 可选 TARDIS 建模

        这个 notebook 的定位刻意收窄。文献调研说明，稀疏光谱样本不适合过度建模；这里的 TARDIS 主要用于在分类、相位和速度检查之后，辅助谱线识别和定性比较谱形。

        只有当目标有可用观测光谱，并且 `output/<target>/tardis/` 下已经有 TARDIS 输出时，才需要在 `tardis` 环境中运行这个 notebook。
        """
    ),
    code(
        """
        from pathlib import Path
        import numpy as np
        import matplotlib.pyplot as plt
        from IPython.display import display

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        TARGET = "SN2026jlm"
        OUTPUT_DIR = PROJECT_ROOT / "output" / TARGET
        SPECTRUM_DIR = OUTPUT_DIR / "spectrum"
        TARDIS_DIR = OUTPUT_DIR / "tardis"
        """
    ),
    md("## 读取观测光谱和模拟光谱"),
    code(
        """
        observed_files = sorted(SPECTRUM_DIR.glob("*.dat"))
        simulated_files = sorted(TARDIS_DIR.glob("tardis_spectrum_*.dat"))

        if not observed_files:
            raise FileNotFoundError(f"No observed *.dat spectra in {SPECTRUM_DIR}")
        if not simulated_files:
            raise FileNotFoundError(f"No TARDIS spectra in {TARDIS_DIR}")

        observed_path = observed_files[0]
        simulated_path = simulated_files[0]
        obs = np.loadtxt(observed_path)
        sim = np.loadtxt(simulated_path)

        wave_obs, flux_obs = obs[:, 0], obs[:, 1]
        wave_sim, flux_sim = sim[:, 0], sim[:, 1]

        print(f"观测光谱: {observed_path}")
        print(f"模拟光谱: {simulated_path}")
        """
    ),
    md("## 归一化并比较谱形"),
    code(
        """
        def normalize(flux):
            finite = np.isfinite(flux)
            scale = np.nanpercentile(np.abs(flux[finite]), 95) if finite.any() else 1.0
            return flux / scale if scale else flux

        plt.figure(figsize=(10, 5))
        plt.plot(wave_obs, normalize(flux_obs), lw=0.9, label="Observed WISeREP/BFOSC spectrum")
        plt.plot(wave_sim, normalize(flux_sim), lw=0.9, label="TARDIS synthetic spectrum")
        plt.xlim(3500, 9000)
        plt.xlabel("Rest wavelength (Angstrom)")
        plt.ylabel("Normalized flux / luminosity density")
        plt.title(f"{TARGET}: qualitative TARDIS comparison")
        plt.grid(alpha=0.25)
        plt.legend()
        plt.show()
        """
    ),
    md(
        """
        ## 解释边界

        这个比较只能用来讨论模型是否大体匹配谱线位置或连续谱形状。若没有进一步建模和不确定度分析，不应从一条稀疏光谱中给出强的抛射物质量、爆炸能量或丰度约束。
        """
    ),
]


REPORT_NOTEBOOK = [
    md(
        """
        # 04 项目报告 Notebook

        这个 notebook 是精简版 P2Rp2 风格报告，也可作为最终展示图表的来源。结构对应课程要求：科学问题、数据、处理与分析、建模与解释、结论和分工说明。
        """
    ),
    code(
        """
        from pathlib import Path
        import pandas as pd
        from IPython.display import display, Image, Markdown

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"

        target_status = pd.read_csv(ANALYSIS_DIR / "target_status.csv")
        line_qc = pd.read_csv(ANALYSIS_DIR / "line_diagnostics_qc.csv")
        host_summary = pd.read_csv(ANALYSIS_DIR / "host_environment_summary.csv")
        bb = pd.read_csv(ANALYSIS_DIR / "blackbody_temperature.csv")
        """
    ),
    md(
        """
        ## 科学问题

        对一组新观测的超新星目标，如果每个目标只有 1-4 条光学光谱，我们能可靠提取哪些光谱信息？比较稳妥的目标是：确认类型/子型，估计光谱相位，在可靠时测量关键谱线速度和 pEW/FWHM，识别宿主污染或窄宿主线，并把每个目标放到公开超新星光谱样本的背景下比较。
        """
    ),
    md(
        """
        ## 数据

        本项目整合 TNS 元数据和找星图、可用时的 Lasair/ZTF 光变曲线、WISeREP 公开光谱，以及 `data/SN*/` 下的本地 BFOSC 一维光谱。下面的分析产物由 `scripts/build_analysis_products.py` 生成。
        """
    ),
    code("display(target_status)"),
    md(
        """
        ## 处理与分析

        精简 pipeline 读取已定标的一维 FITS 光谱；在有 TNS 红移时进行静止系修正；按目标类型测量合适的稀疏光谱诊断量；并给出保守质检标记。标记为 `check` 的自动测量保留在表中以便追溯，但人工看图前不应作为最终数值引用。
        """
    ),
    code(
        """
        adopted = line_qc[line_qc["qc_flag"].eq("adopt")].copy()
        display(adopted[["target", "date_obs", "phase_days", "type", "line", "velocity_kms", "pEW_A", "FWHM_A"]])
        """
    ),
    md("## 关键图表"),
    md(
        """
        这些图也直接以 Markdown 链接嵌入，因此即使不执行代码单元，报告仍然可读。

        ### 目标状态

        ![目标状态](../output/analysis_pipeline/figures/target_status_table.png)

        ### 谱线速度演化

        ![谱线速度演化](../output/analysis_pipeline/figures/line_velocity_evolution.png)

        ### pEW 演化

        ![pEW 演化](../output/analysis_pipeline/figures/pew_evolution.png)

        ### 连续谱颜色温度估计

        ![黑体温度](../output/analysis_pipeline/figures/blackbody_temperature.png)

        ### 宿主/环境谱线探测

        ![宿主线探测](../output/analysis_pipeline/figures/host_line_detections.png)
        """
    ),
    code(
        """
        for fig in [
            "target_status_table.png",
            "line_velocity_evolution.png",
            "pew_evolution.png",
            "blackbody_temperature.png",
            "host_line_detections.png",
        ]:
            path = FIG_DIR / fig
            display(Markdown(f"### {fig}"))
            display(Image(filename=str(path)))
        """
    ),
    md(
        """
        ## 建模与解释

        文献调研支持保守解释。Ia 型目标应主要用 Si II/Ca II 速度和 pEW，与 BSNIP/CSP/Branch 类样本比较。II 型目标应重点讨论 Fe II 和 Balmer 速度，并放到 Gutiérrez/Tsinghua 等样本背景下。去包层候选体应先核查 He/O/Ca 谱线识别，再讨论子型。TARDIS 可以辅助说明谱线识别或大体谱形，但不作为前身星或爆炸参数结论的主要证据。
        """
    ),
    code("display(host_summary)"),
    md(
        """
        ## 当前结论

        - `SN2026FVX` 和 `SN2026JLM` 具有 Ia 型稀疏光谱序列特征；Si II 6355 是第一版速度测量中最干净的谱线。
        - `SN2026KID` 是当前最明确的 II 型案例；最终引用 Fe II/H 线和宿主线指标前仍需人工检查。
        - `SN2026KIE` 应先按去包层候选体处理；子型需要结合 He/O/Ca 诊断和模板拟合进一步确认。
        - `SN2026LMP` 在当前元数据中仍未分类；确认红移和类型前，不应进入强科学结论。

        这些结果已经可以作为第一版展示产物，但最终报告中的数值应基于 `adopt` 测量和人工视觉检查。
        """
    ),
    md(
        """
        ## 分工页/报告占位

        提交前请把 `TBD by group` 替换成小组成员姓名。一个清晰分工可以是：

        | 分工 | 负责人 | 贡献 |
        |---|---|---|
        | 观测准备 | TBD by group | TNS 元数据、找星图、观测窗口准备、公开数据盘点。 |
        | 光谱处理 | TBD by group | BFOSC/FITS 检查、光谱抽取核查、波长和红移合理性检查。 |
        | 光谱诊断 | TBD by group | 谱线速度、pEW/FWHM、黑体颜色温度 proxy、宿主线标记。 |
        | 解释与展示 | TBD by group | 文献比较、报告 notebook、TARDIS 定性建模、最终英文 slides。 |
        """
    ),
]


def main() -> None:
    written = [
        write_notebook("01_data_collection_and_observing.ipynb", OBSERVING_NOTEBOOK),
        write_notebook("02_spectral_analysis_pipeline.ipynb", SPECTRAL_NOTEBOOK),
        write_notebook("03_tardis_modeling_optional.ipynb", TARDIS_NOTEBOOK),
        write_notebook("04_project_report.ipynb", REPORT_NOTEBOOK),
    ]
    print("Wrote notebooks:")
    for path in written:
        print(f"- {path}")


if __name__ == "__main__":
    main()
