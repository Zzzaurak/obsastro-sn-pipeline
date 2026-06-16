<!-- 请 AI 编辑此文件时尽可能适合人看；给 AI 看的项目细节主要在 `AGENTS.md` -->

# SN 观测与光谱分析流水线

本项目围绕一组新近超新星目标，完成从观测准备到稀疏光谱分析、报告 notebook 和英文汇报 slides 的可复现流程。当前版本的核心思路是：数据获取和观测准备自动化，光谱诊断集中到一个稳定 pipeline，TARDIS 只作为定性解释辅助。

## 环境

推荐用 Conda 一键创建主环境：

```bash
conda env create -f envs/environment_astro_env.yml
conda activate astro_env
python -m ipykernel install --user --name astro_env --display-name "Python (astro_env)"
```

| 环境 | Python | 用途 |
|---|---|---|
| `astro_env` | 3.10 | 主流水线、TNS/Lasair/WISeREP、找星图、光谱下载与绘图、astrodash、批量光谱分析。 |
| `tardis` | 3.13 | 可选 TARDIS 蒙特卡洛辐射传输模拟。 |

`tardis` 环境下载地址：https://tardis-sn.github.io/tardis/installation.html

除可选 TARDIS 流程外，其他 notebook 和脚本都在 `astro_env` 中运行。可选 TARDIS 流程包括 `notebooks/03_tardis_modeling_optional.ipynb` 中真正运行模拟的 cells，以及 `scripts/download_tardis_atom_data.py`、`scripts/download_tardis_model_resources.py`、`scripts/run_tardis_tuning.py`。

`astro_env` 中 `numpy` 必须保持 `1.23.5`，因为 astrodash 与旧版 tensorflow 对新版 numpy 不兼容。环境文件已经在 conda 层和 pip 层同时锁定该版本；迁移到新电脑时不要手动混装。

`astro_env` 的 TensorFlow 依赖使用 `tensorflow[and-cuda]==2.15.1`，用于在 Linux/WSL 下给 DASH 推理安装 CUDA/cuDNN 运行库。更新现有环境时运行：

