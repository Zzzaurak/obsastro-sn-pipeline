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


def notebook(cells: list[dict], *, display_name: str = "Python (astro_env)", python_version: str | None = None) -> dict:
    language_info = {"name": "python", "pygments_lexer": "ipython3"}
    if python_version:
        language_info["version"] = python_version
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": display_name, "language": "python", "name": "python3"},
            "language_info": language_info,
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(
    name: str,
    cells: list[dict],
    *,
    display_name: str = "Python (astro_env)",
    python_version: str | None = None,
) -> Path:
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTEBOOK_DIR / name
    path.write_text(
        json.dumps(notebook(cells, display_name=display_name, python_version=python_version), ensure_ascii=False, indent=1)
        + "\n",
        encoding="utf-8",
    )
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
        from importlib import reload

        import matplotlib.pyplot as plt
        import pandas as pd
        from IPython.display import display, Markdown, Image

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        sys.path.insert(0, str(PROJECT_ROOT))

        from src import spectral_pipeline as sp
        from src import spectral_notebook_tools as snt

        OUTPUT_DIR = PROJECT_ROOT / "output"
        ANALYSIS_DIR = OUTPUT_DIR / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"
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
        ## 可选：重新运行 Superfit

        默认保持 `RUN_SUPERFIT = False`，避免打开 notebook 就批量重跑。需要刷新模板拟合时，先在 `SUPERFIT_TARGETS` 里指定目标；空列表表示对所有 `data/SN*/SN*.txt` 重跑。若有可靠宿主红移，可填入 `SUPERFIT_Z_BY_TARGET`，否则 Superfit 会在粗红移网格中搜索。
        """
    ),
    code(
        """
        RUN_SUPERFIT = False
        SUPERFIT_TARGETS = []  # 例如 ["SN2026KID"]; 空列表表示全部本地 txt 光谱
        SUPERFIT_Z_BY_TARGET = {
            # "SN2026KID": 0.0014,
        }

        if RUN_SUPERFIT:
            superfit_run_table = snt.run_superfit_batch(
                PROJECT_ROOT,
                targets=SUPERFIT_TARGETS,
                z_by_target=SUPERFIT_Z_BY_TARGET,
                z_range=(0.0, 0.08),
                z_step=0.005,
                resolution=30,
                how_many_plots=5,
            )
            display(superfit_run_table)
        else:
            print("未重跑 Superfit；使用已有 data/SN*/superfit/*.csv。")
        """
    ),
    md(
        """
        ## 可选：重新运行 DASH

        默认保持 `RUN_DASH = False`。DASH 会读取 `data/SN*/SN*.txt`，并把匹配结果写回 `notebooks/DASH_matches.txt`。如果 `DASH_KNOWN_Z = True`，需要为所有待跑目标在 `DASH_Z_BY_TARGET` 填可靠红移；否则 DASH 会自己估计红移。
        """
    ),
    code(
        """
        RUN_DASH = False
        DASH_TARGETS = []  # 例如 ["SN2026JLM"]; 空列表表示全部本地 txt 光谱
        DASH_KNOWN_Z = False
        DASH_Z_BY_TARGET = {
            # "SN2026JLM": 0.0155,
        }

        if RUN_DASH:
            dash_run_table = snt.run_dash_batch(
                PROJECT_ROOT,
                targets=DASH_TARGETS,
                z_by_target=DASH_Z_BY_TARGET,
                known_z=DASH_KNOWN_Z,
                output_path=PROJECT_ROOT / "notebooks" / "DASH_matches.txt",
                top_n=5,
            )
            display(dash_run_table)
        else:
            print("未重跑 DASH；使用已有 notebooks/DASH_matches.txt。")
        """
    ),
    md(
        """
        ## 已有模板工具产物：Superfit/DASH 状态

        这里盘点 `data/SN*/superfit/*.csv` 和 `notebooks/DASH_matches.txt` 里已有或刚重跑出的模板分类结果，作为后面经验粗分类的交叉参考。
        """
    ),
    code(
        """
        superfit_summary = snt.summarize_existing_superfit_results(PROJECT_ROOT)
        if superfit_summary.empty:
            print("没有发现已有 Superfit CSV。")
        else:
            display(superfit_summary)

        template_spectrum_table, template_target_table = snt.summarize_local_template_classifications(PROJECT_ROOT)
        if template_target_table.empty:
            print("没有可汇总的本地模板分类结果。")
        else:
            display(template_target_table)

        dash_log = PROJECT_ROOT / "notebooks" / "DASH_matches.txt"
        if dash_log.exists():
            print(f"已有 DASH 文本记录：{dash_log}")
        else:
            print("没有发现 DASH_matches.txt。")
        """
    ),
    md(
        """
        ## 全自动本地光谱粗分类

        这一步只读取 `data/` 下自己的 FITS 光谱，不读 `data/tns_public_objects.csv`，也不读 TNS 类型。方法是轻量级经验分类：先用宿主窄发射线粗估红移，再测 Si、H、He、O、Ca、Fe 等关键谱线的吸收特征，给出 Ia/II/IIb/Ib/Ic 的初筛类型、粗红移、代表速度和黑体颜色温度。

        这不是 DASH/SNID/Superfit 模板匹配，只用于观测准备和 02 notebook 自动选线；最终报告中的类型仍应结合人工检查或模板工具确认。
        """
    ),
    code(
        """
        reload(snt)

        spectra_local, skipped_local = snt.load_observed_spectra(PROJECT_ROOT, target_metadata={})
        if not spectra_local:
            print("没有找到可处理的一维 FITS 光谱。")
        else:
            rough_spectrum_table, rough_target_table, rough_feature_table = snt.rough_classify_spectra(spectra_local)
            template_spectrum_table, template_target_table = snt.summarize_local_template_classifications(PROJECT_ROOT)
            classification_target_table = snt.combine_template_and_rough_classifications(template_target_table, rough_target_table)

            display(classification_target_table)
            display(rough_target_table)
            display(rough_spectrum_table[[
                "target", "file", "date_obs", "rough_type", "rough_type_confidence",
                "rough_z", "rough_z_source", "rough_velocity_line", "rough_velocity_kms", "T_bb_K",
            ]])
            snt.plot_rough_classification_summary(classification_target_table, FIG_DIR, save_figures=True)

            ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
            classification_target_table.to_csv(ANALYSIS_DIR / "local_classification_targets.csv", index=False)
            template_spectrum_table.to_csv(ANALYSIS_DIR / "local_template_classification_spectra.csv", index=False)
            template_target_table.to_csv(ANALYSIS_DIR / "local_template_classification_targets.csv", index=False)
            rough_target_table.to_csv(ANALYSIS_DIR / "rough_classification_targets.csv", index=False)
            rough_spectrum_table.to_csv(ANALYSIS_DIR / "rough_classification_spectra.csv", index=False)
            rough_feature_table.to_csv(ANALYSIS_DIR / "rough_classification_line_features.csv", index=False)
            skipped_local.to_csv(ANALYSIS_DIR / "rough_classification_skipped_fits.csv", index=False)
            print(f"Saved rough-classification products to {ANALYSIS_DIR}")
        """
    ),
    md(
        """
        ## 光谱分析 pipeline 给出的目标状态

        运行 `02_spectral_analysis_pipeline.ipynb` 后，单目标调参输出会带目标名前缀；运行 `scripts/build_analysis_products.py` 后可能还有旧的全量无前缀表。这里按目标合并读取最新可用版本。
        """
    ),
    code(
        """
        status_table = snt.read_combined_analysis_products(ANALYSIS_DIR, "target_status.csv")
        status_products = snt.find_analysis_products(ANALYSIS_DIR, "target_status.csv")

        if status_table.empty:
            print(f"缺少 target_status.csv 或 *_target_status.csv。请先运行光谱分析 pipeline。")
        else:
            print("读取到的目标状态产物（新到旧）：")
            for path in status_products[:8]:
                print(f"- {path.name}")
            display(status_table)
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
        import numpy as np
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
        - `TARGET_LINES`：为某个目标手动覆盖要测的谱线；留空时按 SN 类型自动选择关键谱线。
        - `AUTO_CLASSIFY_TYPES`：没有手动类型时，使用本地光谱经验粗分类结果给 02 自动选线。
        - `LINE_PARAM_OVERRIDES`：按谱线、目标+谱线、目标+文件+谱线覆盖半宽、平滑窗口、连续谱边缘比例。
        - `OUTPUT_TAG`：空字符串时自动使用当前目标名；`SAVE_PRODUCTS=True`/`SAVE_FIGURES=True` 只会覆盖同一 tag 的输出，不会覆盖其他目标的输出。
        - 红移检查第 4 节里只改“选取的发射线”、“手动观测波长”和 `REDSHIFT_SPECTRUM_INDEX`。
        - `CHECK_*`：控制最后的单条谱线局部检查图。

        方法说明：本节只设置参数，不读取数据，也不运行任何拟合。
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
            # 留空时按 spec["type"] 自动选择；这里仅用于手动覆盖。
            # "SN2026KID": ["Halpha", "Hbeta", "FeII5169"],
            # "SN2026JLM": ["SiII6355", "CaIIHK", "SII5640"],
        }

        AUTO_CLASSIFY_TYPES = True  # 没有手动 type 时，用本地光谱经验粗分类来自动选线
        AUTO_APPLY_ROUGH_Z = False  # 红移仍建议用第 4-5 节手动宿主窄线测量；不默认采用粗红移
        AUTO_OVERWRITE_MANUAL_TYPE = False

        LINE_HALF_WIDTH = 420.0
        LINE_SMOOTH_WINDOW = 21
        LINE_EDGE_FRACTION = 0.18
        BB_WAVE_RANGE = (4200.0, 7600.0)
        RAW_REFERENCE_LINES = ["CaIIHK", "Hgamma", "Hbeta", "FeII5169", "SII5640", "HeI5876", "SiII6355", "Halpha", "OI7774", "CaIINIR"]

        LINE_PARAM_OVERRIDES = {
            # "SiII6355": {"half_width": 500.0},
            # ("SN2026KID", "Halpha"): {"half_width": 650.0, "smooth_window": 31},
            # ("SN2026JLM", "SN2026jlm_bfosc_20260510.fits", "SiII6355"): {"edge_fraction": 0.22},
        }

        SAVE_PRODUCTS = False  # 写出 CSV；同一 RUN_TAG 会覆盖，自动目标 tag 不会覆盖别的目标
        SAVE_FIGURES = False  # 写出 PNG；同一 RUN_TAG 会覆盖，自动目标 tag 不会覆盖别的目标
        PRODUCT_PREFIX = ""  # 例如 "trial" 可在目标 tag 前再加一层前缀
        OUTPUT_TAG = ""  # 空字符串表示自动用当前目标名，例如 SN2026KID；也可手动填 "trial_SN2026KID"

        DIAGNOSTIC_TARGET = None  # 图形诊断网格只看某个目标；None 表示全部
        MAX_DIAGNOSTIC_PANELS = 12

        REDSHIFT_CHECK_TARGET = None
        REDSHIFT_HALF_WIDTH = 160.0

        CHECK_TARGET = None
        CHECK_LINE = None
        """
    ),
    md(
        """
        ### 按 SN 类型自动选择的关键科学谱线

        这些谱线来自当前 `src.spectral_pipeline` 的默认规则，并参考了文献调研中 SNID/Superfit/DASH 分类、Type II 光谱多样性、Ia 大样本和去包层超新星数据集的常用诊断：

        | 类型 | 自动测量的关键谱线 | 用途 |
        |---|---|---|
        | Ia | Si II 6355/5972, S II 5640, Ca II H&K/NIR, C II 6580 | 分类确认、Si II 速度与 pEW、正常/高速 Ia 和碳线检查 |
        | II | H alpha/beta/gamma, Fe II 5169/5018/4924, Sc II 5527, Ca II H&K/NIR | 氢线与 Fe II 速度、平台期谱线演化、Type II 文献比较 |
        | IIn | H alpha/beta/gamma, Fe II 5169, Ca II H&K | 窄/宽氢发射和相互作用迹象的初筛 |
        | IIb | H alpha/beta, He I 5876/6678/7065, Fe II 5169, Ca II H&K/NIR | 氢到氦的转变、IIb/Ib 子型判断 |
        | Ib | He I 5876/6678/7065, Ca II H&K/NIR, O I 7774 | 氦线识别、Ib/Ic 区分 |
        | Ic/Ic-BL | O I 7774, Ca II H&K/NIR, Fe II 5169, C II 6580 | 无氢氦谱线、O/Ca/Fe 速度与宽线候选检查 |

        `TARGET_LINES` 留空时会按这些规则自动选择；若某个目标需要更保守或更窄的线表，可以在配置区手动覆盖。
        """
    ),
    md(
        """
        ## 2. 导入 notebook 工具函数

        大段调参辅助函数已经放到 `src/spectral_notebook_tools.py`，这里保持 notebook 简洁。你修改 `src/` 后可以重新运行这个 cell。

        方法说明：本节只导入/重载函数，不运行任何拟合。
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

        方法说明：本步不做物理拟合，也不做红移校正；图中光谱只用 Savitzky-Golay 作轻微预平滑以便显示。Savitzky-Golay 的含义是在移动窗口内做低阶多项式拟合，并用该窗口中心的拟合值替代原始值。竖虚线是 `RAW_REFERENCE_LINES` 的未校准静止波长参考线，直接画在观测波长轴上，没有乘 `(1+z)`，只用于找线。
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

        print("未处理的多历元光谱序列图：只用原始观测波长和本地 FITS flux，不应用红移、类型或自动选线。")
        for target in sorted(summary_raw["target"].unique()):
            raw_sequence_fig = snt.plot_raw_spectral_sequence(
                target,
                spectra_raw,
                fig_dir=FIG_DIR,
                save_figures=SAVE_FIGURES,
                reference_lines=RAW_REFERENCE_LINES,
            )
            snt.show_figure(raw_sequence_fig)
        """
    ),
    md(
        """
        ## 4. 手动测红移：局部放大关键谱线

        这一步只建议用于宿主星系窄发射线，例如 Halpha、Hbeta、[O III]。超新星自身的宽吸收线会被膨胀速度蓝移，不能直接当作宇宙学红移。

        在下面的 code cell 顶部只改 `SELECTED_EMISSION_LINE`、`MANUAL_OBSERVED_WAVE` 和 `REDSHIFT_SPECTRUM_INDEX`。`z_guess` 会优先由手动波长推断；手动波长为空时，再用已有 `REDSHIFT_MEASUREMENTS` 或已设置的目标红移。

        如果一个目标有多条光谱，建议在 `REDSHIFT_MEASUREMENTS` 里填多条记录；后面会按目标取中位数红移，并显示 scatter。

        方法说明：本节只用于宿主窄发射线的红移复核，不使用第 7 节的超新星宽吸收线高斯拟合。局部窗口先用 Savitzky-Golay 做移动窗口低阶多项式预平滑；然后在窗口左右两端各取一段谱的中位数，连接这两个中位数点，得到一条局部线性连续谱；最后用 `flux / continuum` 归一化。蓝色曲线是局部连续谱归一化后的高斯拟合，仅辅助判断宿主窄线中心；绿线是自动取峰/取谷位置；紫线是手动或最终采用位置。如果后续想正式采用高斯中心，仍然通过手动把 `MANUAL_OBSERVED_WAVE` 填成图中的拟合中心来控制。`z_preview` 返回绿线自动红移，`redshift_plot["adopted_z"]` 是紫线红移。TNS 红移只打印作外部参考，不参与本 notebook 的红移采用。
        """
    ),
    code(
        """
        # 本 cell 通常只需要改这三项。
        SELECTED_EMISSION_LINE = "Halpha"  # 可选示例：Halpha, Hbeta, OIII5007, OIII4959, SII6716
        MANUAL_OBSERVED_WAVE = 6574  # 看图后填观测波长，例如 6701.2；第一次看图可先保留 None
        REDSHIFT_SPECTRUM_INDEX = 0  # 先看下面的 spectrum_index 表，再改这里选择第几条光谱

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
        redshift_tns_ref = snt.tns_redshift_reference(PROJECT_ROOT, redshift_check_target)

        redshift_items = sorted(
            [spec for spec in spectra_raw if spec["target"] == snt.target_key(redshift_check_target)],
            key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
        )
        display(snt.spectrum_choice_table(spectra_raw, redshift_check_target))
        redshift_spec = redshift_items[int(REDSHIFT_SPECTRUM_INDEX)]
        redshift_plot, z_preview = snt.plot_redshift_zoom(
            redshift_spec,
            SELECTED_EMISSION_LINE,
            rest_wave=redshift_rest_wave,
            z_guess=redshift_z_guess,
            half_width=REDSHIFT_HALF_WIDTH,
            manual_observed_wave=MANUAL_OBSERVED_WAVE,
            mode="emission",
        )
        snt.show_figure(redshift_plot.get("figure"))
        # Keep this output concise; do not expand back to the verbose purple/manual-adopted two-record printout.
        print(f"line = {SELECTED_EMISSION_LINE}, rest_wave = {redshift_rest_wave:.3f} A")
        print(f"plot z_guess = {redshift_z_guess:.6f}")
        try:
            if np.isfinite(redshift_tns_ref["z_tns"]):
                print(f"TNS/public-catalog reference z = {redshift_tns_ref['z_tns']:.6f} ({redshift_tns_ref['status']}; not used in calculation)")
            else:
                print(f"TNS/public-catalog reference z = unavailable ({redshift_tns_ref['status']}; not used in calculation)")
            if redshift_tns_ref.get("type_tns"):
                print(f"TNS/public-catalog type = {redshift_tns_ref['type_tns']}")
        except Exception:
            print("未找到 TNS 数据")
        print(f"auto line z = {z_preview:.6f}")
        print(f"auto line lambda = {redshift_plot['auto_wave']:.3f} A")
        print("绿线调整合理后，请将一下内容填入 REDSHIFT_MEASUREMENTS")
        print({
            "target": redshift_spec["target"],
            "file": redshift_spec["file"],
            "line": SELECTED_EMISSION_LINE,
            "kind": "host/emission",
            "rest_wave": redshift_rest_wave,
            "observed_wave": redshift_plot["auto_wave"],
        })
        """
    ),
    md(
        """
        ## 5. 汇总手动红移，并用本地光谱粗分类自动选线

        方法说明：手动红移按目标取中位数，scatter 只作为多条线/多历元一致性的提示。粗分类不是物理拟合；它把局部线性连续谱归一化后的关键吸收线强度、宿主窄发射线启发式红移，以及已有 Superfit/DASH 模板结果合并成类型建议。默认不把粗分类红移写入科学测量。
        """
    ),
    code(
        """
        redshift_table, redshift_summary, MANUAL_REDSHIFT_BY_TARGET = snt.redshift_table_from_measurements(REDSHIFT_MEASUREMENTS)
        display(redshift_table)
        display(redshift_summary)

        spectra = snt.apply_redshift_overrides(spectra_raw, MANUAL_REDSHIFT_BY_TARGET)

        rough_spectrum_table, rough_target_table, rough_feature_table = snt.rough_classify_spectra(spectra)
        template_spectrum_table, template_target_table = snt.summarize_local_template_classifications(PROJECT_ROOT)
        active_targets = {spec["target"] for spec in spectra}
        if not template_target_table.empty:
            template_target_table = template_target_table[template_target_table["target"].isin(active_targets)].reset_index(drop=True)
        if not template_spectrum_table.empty:
            template_spectrum_table = template_spectrum_table[template_spectrum_table["target"].isin(active_targets)].reset_index(drop=True)
        classification_target_table = snt.combine_template_and_rough_classifications(template_target_table, rough_target_table)
        if AUTO_CLASSIFY_TYPES:
            spectra = snt.apply_classification_context_to_spectra(
                spectra,
                classification_target_table,
                apply_type=True,
                apply_z=AUTO_APPLY_ROUGH_Z,
                overwrite_existing_type=AUTO_OVERWRITE_MANUAL_TYPE,
            )

        summary = sp.build_summary(spectra)
        display(summary)
        display(classification_target_table)
        display(template_target_table)
        display(rough_target_table)
        display(snt.selected_line_plan(spectra, TARGET_LINES))

        RUN_TAG = snt.analysis_output_tag(summary[["target"]], OUTPUT_TAG)
        print(f"analysis output tag = {RUN_TAG}")
        """
    ),
    md(
        """
        ## 6. 多历元光谱序列

        下轴是观测波长，上轴是按当前目标红移换算后的静止系波长。谱线竖线画在观测波长位置，即 `rest_wave * (1 + z)`；如果目标还没有红移，就只能暂时画在静止波长位置。

        方法说明：本步只是可视化，没有额外拟合；光谱为显示目的用 Savitzky-Golay 平滑和中位数尺度归一，谱线位置只由第 5 节采用的 `z` 换算。
        """
    ),
    code(
        """
        for target in sorted(summary["target"].unique()):
            sequence_fig = snt.plot_spectral_sequence_dual_axis(
                target,
                spectra,
                target_lines=TARGET_LINES,
                fig_dir=FIG_DIR,
                save_figures=SAVE_FIGURES,
            )
            snt.show_figure(sequence_fig)
        """
    ),
    md(
        """
        ## 7. 批量测量谱线、黑体颜色温度和宿主线

        这一步使用第 5 节得到的手动红移。如果某个目标还没有红移，速度和静止系谱线测量只是占位结果，不应写入科学结论。

        实际测量的谱线由第 5 节的 `selected_line_plan` 决定：`TARGET_LINES` 有手动覆盖时优先用它，否则按手动类型或自动粗分类类型选择关键谱线。

        方法说明：谱线测量先转到当前静止系，再用 Savitzky-Golay 移动窗口低阶多项式预平滑，并用局部线性连续谱归一化；随后直接在归一化谱上拟合吸收型高斯，最终的吸收中心 `abs_wave`、速度 `velocity_kms`、线深 `depth` 和 `FWHM_A` 都来自该高斯拟合。pEW 仍由 `1 - flux/continuum` 的正面积直接积分，不改成高斯面积。黑体颜色温度用 Planck 黑体谱做非线性最小二乘拟合。宿主线指标用局部中位数连续谱和 robust noise，不做高斯拟合。
        """
    ),
    code(
        """
        measure_kwargs = dict(
            line_half_width=LINE_HALF_WIDTH,
            line_smooth_window=LINE_SMOOTH_WINDOW,
            line_edge_fraction=LINE_EDGE_FRACTION,
            line_param_overrides=LINE_PARAM_OVERRIDES,
        )

        summary, line_df, line_qc, bb_df, host_lines, host_summary, target_status = snt.measure_all_features(
            spectra,
            target_lines=TARGET_LINES,
            bb_wave_range=BB_WAVE_RANGE,
            **measure_kwargs,
        )

        display(target_status)
        display(line_qc[["target", "file", "line", "fit_method", "abs_wave", "velocity_kms", "velocity_err_kms", "pEW_A", "FWHM_A", "FWHM_err_A", "depth", "fit_center_err_A", "fit_sigma_A", "fit_sigma_err_A", "fit_depth_err", "fit_chi2_red", "extrema_wave_A", "extrema_depth", "qc_flag", "qc_note"]].head(20))
        """
    ),
    md(
        """
        ## 8. 谱线局部诊断图：中心、吸收谷、拟合和 pEW 区域

        方法说明：每个谱线面板分上下两行。上图显示原始 flux、Savitzky-Golay 预平滑后的 flux，以及橙色局部线性连续谱；下图显示 `flux / continuum` 后的归一化谱。紫色线是本次测量实际使用的高斯吸收拟合，绿色线是高斯中心，灰色细线可对照旧的极值位置。浅紫色区域是 pEW 积分区域，即归一化谱中 `1 - flux/continuum` 的正面积；它不是误差带或高斯置信区间。
        """
    ),
    code(
        """
        line_diagnostics_fig = snt.plot_line_diagnostics_grid(
            spectra,
            line_qc,
            target=DIAGNOSTIC_TARGET,
            max_panels=MAX_DIAGNOSTIC_PANELS,
            fig_dir=FIG_DIR,
            save_figures=SAVE_FIGURES,
            filename_tag=RUN_TAG,
            **measure_kwargs,
        )
        snt.show_figure(line_diagnostics_fig)
        """
    ),
    md(
        """
        ## 9. 黑体连续谱拟合图

        方法说明：先取 `BB_WAVE_RANGE` 内的静止系光谱，平滑后做简单背景偏移和归一化，再用 Planck `B_lambda(T)` 黑体谱作非线性最小二乘拟合；输出的是颜色温度 proxy，不是完整辐射传输温度。图的标题分两行显示，只有最底行显示横坐标标题，避免标题与横坐标重叠。
        """
    ),
    code(
        """
        blackbody_fit_fig = snt.plot_blackbody_fit_grid(
            spectra,
            target=DIAGNOSTIC_TARGET,
            wave_range=BB_WAVE_RANGE,
            fig_dir=FIG_DIR,
            save_figures=SAVE_FIGURES,
            filename_tag=RUN_TAG,
        )
        snt.show_figure(blackbody_fit_fig)
        """
    ),
    md("## 10. 科学量图：谱线速度\n\n方法说明：本步只绘制第 7 节已经测出的速度，不再做新拟合。"),
    code(
        """
        velocity_fig = snt.plot_quantity_by_target(line_qc, "velocity_kms", "Velocity (km/s)", "Line velocity evolution", snt.tagged_filename("line_velocity_evolution.png", RUN_TAG), FIG_DIR, save_figures=SAVE_FIGURES)
        snt.show_figure(velocity_fig)
        """
    ),
    md("## 11. 科学量图：pseudo-equivalent width\n\n方法说明：本步只绘制第 7 节由局部线性连续谱归一化后积分得到的 pEW，不再做新拟合。"),
    code(
        """
        pew_fig = snt.plot_quantity_by_target(line_qc, "pEW_A", "pEW (Angstrom)", "Pseudo-equivalent width evolution", snt.tagged_filename("pew_evolution.png", RUN_TAG), FIG_DIR, save_figures=SAVE_FIGURES)
        snt.show_figure(pew_fig)
        """
    ),
    md("## 12. 科学量图：FWHM\n\n方法说明：本步只绘制第 7 节由高斯拟合 sigma 换算得到的 FWHM，不再做新拟合。"),
    code(
        """
        fwhm_fig = snt.plot_quantity_by_target(line_qc, "FWHM_A", "FWHM (Angstrom)", "Line FWHM evolution", snt.tagged_filename("fwhm_evolution.png", RUN_TAG), FIG_DIR, save_figures=SAVE_FIGURES)
        snt.show_figure(fwhm_fig)
        """
    ),
    md("## 13. 科学量图：线深\n\n方法说明：本步只绘制第 7 节高斯拟合得到的线深，不再做新拟合。"),
    code(
        """
        depth_fig = snt.plot_quantity_by_target(line_qc, "depth", "Line depth", "Absorption-line depth evolution", snt.tagged_filename("line_depth_evolution.png", RUN_TAG), FIG_DIR, save_figures=SAVE_FIGURES)
        snt.show_figure(depth_fig)
        """
    ),
    md("## 14. 科学量图：连续谱黑体颜色温度\n\n方法说明：本步只把第 7/9 节 Planck 黑体谱拟合得到的颜色温度画成演化图，不再做新拟合。"),
    code(
        """
        ok_bb = bb_df[bb_df["status"].eq("ok")].copy()
        if ok_bb.empty:
            print("没有成功的黑体颜色温度拟合。")
        else:
            fig, ax = plt.subplots(figsize=(10, 5))
            for target, group in ok_bb.groupby("target"):
                x = group["phase_days"] if group["phase_days"].notna().any() else pd.to_datetime(group["date_obs"])
                ax.errorbar(x, group["T_bb_K"], yerr=group["T_err_K"], marker="o", capsize=2, lw=1.2, label=target)
            ax.set_ylabel("Blackbody color temperature (K)")
            ax.set_xlabel("Days since discovery / obs date")
            ax.set_title("Continuum blackbody color-temperature estimate")
            ax.grid(alpha=0.25)
            ax.legend(fontsize=8)
            snt.save_figure(fig, FIG_DIR, snt.tagged_filename("blackbody_temperature.png", RUN_TAG), enabled=SAVE_FIGURES)
            snt.show_figure(fig)
        display(bb_df)
        """
    ),
    md("## 15. 科学量图：宿主/环境窄线指标\n\n方法说明：宿主线指标使用红移后的窄窗口，局部两侧窗口取中位数连续谱，用 MAD/标准差估计噪声，并积分线区通量；这里不做高斯拟合，也不能替代严格流量定标的环境诊断。"),
    code(
        """
        host_line_fig = snt.plot_host_line_grid(host_lines, target=DIAGNOSTIC_TARGET, fig_dir=FIG_DIR, save_figures=SAVE_FIGURES, filename_tag=RUN_TAG)
        snt.show_figure(host_line_fig)
        display(host_summary)
        display(host_lines)
        """
    ),
    md(
        """
        ## 16. 单条谱线局部检查图

        改 `CHECK_TARGET`、`CHECK_LINE`、`CHECK_SPECTRUM_INDEX`，或回到配置区改 `LINE_PARAM_OVERRIDES` 后重新运行。

        图中：

        - 灰色：局部原始光谱。
        - 黑色：平滑后的真实观测谱线轮廓。
        - 橙色：局部线性连续谱。
        - 紫色：第 7 节实际用于测量的高斯吸收轮廓。
        - 灰虚线：旧的极值位置，仅作对照。
        - 红虚线：谱线静止波长；绿虚线：高斯中心。

        方法说明：这张图是第 7 节单条谱线测量的放大复核。连续谱为局部线性模型，紫色为第 7 节同一个高斯拟合结果，pEW 仍来自连续谱与平滑谱之间的直接积分；灰虚线给出旧的极值位置，便于对照。
        """
    ),
    code(
        """
        CHECK_TARGET_LOCAL = summary.iloc[0]["target"] if CHECK_TARGET is None else CHECK_TARGET
        CHECK_LINE_KEY = CHECK_LINE  # 例如 "Halpha"；None 表示优先使用当前光谱里 qc=adopt/check 的第一条线
        CHECK_SPECTRUM_INDEX = 0  # 先看下面的 spectrum_index 表，再改这里选择第几条光谱

        display(snt.spectrum_choice_table(spectra, CHECK_TARGET_LOCAL))
        check_items = sorted(
            [spec for spec in spectra if spec["target"] == snt.target_key(CHECK_TARGET_LOCAL)],
            key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
        )
        check_spec = check_items[int(CHECK_SPECTRUM_INDEX)]
        if CHECK_LINE_KEY is None:
            checked = line_qc[
                line_qc["target"].eq(snt.target_key(CHECK_TARGET_LOCAL))
                & line_qc["file"].eq(check_spec["file"])
                & line_qc["status"].eq("ok")
                & line_qc["qc_flag"].isin(["adopt", "check"])
            ].copy()
            if not checked.empty:
                checked["qc_order"] = checked["qc_flag"].map({"adopt": 0, "check": 1}).fillna(2)
                CHECK_LINE_KEY = checked.sort_values(["qc_order", "line"]).iloc[0]["line"]
            else:
                CHECK_LINE_KEY = snt.line_keys_for(check_spec, TARGET_LINES)[0]

        print(f"line check target={snt.target_key(CHECK_TARGET_LOCAL)}, spectrum_index={CHECK_SPECTRUM_INDEX}, line={CHECK_LINE_KEY}")
        print(f"file = {check_spec['file']}")
        print(f"z = {check_spec.get('z')} ({check_spec.get('z_source')})")
        if not np.isfinite(check_spec.get("z", np.nan)):
            print("WARNING: 当前光谱还没有采用红移；静止系谱线窗口和绿线位置不能用于科学判断。请先在 REDSHIFT_MEASUREMENTS 填入第 4 节确认的宿主窄线红移。")

        check_result, check_fig = snt.plot_line_check(
            spectra,
            target=CHECK_TARGET_LOCAL,
            line_key=CHECK_LINE_KEY,
            spectrum_index=CHECK_SPECTRUM_INDEX,
            fig_dir=FIG_DIR,
            save_figures=SAVE_FIGURES,
            **measure_kwargs,
        )
        snt.show_figure(check_fig)
        display(check_result)
        """
    ),
    md("## 17. 保存 CSV 汇总\n\n方法说明：本节只把前面已经算出的表格写入 CSV，不运行新的拟合或重新测量。输出文件会使用 `RUN_TAG`，例如 `SN2026KID_line_diagnostics_qc.csv`；同一目标重跑会覆盖同一目标文件，但不会覆盖其他目标。"),
    code(
        """
        def output_path(name):
            ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
            return snt.analysis_output_path(ANALYSIS_DIR, name, tag=RUN_TAG, product_prefix=PRODUCT_PREFIX)


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

        方法说明：本节不做拟合，只列出需要人工检查和后续采用的结果。

        正式报告里建议只引用：

        1. 由宿主窄线手动测得并写入 `REDSHIFT_MEASUREMENTS` 的红移；
        2. `qc_flag=adopt` 的自动测量；
        3. 或者经过上面局部检查图确认后的 `qc_flag=check` 测量。

        如果某条线的高斯中心仍然落到错误吸收谷，优先在配置区用 `LINE_PARAM_OVERRIDES` 调整 `half_width`、`smooth_window`、`edge_fraction`，然后重新运行批量测量之后的 cells。
        """
    ),
]


TARDIS_NOTEBOOK = [
    md(
        """
