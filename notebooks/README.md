# Notebook 入口

当前项目主流程使用下面 4 个 notebook：

| Notebook | 用途 |
|---|---|
| `01_data_collection_and_observing.ipynb` | 目标元数据、观测准备和已有产物盘点；使用 `astro_env`。 |
| `02_spectral_analysis_pipeline.ipynb` | 主光谱分析 pipeline，生成可复现表格和报告用图；使用 `astro_env`。红移默认采用 TNS 公共目录数据，只在“单条谱线局部检查图”里保留本地吸收线微调功能；`CHECK_LINE_KEY=None` 时可以用 `CHECK_LINE_INDEX` 选择第几条关键线。 |
| `03_tardis_modeling_optional.ipynb` | 可选 TARDIS 配置/模拟，只作谱线识别和谱形解释辅助；真正运行模拟时使用 `tardis`。 |
| `04_project_report.ipynb` | P2Rp2 风格报告 notebook，汇总图表、解释和结论；使用 `astro_env`。 |

旧版探索 notebook 保留在 `legacy/`，用于追溯早期尝试，不再作为正式流程入口。

这四个顶层 notebook 现在都直接手工维护，不再依赖生成脚本。

主环境以 `../envs/environment_astro_env.yml` 为准；不要再使用旧的 `requirements.txt`。Superfit、DASH 和 TARDIS YAML 的加速参数集中在 `../configs/acceleration.json`，notebook helper 会自动读取它。
