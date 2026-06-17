# 光谱分析交接报告

本文档面向下一位负责整理科学结论的同学。它不是给老师提交的正文，而是说明当前 `report/` 目录里哪些结果已经可用、每个源可以支持怎样的结论、哪些地方需要谨慎表述。给老师看的数据处理章节见 `report.md`；TARDIS 辅助模拟的详细记录见 `tardis_report.md`。

当前 `report/` 目录已经包含本报告引用的 CSV、PNG、TARDIS 配置和模拟谱。复制整个 `report/` 文件夹到其他位置后，Markdown 中的相对链接仍可查看。

## 1. 当前结果状态

本项目的基础数据处理和一维光谱诊断已经完成，可以进入科学解释和结论写作阶段。核心结果来自新版 `notebooks/02_spectral_analysis_pipeline.ipynb` 重新执行后的 `final5` 产物，并已复制到 `report/assets/` 下。

当前最终采用的是保守版线表：

- 红移不再手动测量，统一采用 TNS/catalog 红移。
- 吸收线中心不再用高斯拟合，统一采用平滑、局部归一化后的吸收最低点。
- pEW 和 FWHM 采用非参数定义，不再从高斯模型参数换算。
- 只有人工检查后可靠的谱线进入 `adopt`；有明显混线、缺红移或局部窗口不稳定的测量保留为 `check`。

最终统计：

| target | type | z | spectra | adopted/check | adopted lines | conclusion strength |
|---|---|---:|---:|---:|---|---|
| SN2026FVX | SN Ia | 0.004846 | 4 | 7/1 | CaIIHK, SiII6355 | 强：最适合写速度演化 |
| SN2026JLM | SN Ia | 0.016738 | 3 | 5/1 | CaIIHK, SiII6355 | 强：可与 SN2026FVX 对比 |
| SN2026KID | SN II | 0.0017 | 3 | 3/0 | FeII5169 | 中：只适合给速度量级 |
| SN2026KIE | SN Ic | 0.00424 | 1 | 3/0 | CaIIHK, CaIINIR, OI7774 | 中：单历元，不能写演化 |
| SN2026LMP | SN IIb | no TNS z | 1 | 0/8 | none | 弱：只能定性描述 |

## 2. 应优先使用的材料

### 2.1 主数据表

科学结论优先从这些表取数：

- `assets/data/target_status.csv`：目标类型、红移、光谱数量、相位范围、采用线数量。
- `assets/data/spectra_summary.csv`：每条光谱的观测时间、相位、波长覆盖和文件来源。
- `assets/data/key_line_summary.csv`：最终采用的 18 条关键谱线测量，是写速度、pEW、FWHM、line depth 的主表。
- `assets/data/line_diagnostics_qc.csv`：完整 QC 表，包含 adopted 和 check 行，适合追踪为什么某些线没有进入最终结论。
- `assets/data/line_diagnostics_check.csv`：所有未采用但保留检查的候选线，尤其是 SN2026LMP 和被降权的线。

辅助表只能作为背景材料：

- `assets/data/blackbody_temperature.csv`：黑体颜色温度 proxy。可用于描述 Ia 连续谱变红的趋势，但不要作为严格温度测量。
- `assets/data/host_environment_lines.csv` 和 `assets/data/host_environment_summary.csv`：宿主窄线指数。没有严格流量定标，不适合推金属丰度、SFR 或消光。
- `assets/data/superfit_top_matches.csv` 和 `assets/data/local_template_classification_targets.csv`：分类辅助材料。正式分类仍应结合 TNS 和肉眼谱线识别。

### 2.2 主图

建议最终科学结论至少引用：

- `assets/figures/target_status_table.png`
- `assets/figures/final5_line_velocity_evolution.png`
- `assets/figures/final5_pew_evolution.png`
- `assets/figures/SN2026FVX_line_diagnostics_grid.png`
- `assets/figures/SN2026JLM_line_diagnostics_grid.png`
- `assets/figures/SN2026KID_line_diagnostics_grid.png`
- `assets/figures/SN2026KIE_line_diagnostics_grid.png`
- `assets/figures/SN2026LMP_line_diagnostics_grid.png`

如果需要展示每个目标的整体谱形，可用：