# 03 可选 TARDIS 建模

这个 notebook 不再依赖 `notebooks/legacy/` 或遗留 `.dat` 数据。它从本地 `data/SN*/` 一维 FITS 光谱读取观测谱，并优先使用 `02_spectral_analysis_pipeline.ipynb` 写出的目标化分析表来给 TARDIS 生成第一版参数。

TARDIS 在本项目里只用于辅助谱线识别和定性比较谱形，不作为抛射物质量、丰度或爆炸能量的强约束。默认 `RUN_TARDIS=False`，先检查配置；确认参数后再在 `tardis` 环境中运行模拟。
        """
    ),
    code(
        """
%matplotlib inline

from pathlib import Path
import shutil
import sys
from importlib import reload

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display

PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from src import spectral_notebook_tools as snt

ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        """
    ),
    md(
        """
## 1. 目标和手动覆盖参数

先只改这个 cell。`ANALYSIS_TAG` 为空时会自动读取该目标最新的 `*_target_status.csv`、`*_line_diagnostics_qc.csv` 等分析产物；如果你想强制使用某次输出，可以填 `SN2026KID` 或你在 02 里设置的 `OUTPUT_TAG`。

手动覆盖项优先级最高。`MANUAL_APPARENT_MAG` 用于由红移和视星等粗估 luminosity；如果你已经知道更合适的 bolometric luminosity，直接填 `MANUAL_LOG_LSUN`。
        """
    ),
    code(
        """
