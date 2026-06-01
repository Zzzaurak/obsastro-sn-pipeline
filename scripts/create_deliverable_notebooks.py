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
        # 02 光谱分析 Pipeline

        这个 notebook 用一个可复现 pipeline 替代原来的多个探索 notebook。它从 `data/` 读取定标后的一维 FITS 光谱，测量适合稀疏光谱样本的保守诊断量，把 CSV 表写到 `output/analysis_pipeline/`，并生成可直接放进报告的图。

        根据 `paper/sparse-multi-epoch-sn-spectra/` 的文献调研：每个目标只有 1-3 条光谱时，稳妥结论应集中在类型/子型检查、光谱相位、速度、pEW/FWHM、宿主污染和公开样本比较上。TARDIS 只作为解释辅助，不作为主要证据。
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

        from src.spectral_pipeline import build_all

        ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"
        """
    ),
    md("## 运行或刷新分析产物"),
    code(
        """
        RUN_PIPELINE = True

        if RUN_PIPELINE:
            paths = build_all(PROJECT_ROOT)
            print(f"已更新 {ANALYSIS_DIR}")
            for item in paths.get("figures", []):
                print(item)
        else:
            print("使用现有 output/analysis_pipeline 产物。")
        """
    ),
    md("## 目标层面的科学状态"),
    code(
        """
        target_status = pd.read_csv(ANALYSIS_DIR / "target_status.csv")
        display(target_status)
        """
    ),
    md(
        """
        ## 带质检标记的谱线诊断

        `qc_flag=adopt` 表示自动测量通过保守检查，可以用于第一版图表。`qc_flag=check` 表示在写入科学结论前必须人工看图确认。这样可以避免把噪声谷、宽线混合或次要谱线误读成可靠物理量。
        """
    ),
    code(
        """
        line_qc = pd.read_csv(ANALYSIS_DIR / "line_diagnostics_qc.csv")
        display(line_qc[["target", "date_obs", "phase_days", "type", "line", "velocity_kms", "pEW_A", "FWHM_A", "qc_flag", "qc_note"]])
        """
    ),
    md("## 宿主星系/环境诊断"),
    code(
        """
        host_summary = pd.read_csv(ANALYSIS_DIR / "host_environment_summary.csv")
        host_lines = pd.read_csv(ANALYSIS_DIR / "host_environment_lines.csv")
        display(host_summary)
        display(host_lines[host_lines["status"].eq("detected")].head(30))
        """
    ),
    md("## 报告可用图表"),
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
            if path.exists():
                display(Markdown(f"### {fig}"))
                display(Image(filename=str(path)))
        """
    ),
    md("## 多历元光谱序列"),
    code(
        """
        for path in sorted(FIG_DIR.glob("spectral_sequence_*.png")):
            display(Markdown(f"### {path.stem.replace('_', ' ')}"))
            display(Image(filename=str(path)))
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