- `assets/figures/spectral_sequence_SN2026FVX.png`
- `assets/figures/spectral_sequence_SN2026JLM.png`
- `assets/figures/spectral_sequence_SN2026KID.png`
- `assets/figures/spectral_sequence_SN2026KIE.png`
- `assets/figures/spectral_sequence_SN2026LMP.png`

如果要解释人工检查过程，可用：

- `assets/figures/real_measurement_demo_SiII6355_SN2026JLM.png`
- `assets/figures/real_qc_check_vs_adopt_comparison.png`
- `assets/figures/real_qc_problem_example_SN2026LMP_FeII5169.png`

### 2.3 TARDIS 材料

TARDIS 只建议作为定性辅助，不要作为主结论的物理反演证据。可引用材料：

- `assets/tardis/data/tardis_best_summary.csv`
- `assets/tardis/figures/tardis_comparison_SN2026FVX.png`
- `assets/tardis/figures/tardis_comparison_SN2026JLM.png`
- `assets/tardis/figures/tardis_comparison_SN2026KID.png`
- `assets/tardis/figures/tardis_comparison_SN2026KIE.png`

TARDIS 可支持的表述是“某类简化模型能在主要谱线位置上给出定性一致的谱形”，不能支持“精确测得丰度、抛射物质量、爆炸能量或光度”的说法。

## 3. 方法边界

正式结论中建议把方法说清楚，但不需要展开到 `report.md` 那么长。核心算法如下。

观测谱用 TNS 红移转到静止系：

$$
\lambda_{\rm rest} = \frac{\lambda_{\rm obs}}{1 + z_{\rm TNS}} .
$$

每条线截取局部窗口，用 Savitzky-Golay 平滑后的谱和窗口两侧中位数定义局部连续谱：

$$
f_{\rm norm}(\lambda)=\frac{f_{\rm smooth}(\lambda)}{f_{\rm cont}(\lambda)} .
$$

吸收中心取归一化谱最低点：

$$
\lambda_{\rm min}=\arg\min f_{\rm norm}(\lambda) .
$$

速度定义为蓝移速度：

$$
v = c\frac{\lambda_0-\lambda_{\rm min}}{\lambda_0} .
$$

线深和 pEW 分别为：

$$
d = 1-f_{\rm norm}(\lambda_{\rm min}),
\qquad
{\rm pEW}=\int_{\lambda_1}^{\lambda_2}\max[1-f_{\rm norm}(\lambda),0]\,d\lambda .
$$

FWHM 使用半深度位置的左右交点：

$$
f_{1/2}=1-\frac{d}{2},
\qquad
{\rm FWHM}=\lambda_{\rm R}-\lambda_{\rm L}.
$$

误差棒是形式统计误差：速度误差来自最低点定位不确定度，pEW 误差来自局部归一化残差传播，FWHM 误差来自半深度交点附近的采样级估计。它们没有包含系统误差，例如红移误差、波长定标误差、连续谱窗口选择、线混合和大气/仪器响应。

## 4. 每个目标的结论建议

### 4.1 SN2026FVX

SN2026FVX 是当前样本中最适合写科学结论的目标。它有 4 条光谱，时间覆盖从发现后约 1.7 天到 51.6 天，Ia 关键线 Ca II H&K 和 Si II 6355 均有多历元测量。

可写结论：

- SN2026FVX 的光谱演化与 SN Ia 一致，主要依据是 Si II 6355 和 Ca II H&K 的宽吸收特征。
- Si II 6355 速度从约 14550 km/s 下降到约 8440 km/s，显示典型的膨胀外层向低速内层退行的趋势。
- Ca II H&K 速度从约 16250 km/s 下降到约 8740 km/s，也支持类似的速度演化。
- 由于 2026-03-26 的 Ca II H&K 自动最低点过窄，该历元保留为 `check`，不要把它用于演化拟合。

建议引用：

- `assets/figures/spectral_sequence_SN2026FVX.png`
- `assets/figures/SN2026FVX_line_diagnostics_grid.png`
- `assets/figures/final5_line_velocity_evolution.png`
- `assets/tardis/figures/tardis_comparison_SN2026FVX.png`，如果需要 TARDIS 辅助说明。

不要写：