TARGET = "SN2026KID"
ANALYSIS_TAG = ""  # 空字符串表示按目标读取最新产物；也可填 02 的 OUTPUT_TAG/RUN_TAG
SPECTRUM_INDEX = 0

RUN_TARDIS = False  # 确认配置和原子数据后再改 True

MANUAL_Z = np.nan
MANUAL_TYPE = ""
MANUAL_VELOCITY_KMS = np.nan
MANUAL_EPOCH_DAYS = np.nan
MANUAL_APPARENT_MAG = np.nan
MANUAL_LOG_LSUN = np.nan

BASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "tardis" / "base_Ia.yml"
        """
    ),
    md(
        """
## 2. 从 02 的科学产物估计 TARDIS 起点

本步读取的是当前项目产物，不读取 `legacy/`。优先使用手动红移表，其次目标状态表和光谱摘要表；类型来自目标状态/光谱摘要；速度来自 `line_diagnostics_qc.csv` 中 `adopt/check` 的关键谱线；epoch 和 luminosity 是粗略起点，通常需要人工调整。
        """
    ),
    code(
        """
reload(snt)

context = snt.estimate_tardis_context(
    PROJECT_ROOT,
    TARGET,
    analysis_tag=ANALYSIS_TAG or None,
    spectrum_index=SPECTRUM_INDEX,
    manual_z=MANUAL_Z,
    manual_type=MANUAL_TYPE,
    manual_velocity_kms=MANUAL_VELOCITY_KMS,
    manual_epoch_days=MANUAL_EPOCH_DAYS,
    manual_apparent_mag=MANUAL_APPARENT_MAG,
    manual_log_lsun=MANUAL_LOG_LSUN,
)