```bash
conda activate astro_env
python -m pip install --upgrade "tensorflow[and-cuda]==2.15.1" "numpy==1.23.5"
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

依赖入口以 `envs/environment_astro_env.yml` 为准；旧的 `requirements.txt` 已删除，避免同学用 pip 安装出缺少 Jupyter 组件或 numpy 版本不对的环境。

## 凭证与配置

`.env` 不提交 git，用于保存本地凭证：

```env
TNS_USER_ID=
TNS_USER_NAME=
LASAIR_API_TOKEN=
LASAIR_TOKEN=
WISEREP_API_KEY=
```

当前 TNS 使用 user 模式：下载 TNS 公共目录 CSV，并抓取目标网页补充最新测光和找星图。TNS bot API 不是当前流程的依赖。

观测参数集中在 `configs/sn_parameter.json`：

- `observing`: 目标名、日期、站址、最低高度角、太阳高度限制、时间分辨率。
- `tns`: 是否启用 TNS、是否下载 TNS 文件。
- `lasair`: 是否启用 Lasair 光变曲线。
- `wiserep`: 是否启用 WISeREP 光谱。
- `output`: 输出目录、找星图视场。

加速参数集中在 `configs/acceleration.json`：

- `runtime`: GPU 开关、`CUDA_VISIBLE_DEVICES`、Superfit 最大并行 worker、每个 worker 的 BLAS 线程数。
- `superfit`: NGSF/Superfit 批量重跑 worker、红移网格、分辨率、是否跳过已有 CSV。
- `dash`: AstroDash 是否使用 GPU、是否计算较慢的 rlap、输出 top-N。
- `tardis`: 只写入生成的 TARDIS YAML；控制 `montecarlo.nthreads`、packet 数、迭代数和 spectrum 网格。实际 `tardis` 环境的 CUDA/Numba-CUDA 安装仍需在该环境中单独完成。

## 数据

观测数据以 `data/<观测目标>/*` 的格式存放

## 当前主流程

```bash
conda activate astro_env

# 1. 目标元数据、观测窗口、找星图
python scripts/fetch_target_params.py

# 2. Lasair 光变曲线和 WISeREP 光谱
python scripts/fetch_aux_data.py

# 3. 批量光谱诊断表格与报告图
python scripts/build_analysis_products.py

# 4. 生成 slides 专用图
python scripts/build_presentation_figures.py

```

顶层 `notebooks/` 现在直接手工维护，不再通过脚本重生成。`02_spectral_analysis_pipeline.ipynb` 是主分析和手动调参入口，后续说明、图注和输出都以它为准。

最终 slides 位于 `ppt/`：

```bash
cd ppt
latexmk -pdf main.tex
```

已生成的 PDF 通常保存在 `ppt/slides.pdf` 或 `ppt/build/main.pdf`。

## 目录结构

```text
sn-pipline/
├── configs/
│   ├── sn_parameter.json          # 观测参数、目标名、站址、输出目录
│   └── tardis/                    # TARDIS 基础配置与按目标配置
├── data/                          # 本地 FITS、TNS 缓存、TARDIS 原子数据；不提交 git
├── envs/
│   └── environment_astro_env.yml  # 主环境定义
├── notebooks/
│   ├── 01_data_collection_and_observing.ipynb
│   ├── 02_spectral_analysis_pipeline.ipynb
│   ├── 03_tardis_modeling_optional.ipynb
│   └── 04_project_report.ipynb
├── output/                        # 每个目标和 analysis_pipeline 的输出；不提交 git
├── paper/                         # 文献调研与阅读材料
├── ppt/                           # 英文最终汇报 LaTeX slides
├── scripts/                       # 命令行入口，见下表
└── src/                           # 可复用 Python 模块
```

## `scripts/` 命令说明

| 脚本 | 状态 | 用途 |
|---|---|---|
| `fetch_target_params.py` | 原有 | 读取 `configs/sn_parameter.json`，调用主观测流水线，获取 TNS 目标信息，计算观测窗口，生成观测报告和找星图。等价入口：`python -m src.pipeline`。 |
| `fetch_aux_data.py` | 原有 | 读取 `.env` 和配置，下载 Lasair/ZTF 光变曲线与 WISeREP 光谱，保存 CSV、图片和清洁 `.dat` 光谱。等价入口：`python -m src.fetch_aux_data`。 |
| `build_analysis_products.py` | 新增 | 调用 `src.spectral_pipeline.build_all()`，批量读取 `data/SN*/` 的一维 FITS 光谱，生成目标状态、谱线速度、pEW/FWHM、黑体颜色温度、宿主线指标和质检标记。 |
| `build_presentation_figures.py` | 新增 | 从 `output/analysis_pipeline/figures/` 复制或重组 slides 需要的图，写到 `ppt/figures/`；读取目标状态时会兼容 `SN2026KID_target_status.csv` 这类逐目标调参产物。 |
| `download_tardis_atom_data.py` | 原有 | 首次运行 TARDIS 前把 TARDIS 内部数据目录配置到当前项目 `data/`，并下载或复用 `kurucz_cd23_chianti_H_He_latest.h5`。 |
| `download_tardis_model_resources.py` | 新增 | 把 `configs/tardis/model_resources.yml` 中声明的 TARDIS 包内置模型资源复制到 `data/tardis_models/`；当前主要是 Ia CSVY 分层密度/丰度示例和格式样例。 |
| `run_tardis_tuning.py` | 新增 | 批量运行有限 TARDIS 参数搜索，输出 `output/tardis_tuning/<target>/` 或带 `--run-label` 的独立探索目录；支持 `--include-model-resources` / `--model-resource-only` 测试 CSVY resources。 |

## `src/` 核心模块

| 模块 | 作用 |
|---|---|
| `src/pipeline.py` | 主观测流水线：配置加载、TNS 公共目录查询、页面抓取、观测窗口、报告和找星图。 |
| `src/fetch_aux_data.py` | 辅助数据流水线：协调 Lasair 光变曲线和 WISeREP 光谱下载。 |
| `src/spectral_pipeline.py` | 当前主分析模块：批量光谱读取、静止系修正、稀疏光谱诊断、质检表和报告图。 |
| `src/lasair.py` | Lasair API 访问、光变曲线 CSV 保存和绘图。 |
| `src/wiserep.py` | WISeREP 光谱搜索、下载、清洁 `.dat` 输出和绘图。 |
| `src/finder.py` | astroquery SkyView 找星图生成。 |
| `src/observability.py` | 夜间目标高度角和可观测窗口计算。 |
| `src/config.py`, `src/target.py`, `src/coordinates.py`, `src/time_utils.py`, `src/utils.py`, `src/tns.py` | 配置、数据模型、坐标/时间工具、HTTP/认证和 TNS 访问支持。 |

## Notebook 入口

顶层 `notebooks/` 只保留 4 个稳定入口：

| Notebook | 用途 |
|---|---|
| `01_data_collection_and_observing.ipynb` | 目标获取、观测准备、TNS/Lasair/WISeREP 输出盘点。 |
| `02_spectral_analysis_pipeline.ipynb` | 主光谱分析和手动调参入口：FITS 读取、TNS 公共目录红移、自动选线、速度、pEW/FWHM、黑体温度、宿主线指标和质检标记；只在“单条谱线局部检查图”里保留本地吸收线微调，可用 `CHECK_LINE_KEY=None` + `CHECK_LINE_INDEX` 选择关键线。`SAVE_PRODUCTS/SAVE_FIGURES=True` 时默认写出带目标名前缀的产物。该 notebook 直接编辑维护，不再依赖生成脚本。 |
| `03_tardis_modeling_optional.ipynb` | 可选 TARDIS 配置与模拟入口；从本地 FITS 和 02 的分析产物估计起始参数，不依赖 legacy notebook 或遗留数据。 |
| `04_project_report.ipynb` | 中文报告 notebook，汇总科学问题、数据、分析、解释和结论。 |

旧版探索 notebook 已移到 `notebooks/legacy/`，用于追溯早期手动步骤，不再作为正式复现入口。

## 主要输出

目标级输出保存在 `output/<target>/`：

```text
output/SN2026fov/
├── sn_report_2026-05-08_SN2026fov.txt
├── finder_TNS_*.jpg
├── finder_astroquery_DSS2_Red.png
├── lightcurve/
│   ├── lightcurve_lasair.csv
│   └── lightcurve_lasair.png
├── spectrum/
│   ├── spectra_wiserep.csv
│   ├── spectra_wiserep.png
│   ├── spectrum_*.ascii
│   └── spectrum_*.dat
└── tardis/
    ├── tardis_spectrum_<target>.dat
    └── tardis_config_<target>.yml
