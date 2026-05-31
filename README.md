---
注意: 请AI编辑此文件时尽可能适合人看，给AI看的主要是`AGENTS.md`
---

# SN 观测流水线 (Supernova Observing Pipeline)

从 [TNS (Transient Name Server)](https://www.wis-tns.org) 获取超新星目标数据，计算观测夜间可见性窗口，并生成观测报告。

## 目录结构

```
sn-pipline/
├── configs/
│   ├── sn_parameter.json      # 观测参数配置文件
│   └── tardis/                # TARDIS 模拟配置模板
├── src/
│   ├── pipeline.py            # 核心流水线（数据获取、观测窗计算、报告生成）
│   ├── finder.py              # 找星图生成（astroquery SkyView + matplotlib）
│   ├── lasair.py              # Lasair 光变曲线获取
│   ├── wiserep.py             # WISeREP 光谱数据获取
│   ├── fetch_aux_data.py      # 辅助数据获取入口（光变曲线 + 光谱）
│   ├── config.py              # 配置加载工具
│   ├── coordinates.py         # 坐标格式转换（度 ↔ 时角）
│   ├── observability.py       # 可观测性计算
│   ├── target.py              # Target 数据模型
│   ├── time_utils.py          # 时间/天文计算（儒略日、太阳位置等）
│   ├── tns.py                 # TNS API 集成
│   └── utils.py               # 工具函数（HTTP、认证、CSV 等）
├── scripts/
│   ├── fetch_target_params.py       # 目标参数获取入口
│   ├── fetch_aux_data.py            # 辅助数据获取入口（光变曲线 + 光谱）
│   └── download_tardis_atom_data.py # 下载 TARDIS 原子数据
├── output/                    # 输出目录（每个目标一个子目录）
├── data/                      # TNS 公共目录缓存
├── envs/                      # Conda 环境定义文件
│   └── environment_astro_env.yml
├── requirements.txt           # Python 依赖（备选安装方式）
└── .env                       # TNS 用户凭证（不上传 git）
```

## 环境准备

### 1. 一键创建环境（新电脑/其他人使用）

```bash
conda env create -f envs/environment_astro_env.yml
```

创建后每次使用只需 `conda activate astro_env`。一个环境涵盖所有功能（主流水线 + 光变曲线 + 光谱 + astrodash 分类）。

### 环境说明

| 环境 | Python | 用途 |
|------|--------|------|
| `astro_env` | 3.10 | 主流水线 — TNS 查询、观测窗、找星图、光变曲线、光谱下载/绘图、astrodash 分类 |
| `tardis` | 3.13 | TARDIS 蒙特卡洛辐射传输模拟 — 超新星光谱建模与对比分析 |

**注意**：astrodash 要求 `numpy<1.24` + `tensorflow<2.16`，环境文件已锁定版本，无需手动操作。如需纯 `pip` 安装（不推荐），可配合 `numpy<1.24` 使用 `requirements.txt`。

> **迁移到新电脑的注意事项**：必须用 `conda env create -f envs/environment_astro_env.yml` 一键重建环境，不能手动装包。pip 的 tensorflow 依赖约束 `numpy>=1.23.5,<2.0.0` 会在安装时把 conda 的 numpy 从 1.23.5 升到 1.26.x，导致 astrodash 内部 `np.array([[np.zeros(n),...]])` 报错。解决方法是将 `numpy==1.23.5` 也写进 YAML 的 pip 依赖中。
>
> 验证命令：`D:\Anaconda\envs\astro_env\python.exe -c "import numpy; print(numpy.__version__)"` 应输出 `1.23.5`。

```bash
# 主流水线
conda activate astro_env

# 光谱分类
conda activate astro_env

# tardis 模拟
conda activate tardis
```

如需新环境安装依赖：

```bash
pip install -r requirements.txt
```

所需依赖（`astro_env` 环境）：
- `astropy>=5.0` — 天文坐标与可见性计算
- `numpy<1.24` — 数值计算
- `astroquery>=0.4` — 天文在线数据查询（SkyView 找星图）
- `matplotlib>=3.5` — 找星图绘制
- `tensorflow<2.16` — astrodash 分类
- ...

### 2. 凭证配置

编辑 `.env` 文件，填入你的 TNS 账户信息与Lasair API token：

```env
TNS_USER_ID=你的ID
TNS_USER_NAME=你的用户名
LASAIR_API_TOKEN=你的Lasair API Token
```

可在 TNS 网站 → My Account → User-Agent specification 获取。

**注意**：当前使用 **user 模式**（无需 bot API key）。通过下载 TNS 公共目录 CSV + 抓取目标页面获取数据。

## 使用方法

### 1. 配置观测参数

编辑 `configs/sn_parameter.json`:

```json
{
  "observing": {
    "target": "SN2026kid",        // 目标名称（支持 SN/AT 前缀）
    "date": "2026-05-08",         // 观测日期
    "site_lat": 40.0,             // 观测站纬度
    "site_lon": 116.3,            // 观测站经度（正值=东经）
    "site_elevation_m": 50.0,     // 海拔 (m)
    "tz_offset": 8.0,             // 时区偏移（UTC+8 = 北京时间）
    "min_alt": 30.0,              // 最低高度角 (deg, 对应 airmass≤2)
    "sun_alt_limit": -12.0,       // 太阳高度角上限 (天文昏影)
    "time_step_minutes": 10       // 时间分辨率 (分钟)
  },
  "tns": {
    "enabled": true,              // 是否查询 TNS
    "download_files": true        // 是否下载 TNS 找星图
  },
  "output": {
    "out_dir": "output",          // 输出目录
    "finder_fov_arcmin": 10.0     // Aladin Lite 视场 (角分)
  }
}
```

所有参数均可调，无需修改代码。

### 2. 运行流水线

```bash
conda activate astro_env
python scripts/fetch_target_params.py
```

或直接以模块方式运行：

```bash
python -m src.pipeline
```

### 3. 查看输出

输出按目标组织在 `output/<目标名>/` 中：

```
output/SN2026fov/
├── sn_report_2026-05-08_SN2026fov.txt             # 观测报告
├── finder_TNS_tns_2026fov_atrep_*.jpg             # TNS 找星图
├── finder_astroquery_DSS2_Red.png                 # astroquery 找星图
├── lightcurve/
│   ├── lightcurve_lasair.csv                      # Lasair 光变曲线数据
│   └── lightcurve_lasair.png                      # 光变曲线图
└── spectrum/
    ├── spectra_wiserep.csv                        # WISeREP 光谱元数据
    ├── spectra_wiserep.png                        # 光谱图
    ├── spectrum_*.ascii                           # 原始光谱数据文件
    └── spectrum_*.dat                             # 清洁 2 列数据（供 astrodash 等工具）
```

### 4. 获取辅助数据（光变曲线 + 光谱）

```bash
python scripts/fetch_aux_data.py
# 或
python -m src.fetch_aux_data
```

- **Lasair** — 使用 `.env` 中的 `LASAIR_API_TOKEN`，通过 ZTF ID 从 Lasair API 获取光变曲线
- **WISeREP** — 从 WISeREP 搜索公共光谱数据，下载光谱文件并绘图
- 配置中可分别开关：`lasair.lasair_enabled` 和 `wiserep.wiserep_enabled`

## 输出报告内容

| 项目 | 说明 | 示例 |
|------|------|------|
| **Target** | 目标名称与发现日期 | `SN 2026kid (4/22)` |
| **Type** | 暂现源类型 | `SN II`, `Ia`, `CV`, `Unclassified` |
| **RA / Dec** | 赤经赤纬（时角 + 度） | `15:15:57.23 / +56:18:32.1` |
| **Mag** | 最新测光星等（含日期和滤光片） | `16.2 Clear- (4/23)` |
| **Window** | 目标高度角 ≥ 30° 的时间窗口 | `20:30 - 03:50 (+1d) CST` |
| **Max Altitude** | 当晚最大高度角及时间 | `73.7 deg at 00:20 CST` |
| **Finding Chart** | 找星图（TNS 下载 + astroquery DSS2 绘制 + Aladin Lite 链接） | 本地 PNG 文件 + 在线星图 URL |

## TNS 数据获取方式

本流水线使用 **user 模式** 访问 TNS：

1. **公共目录 CSV** — 下载 `tns_public_objects.csv.zip`（缓存于 `data/`，24 小时内复用），从中提取目标基本参数（名称、类型、坐标、发现日期、红移、星等）
2. **目标页面抓取** — 访问 TNS 目标页面，提取最新测光数据和找星图链接

## Jupyter Notebook 使用

### 精简后的 notebook pipeline

顶层 `notebooks/` 现在只保留 4 个稳定入口；原来的探索 notebook 已移到 `notebooks/legacy/`，用于追溯早期尝试，不再作为主流程入口。

| Notebook | 用途 | 主要输出 |
|---|---|---|
| `01_data_collection_and_observing.ipynb` | 目标获取、观测准备、TNS/Lasair/WISeREP 输出盘点 | 读取现有 `output/` 和 `configs/sn_parameter.json` |
| `02_spectral_analysis_pipeline.ipynb` | 统一光谱分析 pipeline：FITS 读取、速度、pEW/FWHM、黑体温度、宿主线指标和质检标记 | `output/analysis_pipeline/*.csv` 与 `output/analysis_pipeline/figures/*.png` |
| `03_tardis_modeling_optional.ipynb` | 可选 TARDIS 定性比较；只用于 line-ID/谱形解释，不作为强物理约束 | 读取 `output/<target>/tardis/` |
| `04_project_report.ipynb` | P2Rp2 风格报告 notebook，汇总科学问题、数据、分析、解释和结论 | 直接展示 pipeline 图表 |

命令行可复现主分析输出：

```bash
conda activate astro_env
python scripts/build_analysis_products.py
python scripts/build_presentation_figures.py
```

LaTeX 幻灯片在 `ppt/`：

```bash
cd ppt
latexmk -pdf main.tex
```

已编译 PDF 位于 `ppt/slides.pdf`（同时保留 `ppt/build/main.pdf`）。

### 旧版探索 notebook（已归档）

以下 notebook 已移动到 `notebooks/legacy/`。它们保留了早期手动步骤和课堂练习，但正式汇报和复现请使用上面的 4 个精简入口。

#### 光谱后处理 (`legacy/spectral_processing.ipynb`)

1. **读取和查看光谱** — 从 `output/` 加载 `.dat` 光谱文件并绘图
2. **astrodash 分类** — 使用 DASH 深度学习模型进行超新星光谱自动分类
3. **膨胀速度测量** — 基于特征吸收线的蓝移计算超新星抛射物速度

```bash
conda activate astro_env
python scripts/fetch_target_params.py   # 获取 TNS 数据、生成观测报告
python scripts/fetch_aux_data.py        # 下载光变曲线和光谱数据（生成 .dat 文件）
jupyter notebook notebooks/spectral_processing.ipynb
```

#### TARDIS 光谱模拟 (`legacy/tardis_simulation.ipynb`)

基于观测光谱和 DASH 分类结果运行 TARDIS 辐射传输模拟，并与实际观测对比：

1. **加载观测光谱** — 从 `output/` 读取 WISeREP 光谱
2. **构建 TARDIS 配置** — 根据红移、类型（Ia/II/Ibc）、膨胀速度估算光度、爆发时间，自动生成 YAML
3. **运行模拟** — 蒙特卡洛辐射传输，输出合成光谱
4. **对比分析** — 模拟 vs 观测光谱叠加对比 + 残差图
5. **保存结果** — 输出到 `output/{target}/tardis/`

```bash
conda activate tardis
python scripts/download_tardis_atom_data.py  # 首次使用：下载原子数据 (~212 MB)
jupyter notebook notebooks/tardis_simulation.ipynb
```

notebook 内切换目标只需修改 `TARGET` 变量。

## 注意事项

- `.env` 包含 TNS 凭证，**不要提交到 git**
- `output/` 和 `data/` 已被 `.gitignore` 排除
- TNS 公共目录约 100MB，首次运行需要下载
- 观测窗口计算使用 astropy（自动退化为纯 Python 计算）

# SN 光谱数据分析进展总结

本文整理当前已经有光谱数据后完成的分析，以及此前建议的 9 类后续可做分析。状态含义：

- `[已做]`：已有可运行 notebook 或已形成自动化诊断输出。
- `[部分]`：已有框架或示例，但还需要按目标手动调参、补充物理约束或改成批处理。
- `[待做]`：当前还没有专门 notebook。

## 已经完成的基础工作

| 状态 | 工作 | 目的 | 对应 notebook |
|---|---|---|---|
| `[已做]` | 检查 `.fits` 文件内容 | 识别学长给的数据是 1D 光谱、2D 光谱图像还是表格，并查看 header、HDU、波长轴和数据维度 | [`fits_inspection.ipynb`](fits_inspection.ipynb) |
| `[已做]` | 2D 光谱的基础提取流程 | 从长缝二维光谱中做背景扣除、抽取 1D 光谱、建立波长解，并用强发射线估计红移 | [`spectral_reduction.ipynb`](spectral_reduction.ipynb) |
| `[已做]` | 读取和可视化 1D 光谱 | 读取 `data/<target>/` 或 pipeline 产出的光谱文件，画出观测谱 | [`spectral_processing.ipynb`](spectral_processing.ipynb), [`spectral_superfit.ipynb`](spectral_superfit.ipynb), [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| `[已做]` | DASH 分类、红移和模板匹配 | 用 Astrodash 给出 SN 类型、模板相位、红移和最佳模板叠加图 | [`spectral_processing.ipynb`](spectral_processing.ipynb) |
| `[已做]` | Superfit/NGSF 模板拟合 | 用 Superfit 作为 DASH 之外的独立模板拟合结果，交叉检查类型、红移和相位 | [`spectral_superfit.ipynb`](spectral_superfit.ipynb) |
| `[已做]` | 抛射物速度估算 | 根据 SN 类型选择典型谱线，在去红移光谱中找吸收谷并计算膨胀速度 | [`spectral_processing.ipynb`](spectral_processing.ipynb), [`spectral_superfit.ipynb`](spectral_superfit.ipynb), [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| `[已做]` | 连续谱归一化 | 用 `specutils` 和 Chebyshev 多项式拟合经验连续谱，再用原始光谱除以连续谱 | [`spectral_normalization.ipynb`](spectral_normalization.ipynb) |
| `[部分]` | TARDIS 辐射转移模拟 | 根据类型、红移、相位、速度和亮度生成 TARDIS 配置，模拟光谱并和观测谱比较 | [`tardis_simulation.ipynb`](tardis_simulation.ipynb) |

## 此前建议的 9 类后续分析

| # | 状态 | 可做分析 | 当前实现 | 对应 notebook |
|---:|---|---|---|---|
| 1 | `[已做]` | 多历元光谱演化 | 批量读取 `data/SN*/SN*_bfosc_*.fits`，按目标分组画 rest-frame 多历元光谱序列；可看谱线形状、连续谱颜色和演化趋势 | [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| 2 | `[已做]` | 多谱线速度演化 | 对 Ia/II/Ib/Ic 常用谱线自动选择搜索窗口，测吸收谷蓝移速度，并画速度随时间变化 | [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| 3 | `[已做]` | 谱线强度：pseudo-equivalent width | 对吸收线局部拟合线性连续谱，计算 pEW；适合比较 Si II、Hα、He I、Ca II 等线强演化 | [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| 4 | `[已做]` | 谱线宽度和线深 | 自动输出 FWHM、线深、吸收谷位置，用于判断谱线是否变宽、是否有高速成分或混合特征 | [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| 5 | `[已做]` | 连续谱黑体温度粗估 | 用 Planck 黑体函数 `A * B_lambda(T)` 拟合连续谱，输出颜色温度 `T_bb`；当前结果应视为粗略温度，不是严格 photospheric temperature | [`spectral_diagnostics.ipynb`](spectral_diagnostics.ipynb) |
| 6 | `[已做]` | 连续谱归一化与谱线测量准备 | 用经验多项式连续谱做归一化，便于后续量等效宽度、谱线深度和局部轮廓 | [`spectral_normalization.ipynb`](spectral_normalization.ipynb) |
| 7 | `[已做]` | 分类/红移/相位的交叉验证 | 用 DASH 和 Superfit 两套独立模板方法比较 SN 类型、红移和模板相位；若两者冲突，需要人工检查谱线识别和宿主红移 | [`spectral_processing.ipynb`](spectral_processing.ipynb), [`spectral_superfit.ipynb`](spectral_superfit.ipynb) |
| 8 | `[部分]` | 物理模型拟合 | TARDIS 可以把观测谱和辐射转移模型比较，调节 luminosity、epoch、velocity range、abundance、plasma 设置；目前是单目标手动调参框架，还不是自动拟合器 | [`tardis_simulation.ipynb`](tardis_simulation.ipynb) |
| 9 | `[部分]` | 宿主星系/消光/环境诊断 | 已在 `src/spectral_pipeline.py` 中加入窄线/Na I D 指标、host line summary 和质检提醒；这些是未定标的粗略 index，正式物理解释前仍需人工检查 | `02_spectral_analysis_pipeline.ipynb` |

## 当前自动输出

`02_spectral_analysis_pipeline.ipynb` / `scripts/build_analysis_products.py` 会把批量诊断结果写到：

- `output/analysis_pipeline/spectra_summary.csv`
- `output/analysis_pipeline/line_diagnostics_raw.csv`
- `output/analysis_pipeline/line_diagnostics_qc.csv`
- `output/analysis_pipeline/blackbody_temperature.csv`
- `output/analysis_pipeline/host_environment_lines.csv`
- `output/analysis_pipeline/host_environment_summary.csv`
- `output/analysis_pipeline/target_status.csv`

这些表格适合直接放进报告或继续画图。需要注意的是，自动谱线测量依赖目标类型、红移和搜索窗口；正式引用速度、pEW 或 FWHM 前，建议用 notebook 中的单条谱线检查图逐个确认吸收谷没有被噪声、天光残差或线混合误判。

## 还值得补的工作

优先级最高的 notebook 清理和宿主环境初步诊断已经并入统一 pipeline。下一步最值得做的是：对 `line_diagnostics_qc.csv` 中所有 `qc_flag=check` 的谱线生成逐条局部检查图，并把最终采用的速度/pEW/FWHM 手动确认后写入报告正文。