display(snt.spectrum_choice_table(context["spectra"], TARGET))
display(snt.tardis_context_table(context))

for name, table in context["analysis_tables"].items():
    if not table.empty:
        print(f"{name}: rows={len(table)}, product_file={table.get('product_file', pd.Series([''])).iloc[0]}")
        """
    ),
    md(
        """
## 3. 检查选中的观测光谱

下轴是观测波长，上轴是按当前采用红移换算后的静止系波长。这个图只用于检查 TARDIS 要比较哪一条真实观测光谱。
        """
    ),
    code(
        """
spec = context["spectrum"]
z = context["z"]

fig, ax = plt.subplots(figsize=(10.5, 4.6))
ax.plot(spec["wave"], snt.normalize_for_comparison(spec["flux"]), color="black", lw=0.8)
ax.set_xlabel("Observed wavelength (Angstrom)")
ax.set_ylabel("Normalized flux")
ax.set_title(f"{context['target']} observed spectrum for TARDIS setup")
ax.grid(alpha=0.25)
snt.add_rest_top_axis(ax, z)
snt.show_figure(fig)

print(f"selected file = {spec['file']}")
print(f"z = {z:.6f} ({context['z_source']})")
        """
    ),
    md(
        """
## 4. 生成 TARDIS YAML 配置