```

批量分析输出保存在 `output/analysis_pipeline/`：

- `spectra_summary.csv` 或 `<RUN_TAG>_spectra_summary.csv`
- `line_diagnostics_raw.csv` 或 `<RUN_TAG>_line_diagnostics_raw.csv`
- `line_diagnostics_qc.csv` 或 `<RUN_TAG>_line_diagnostics_qc.csv`
- `blackbody_temperature.csv` 或 `<RUN_TAG>_blackbody_temperature.csv`
- `host_environment_lines.csv` 或 `<RUN_TAG>_host_environment_lines.csv`
- `host_environment_summary.csv` 或 `<RUN_TAG>_host_environment_summary.csv`
- `target_status.csv` 或 `<RUN_TAG>_target_status.csv`
- `figures/*.png`

`scripts/build_analysis_products.py` 生成无前缀的全量批处理产物。`02_spectral_analysis_pipeline.ipynb` 中 `OUTPUT_TAG=""` 时会自动用当前目标名作为 `RUN_TAG`；同一目标重跑会覆盖同一目标文件，但不会覆盖其他目标的文件。`01/03/04` 和展示图脚本会优先读取目标化产物，再回退到无前缀批处理产物。

## TARDIS 可选流程

TARDIS 不作为本项目主证据链，只用于定性比较谱线位置和整体谱形。首次运行前：

```bash
conda activate tardis
python scripts/download_tardis_atom_data.py
python scripts/download_tardis_model_resources.py
```

第一个脚本不依赖当前工作目录，会把 `~/.astropy/config/tardis_internal_config.yml` 中的 `data_dir` 写成当前 clone 的项目 `data/` 绝对路径，并在同一目录下载或复用 `kurucz_cd23_chianti_H_He_latest.h5`。如果只需要修复路径、不想联网下载，可运行 `python scripts/download_tardis_atom_data.py --configure-only`。

第二个脚本只准备模型资源，不运行 TARDIS。它会根据 `configs/tardis/model_resources.yml` 把当前 TARDIS package 自带的 Ia CSVY 分层模型和格式样例复制到 `data/tardis_models/`，并生成 `data/tardis_models/model_resources_index.csv`。

然后使用 `notebooks/03_tardis_modeling_optional.ipynb`。该 notebook 会从本地 FITS 和 02 的 `*_target_status.csv`、`*_spectra_summary.csv`、`*_line_diagnostics_qc.csv` 等产物估计第一版 `z/type/velocity/time_explosion/luminosity`；红移默认来自 TNS public catalog，并随 02 的 summary/status 产物传递。它会生成 `configs/tardis/<target>.yml`，并在 `RUN_TARDIS=True` 时运行模拟。旧版归档 notebook 只作追溯，不是复现依赖。当前安装的是 TARDIS v2 dev，API 与网上很多 v1 示例不同；关键差异见 `AGENTS.md`。

`configs/acceleration.json` 中的 `tardis` 段会自动叠加到新生成的 `configs/tardis/<target>.yml`，例如 `montecarlo.nthreads`、`no_of_packets`、`iterations`、`last_no_of_packets`、`no_of_virtual_packets`、`spectrum.num` 和 integrated spectrum 的 `compute/points`。这一步只改 YAML，不会安装或修改 `tardis` conda 环境。

当前批量调参入口为：

```bash
conda activate tardis
python scripts/run_tardis_tuning.py --target SN2026KID --run-label analytic_refine --max-candidates 16
```

常用选项：

- `--adopt-best`：把本轮最佳候选复制到 `configs/tardis/<TARGET>.yml` 和 `output/<TARGET>/tardis/`。
- `--run-label <name>`：把探索性结果写到 `output/tardis_tuning/<TARGET>__<name>/`，避免覆盖原 adopted 搜索目录。
- `--include-model-resources`：把 `data/tardis_models/ia/*.csvy` 追加为 Ia 候选。
- `--model-resource-only`：只跑 CSVY model-resource 候选。

截至本次调参，Ia CSVY resources 可通过 `csvy_model` 写入合法的 TARDIS 候选配置并运行；CSVY 文件本身是模型资源，不是可单独执行的 run config。它们生成的 virtual/real packet 光谱噪声较大，SN2026FVX 与 SN2026JLM 的评分和目视效果均未优于原来的 W7-like analytic 模型。SN2026KID 的 quick refinement 曾得到较低分数，但 final packet profile 复跑没有保持优势，因此最终 adopted TARDIS 结果仍以 `report/tardis_report.md` 中的 adopted 表为准。

## 注意事项

- 不要提交 `.env`、`data/`、`output/` 或真实凭证。
- 自动谱线测量只适合作为第一版结果；正式引用速度、pEW 或 FWHM 前，应检查 `line_diagnostics_qc.csv` 或 `<RUN_TAG>_line_diagnostics_qc.csv` 中的 `qc_flag`，并人工确认 `check` 项。
- `ppt/` 是英文最终展示；中文 notebook 和 README 是为了方便组内复现与写作。
- 如果修改 notebook 结构，直接编辑对应 `.ipynb`，并同步更新 README、`AGENTS.md` 和 `notebooks/README.md` 里的说明。

## 未完成与后续建议

当前版本已经把观测准备、公开数据整理、批量光谱诊断、报告图和英文 slides 的骨架打通，但还不是最终科学结论。后续最该补的是人工确认和解释层面的工作。

| 优先级 | 状态 | 后续工作 | 说明 |
|---|---|---|---|
| 高 | 未完成 | 人工检查 `qc_flag=check` 的谱线测量 | 自动 pipeline 已输出速度、pEW、FWHM，但 `check` 项可能受噪声、天光残差、线混合或局部连续谱影响。正式报告里只应引用人工确认后的数值。 |
| 高 | 未完成 | 为每个目标确定最终采用的类型、红移和相位 | 当前 `target_status.csv` / `<RUN_TAG>_target_status.csv` 是第一版综合表。需要结合 TNS、DASH/Superfit、谱线识别和光变曲线，确定报告中的最终值。 |
| 高 | 未完成 | 替换 slides/report 中的 `TBD by group` 分工占位 | 需要填入真实组员姓名和贡献。 |
| 中 | 部分完成 | 宿主星系/环境诊断 | 已有 `host_environment_lines.csv` 和 `host_environment_summary.csv`，但这些是窄线/指数级别的粗略指标。若要讨论消光或宿主环境，需要检查谱线拟合、通量定标和 Balmer decrement 的可靠性。 |
| 中 | 部分完成 | TARDIS 建模 | `03_tardis_modeling_optional.ipynb` 与 `scripts/run_tardis_tuning.py` 已能从当前项目产物生成配置并可选运行模拟；`data/tardis_models/` 已支持 Ia CSVY resources。但当前仍不是自动物理拟合器，只能辅助 line ID 和谱形解释，不应给出强的抛射物质量、丰度或爆炸能量约束。 |
| 中 | 待完善 | 把人工确认后的最终科学表单独固化 | 建议新增一个人工维护的 `output/analysis_pipeline/final_adopted_measurements.csv` 或同名 notebook 表格，明确哪些数值进入最终报告。 |
| 低 | 待完善 | 生成逐条谱线局部检查图 | 可以为 `line_diagnostics_qc.csv` 的每一行自动画局部窗口，标出连续谱、吸收谷、pEW 区间和采用/拒绝理由，方便审稿式检查。 |
| 低 | 待完善 | 让 README 和 `AGENTS.md` 持续同步 | README 给人看，`AGENTS.md` 给 AI/自动化看。后续如果新增脚本、改 notebook 结构或改变主流程，两边都要更新。 |

建议的最小收尾顺序：

1. 运行 `python scripts/build_analysis_products.py` 刷新 `output/analysis_pipeline/`。
2. 打开 `notebooks/02_spectral_analysis_pipeline.ipynb`，逐个检查 `qc_flag=check` 的谱线。
3. 把最终采用值整理成一张手工确认表，用于 `04_project_report.ipynb` 和 `ppt/main.tex`。
4. 填入真实小组分工，并重新编译英文 slides。