- 不要重新引入 Si II 5972 作为最终采用线；它对局部窗口和 Si II 6355 宽翼污染敏感。
- 不要把 TARDIS 的 `ia_standard` 参数解释成真实丰度测量。

### 4.2 SN2026JLM

SN2026JLM 也是较可靠的 SN Ia 目标，但观测相位更晚、时间跨度更短。它适合和 SN2026FVX 做对比：SN2026FVX 展现更长时间的速度下降，SN2026JLM 的 Si II 6355 在当前相位范围内较稳定。

可写结论：

- SN2026JLM 的 Si II 6355 速度约为 11200--11400 km/s，在 14.5--26.6 天范围内变化不明显。
- Ca II H&K 有两个 adopted 点，从约 16020 km/s 到 11530 km/s，但中间历元为 `check`，因此不要做精细速度梯度拟合。
- 与 SN2026FVX 相比，SN2026JLM 的 Ia 识别同样可靠，但演化基线较短。

建议引用：

- `assets/figures/spectral_sequence_SN2026JLM.png`
- `assets/figures/SN2026JLM_line_diagnostics_grid.png`
- `assets/figures/final5_line_velocity_evolution.png`
- `assets/tardis/figures/tardis_comparison_SN2026JLM.png`，如果需要 TARDIS 辅助说明。

不要写：

- 不要声称 SN2026JLM 的 Si II 速度有显著单调下降；当前三点几乎持平。
- 不要把 `ia_si_rich` TARDIS preset 解读为真实硅丰度偏高。

### 4.3 SN2026KID

SN2026KID 是 SN II。当前自动测量中只采用 Fe II 5169 作为速度量级指标。氢线虽然对 Type II 识别重要，但 Halpha/Hbeta 的局部最低点容易受 P-Cygni 发射结构和连续谱影响，因此没有进入 adopted 速度表。

可写结论：

- SN2026KID 的谱形和 TNS 分类支持 Type II 解释。
- Fe II 5169 给出的速度量级约为 7700--11500 km/s，但误差较大、线深较浅。
- 当前数据不足以给出严格的单调速度演化，只能说速度处于典型早期 core-collapse SN 的数量级。
- TARDIS 的 `ii_h_rich` 简化模型能较好复现 Halpha P-Cygni 区域，可作为 Type II 光谱形态的定性支持。

建议引用：

- `assets/figures/spectral_sequence_SN2026KID.png`
- `assets/figures/SN2026KID_line_diagnostics_grid.png`
- `assets/tardis/figures/tardis_comparison_SN2026KID.png`

不要写：

- 不要把 Halpha/Hbeta 自动测量作为 adopted 速度。
- 不要对 Fe II 5169 三个点做严格速度下降率。

### 4.4 SN2026KIE

SN2026KIE 是单历元 SN Ic / stripped-envelope 目标。它可以支持分类和速度量级判断，但不能支持时间演化结论。

可写结论：

- Ca II H&K、O I 7774 和 Ca II NIR 的吸收结构支持 stripped-envelope SN 的解释。
- Ca II H&K 和 O I 7774 给出约 1.1e4 km/s 的速度量级。
- Ca II NIR 给出约 1.38e4 km/s，但线深浅、pEW 误差大，应只作为辅助信息。
- TARDIS 的 Ibc 简化模型可部分复现 O I 7774 和 Ca II NIR 区域，但 Ca II NIR 偏深，说明模型只是定性辅助。

建议引用：

- `assets/figures/spectral_sequence_SN2026KIE.png`
- `assets/figures/SN2026KIE_line_diagnostics_grid.png`
- `assets/tardis/figures/tardis_comparison_SN2026KIE.png`

不要写：

- 不要声称 SN2026KIE 有速度演化趋势；只有一个历元。
- 不要因为 TARDIS 最佳 preset 为 `ib_he_rich` 就把分类改成 SN Ib。

### 4.5 SN2026LMP

SN2026LMP 是当前样本中最不适合做定量结论的目标。它缺少 TNS 红移，因此静止系校正和速度测量都没有可靠基准。

可写结论：

- SN2026LMP 可作为一个缺红移、低置信度候选目标保留在样本说明中。
- 粗分类接近 SN IIb，但当前只适合做定性谱形检查。
- 所有候选线都保留为 `check`，不进入速度、pEW、FWHM 的科学结论。