配置从 `configs/tardis/base_Ia.yml` 复制并覆盖：`luminosity_requested`、`time_explosion`、速度范围和 `atom_data` 绝对路径。非 Ia 目标会使用一个非常粗略的 II/Ibc 均匀丰度 preset；这只是定性起点，不代表自动物理拟合。
        """
    ),
    code(
        """
CONFIG_PATH = PROJECT_ROOT / "configs" / "tardis" / f"{context['target']}.yml"
config, config_path = snt.build_tardis_config_from_context(
    context,
    project_root=PROJECT_ROOT,
    base_config_path=BASE_CONFIG_PATH,
    output_config_path=CONFIG_PATH,
)

print(f"wrote config: {config_path}")
display(pd.DataFrame([
    {"section": "supernova", **config["supernova"]},
    {"section": "velocity", **config["model"]["structure"]["velocity"]},
    {"section": "abundances", **config["model"]["abundances"]},
]))
        """
    ),
    md(
        """
## 5. 检查 TARDIS 原子数据

TARDIS 需要 `data/kurucz_cd23_chianti_H_He_latest.h5`。如果缺失，在终端运行：

```bash
conda activate tardis
python scripts/download_tardis_atom_data.py
```
        """
    ),
    code(
        """
ATOM_DATA_FILE = Path(config["atom_data"])
print(f"atom_data = {ATOM_DATA_FILE}")

if ATOM_DATA_FILE.exists():
    print(f"found atomic data: {ATOM_DATA_FILE.stat().st_size / 1e6:.0f} MB")
else:
    print("atomic data missing; run scripts/download_tardis_atom_data.py in the tardis environment")
        """
    ),
    md(
        """
## 6. 可选：运行 TARDIS

只有 `RUN_TARDIS=True` 时才会导入并运行 TARDIS。运行时间取决于 packet 数和迭代数；如果只是检查 notebook 流程，保持 False。
        """
    ),
    code(
        """
tardis_wave = None
tardis_flux = None
sim = None

if RUN_TARDIS:
    if not ATOM_DATA_FILE.exists():
        raise RuntimeError(f"Atomic data file not found: {ATOM_DATA_FILE}")
    from tardis import run_tardis

    print(f"running TARDIS with {config_path}")
    try:
        sim = run_tardis(str(config_path), show_convergence_plots=False, log_level="WARNING", show_progress_bars=False)
    except TypeError:
        sim = run_tardis(str(config_path), show_convergence_plots=False, log_level="WARNING")
    tardis_wave, tardis_flux = snt.extract_tardis_spectrum_arrays(sim)
    print("simulation complete")
    print(f"iterations_executed = {getattr(sim, 'iterations_executed', 'unknown')}")
    print(f"spectrum points = {len(tardis_wave)}")