建议引用：

- `assets/figures/spectral_sequence_SN2026LMP.png`
- `assets/figures/SN2026LMP_line_diagnostics_grid.png`
- `assets/figures/real_qc_problem_example_SN2026LMP_FeII5169.png`

不要写：

- 不要给 SN2026LMP 报速度、pEW 或 FWHM 结论。
- 不要把缺红移下的线位对应当作分类强证据。

## 5. 可直接发展的科学叙事

建议把最终结论组织成三层。

第一层是样本层面：本项目获得了 5 个近邻超新星的一维光谱诊断，其中 4 个有 TNS 红移并可进行定量线速度测量，1 个因缺红移只保留定性检查。样本覆盖 SN Ia、SN II、SN Ic 和可能的 SN IIb。

第二层是 Ia 对比：SN2026FVX 和 SN2026JLM 都有明确的 Si II 6355 和 Ca II H&K 特征。SN2026FVX 的多历元速度下降最清楚，SN2026JLM 在较晚相位范围内 Si II 速度更稳定。这个对比可以作为本项目最主要的科学结果。

第三层是 core-collapse / stripped-envelope 个例：SN2026KID 的 Fe II 5169 只给出早期 SN II 的速度量级；SN2026KIE 的 O I 和 Ca II 线支持 stripped-envelope 分类但缺少演化信息；SN2026LMP 需要可靠红移或更多光谱才能进入定量讨论。

可用的英文结论骨架如下，后续可以按课程要求改写：

> The two Type Ia supernovae show robust Si II 6355 and Ca II H&K absorptions. SN2026FVX exhibits a clear decline in the Si II 6355 velocity from about 14,500 km/s to about 8,400 km/s over the observed baseline, while SN2026JLM remains near 11,300 km/s over a shorter and later phase range. The Type II object SN2026KID provides only a rough Fe II 5169 velocity scale because the line is shallow and noisy. SN2026KIE is consistent with a stripped-envelope SN from its O I and Ca II absorptions, but the single epoch prevents an evolutionary interpretation. SN2026LMP is excluded from quantitative velocity measurements because no reliable TNS redshift is available.

## 6. 不建议写进最终科学结论的内容

- 不要说本项目重新完成了二维光谱归约；当前分析从已归约一维 FITS 光谱开始。
- 不要说红移来自手动测量；当前最终版本采用 TNS/catalog 红移。
- 不要说吸收线由高斯拟合得到；当前最终版本是最低点法。
- 不要把表中形式误差当成完整误差预算；系统误差没有完全包含。
- 不要对 SN2026LMP 做任何定量速度、pEW 或 FWHM 结论。
- 不要把黑体颜色温度写成严格物理温度；它只是连续谱形状 proxy。
- 不要把宿主窄线指数解释成金属丰度、SFR 或消光测量。
- 不要把 TARDIS 的 luminosity、abundance preset、density profile 当成真实物理参数反演。

## 7. 下一位同学需要补的工作

1. 确认数据来源和基础归约来源：这些 BFOSC 一维 FITS 是谁归约的、是否已做响应校正、是否可称为相对流量定标谱。
2. 给方法部分补参考文献：TNS、Superfit/模板分类、pEW/谱线速度常规定义、TARDIS（如果要写）。
3. 决定最终是否把 TARDIS 写进主报告：如果篇幅有限，建议只保留一两句定性说明，详细图放附录或不放。
4. 用 `key_line_summary.csv` 重新核对最终表格数字，避免手动复制时四舍五入错误。
5. 如果要增加新的测量或改线表，建议用新的输出 tag，不要覆盖 `final5`，这样现有报告仍可追溯。

## 8. 快速核查清单

交最终稿前建议逐项确认：

- `SN2026LMP` 是否仍被排除在定量结果之外。
- `SN2026KID` 是否只采用 `FeII5169` 作为速度量级。
- `SN2026FVX` 和 `SN2026JLM` 是否只采用 `CaIIHK` 与 `SiII6355`。
- 图中的误差棒是否解释为形式统计误差。
- TARDIS 是否被描述为 qualitative support，而不是 physical fit。
- `report/` 文件夹单独复制后，所有 Markdown 图片和 CSV 链接仍能打开。