else:
    print("RUN_TARDIS=False：已跳过模拟，只生成/检查配置。")
        """
    ),
    md(
        """
## 7. 保存模拟结果并比较谱形

如果刚刚运行了 TARDIS，本步会保存当前模拟光谱和配置副本到 `output/<target>/tardis/`。如果没有运行，但该目录已经有当前目标的 TARDIS 输出，本步可以读取并显示已有结果；这只是当前项目输出，不依赖 `legacy/`。
        """
    ),
    code(
        """
TARDIS_DIR = PROJECT_ROOT / "output" / context["target"] / "tardis"
TARDIS_DIR.mkdir(parents=True, exist_ok=True)
SPECTRUM_OUT = TARDIS_DIR / f"tardis_spectrum_{context['target']}.dat"
CONFIG_COPY = TARDIS_DIR / f"tardis_config_{context['target']}.yml"
COMPARISON_OUT = TARDIS_DIR / f"tardis_comparison_{context['target']}.png"

if tardis_wave is not None and tardis_flux is not None:
    np.savetxt(SPECTRUM_OUT, np.column_stack([tardis_wave, tardis_flux]), header="wavelength_A luminosity_density_lambda_erg_s_A")
    shutil.copyfile(config_path, CONFIG_COPY)
    print(f"saved {SPECTRUM_OUT}")
    print(f"saved {CONFIG_COPY}")
elif SPECTRUM_OUT.exists():
    existing = np.loadtxt(SPECTRUM_OUT)
    tardis_wave, tardis_flux = existing[:, 0], existing[:, 1]
    print(f"loaded existing current-project output: {SPECTRUM_OUT}")
else:
    print("还没有 TARDIS 光谱。把 RUN_TARDIS 改成 True 后重新运行第 6-7 节。")

if tardis_wave is not None and tardis_flux is not None:
    comparison_fig = snt.plot_tardis_comparison(
        context["spectrum"],
        tardis_wave,
        tardis_flux,
        z=context["z"],
        target=context["target"],
        output_path=COMPARISON_OUT,
    )
    snt.show_figure(comparison_fig)
        """
    ),
    md(
        """
## 8. 调参边界

优先调 `MANUAL_Z`、`MANUAL_TYPE`、`MANUAL_VELOCITY_KMS`、`MANUAL_EPOCH_DAYS` 和 luminosity。若只是几条谱线对不上，不要直接把 TARDIS 结果解释成物理参数；本项目的稀疏光谱更适合把 TARDIS 当作谱线识别和连续谱形状的 sanity check。
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
        import sys

        import pandas as pd
        from IPython.display import display, Image, Markdown

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        sys.path.insert(0, str(PROJECT_ROOT))

        from src import spectral_notebook_tools as snt

        ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"

        def read_product(filename):
            table = snt.read_combined_analysis_products(ANALYSIS_DIR, filename)
            if table.empty:
                raise FileNotFoundError(f"缺少 {filename} 或目标化 *_{filename}")
            return table

        def latest_figure(filename):
            candidates = sorted(FIG_DIR.glob(f"*_{filename}"), key=lambda p: p.stat().st_mtime, reverse=True)
            legacy = FIG_DIR / filename
            if legacy.exists():
                candidates.append(legacy)
            return candidates[0] if candidates else None

        target_status = read_product("target_status.csv")
        line_qc = read_product("line_diagnostics_qc.csv")
        host_summary = read_product("host_environment_summary.csv")
        bb = read_product("blackbody_temperature.csv")
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

        本项目整合 TNS 元数据和找星图、可用时的 Lasair/ZTF 光变曲线、WISeREP 公开光谱，以及 `data/SN*/` 下的本地 BFOSC 一维光谱。下面的分析产物可以由 `02_spectral_analysis_pipeline.ipynb` 逐目标调参生成，也可以由 `scripts/build_analysis_products.py` 批量生成。
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
        下面的 code cell 会优先显示带目标名前缀的最新图；如果没有目标化图，再回退到旧的无前缀批量图。
        """
    ),
    code(
        """
        for title, fig in [
            ("目标状态", "target_status_table.png"),
            ("谱线速度演化", "line_velocity_evolution.png"),
            ("pEW 演化", "pew_evolution.png"),
            ("连续谱颜色温度估计", "blackbody_temperature.png"),
            ("宿主/环境谱线探测", "host_line_detections.png"),
        ]:
            path = latest_figure(fig)
            display(Markdown(f"### {title}"))
            if path is None:
                print(f"缺少图：{fig}")
            else:
                print(path.name)
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
        write_notebook("03_tardis_modeling_optional.ipynb", TARDIS_NOTEBOOK, display_name="tardis", python_version="3.13.3"),
        write_notebook("04_project_report.ipynb", REPORT_NOTEBOOK, display_name="astro_env", python_version="3.10.20"),
    ]
    print("Wrote notebooks:")
    for path in written:
        print(f"- {path}")


if __name__ == "__main__":
    main()
