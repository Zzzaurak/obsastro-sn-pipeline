# TARDIS 超新星光谱模拟报告

本报告基于项目当前的 TARDIS 批量调参结果整理。报告中引用的图片、配置文件、模拟谱和评分表均已复制到 `report/assets/tardis/` 下，因此 `report/` 目录可以单独打包查看。

需要强调的是，本次 TARDIS 计算用于**辅助谱线识别和定性谱形比较**，不是严格的物理参数反演。文中的 luminosity、爆炸后时间、速度范围、密度结构和丰度 preset 都是为了让一维辐射输运模型在主要谱线位置和大尺度谱形上接近观测；它们不应直接解释为精确的抛射物质量、真实丰度或爆炸能量。

## 可复现材料

### 报告引用的图片

TARDIS 对比图均位于 `assets/tardis/figures/`：

- `tardis_comparison_SN2026FVX.png`
- `tardis_comparison_SN2026JLM.png`
- `tardis_comparison_SN2026KID.png`
- `tardis_comparison_SN2026KIE.png`

图中黑线为观测光谱，橙线为 TARDIS 模拟光谱。两者均转到静止系并做 pseudo-continuum normalization。浅蓝色区域为评分时重点比较的诊断谱线窗口。

### 报告引用的数据和配置

数据和配置均位于 `assets/tardis/`：

- `assets/tardis/data/tardis_best_summary.csv`：四个目标的最终 adopted TARDIS 参数汇总。
- `assets/tardis/data/<TARGET>_best_summary.json`：每个目标最佳候选的详细记录。
- `assets/tardis/data/<TARGET>_scores.csv`：每个目标最后一轮搜索的候选评分表。
- `assets/tardis/configs/tardis_config_<TARGET>.yml`：最终 adopted TARDIS YAML 配置。
- `assets/tardis/spectra/tardis_spectrum_<TARGET>.dat`：最终 adopted TARDIS 模拟谱，二列格式为 rest-frame wavelength 与 luminosity density。
- `assets/tardis/experiments/`：本轮新增模型资源和 refinement 搜索的评分表与关键对比图；这些是检查材料，不是最终 adopted 结果。

## 模拟目标和观测谱选择

本次没有对每个历元分别建立模型，而是每颗超新星选取一条代表性光谱进行 TARDIS 定性拟合。默认选择每个目标最早的本地 BFOSC FITS 光谱，因为早期谱线通常更适合用简单的一维光球近似模型做 sanity check。

| target | adopted type | redshift | selected observed spectrum |
|---|---|---:|---|
| SN2026FVX | SN Ia | 0.004846 | `data/SN2026fvx/SN2026fvx_bfosc_20260319.fits` |
| SN2026JLM | SN Ia | 0.016738 | `data/SN2026jlm/SN2026jlm_bfosc_20260426.fits` |
| SN2026KID | SN II | 0.0017 | `data/SN2026kid/SN2026kid_bfosc_20260426.fits` |
| SN2026KIE | SN Ic / Ibc | 0.00424 | `data/SN2026kie/SN2026kie_bfosc_20260508.fits` |

观测谱按

$$
\lambda_{\rm rest} = \frac{\lambda_{\rm obs}}{1 + z}
$$

转到静止系。这里 $z$ 使用前一阶段数据处理中采用的 TNS/catalog 红移。

## TARDIS 模型与参数含义

TARDIS 是一维 Monte Carlo 辐射输运程序。本项目使用的配置是单区或简化多壳层模型：设定一个光球内边界、外层 ejecta 的速度范围、密度结构、简化丰度和目标 luminosity，然后计算通过外层物质形成的合成光谱。

本次主要调整以下参数。

### requested luminosity

YAML 中为

```yaml
supernova:
  luminosity_requested: 9.40 log_lsun
```

它表示 TARDIS 希望模型达到的总 luminosity，单位为 $\log(L/L_\odot)$。该参数会影响温度结构和 ionization 状态，因此会改变连续谱斜率和谱线强度。本报告只把它作为谱形调节参数，不把它解释为严格 bolometric luminosity。

### time_explosion

YAML 中为

```yaml
supernova:
  time_explosion: 25.7 day
```

它表示模型中的爆炸后时间。对 homologous expansion ejecta，时间会影响密度尺度和光球附近物理状态。这里的 `time_explosion` 不是由爆炸时刻精确测量得到，而是从观测相位和类型默认 rise-time 出发，再通过谱线匹配调节得到的近似值。

### velocity start / stop

YAML 中为

```yaml
model:
  structure:
    velocity:
      start: 4373.9 km/s
      stop: 13538.3 km/s
```

`start` 近似对应模型光球或内边界速度，`stop` 是外层 ejecta 的最大速度。超新星吸收线的观测中心通常相对实验室波长蓝移，因此速度范围会直接影响合成谱线的位置。若模拟吸收线整体偏蓝或偏红，首先需要检查和调整这个速度范围。

### density profile

密度结构决定不同速度层中物质分布。本次使用三类简化 profile：

- `branch85_w7`：Ia 模型常用的 W7-like 密度结构。
- `exponential`：指数型密度下降，常用于非 Ia 的定性尝试。
- `power_law`：幂律密度下降，适合测试 stripped-envelope SN 的简化外层结构。

密度 profile 对谱线宽度、吸收深度和不同速度层贡献都有影响。

### CSVY model resource

本轮新增了 `data/tardis_models/` 模型资源目录，并用 `configs/tardis/model_resources.yml` 记录来源。当前下载到本地的资源包括 TARDIS 包内置的 Ia delayed-detonation、double-detonation、deflagration、merger 类 CSVY 示例，以及 simple ASCII / CSVY 格式样例。

CSVY 模型与上面的均匀丰度 preset 不同：它把 velocity、density 和分层 abundance 放在同一个模型文件中。脚本 `scripts/run_tardis_tuning.py --include-model-resources` 可把这些 CSVY 文件作为 Ia 目标的候选模型；`--model-resource-only` 可只跑这类模型，`--run-label` 可把探索性输出写到独立目录，避免覆盖原来的 adopted tuning workspace。

### abundance preset

本次不是逐元素连续拟合，而是使用少量 preset：

- `ia_standard`
- `ia_si_rich`
- `ii_h_rich`
- `ii_balmer_strong`
- `ic_oxygen_rich`
- `ic_ca_rich`
- `ib_he_rich`

这些 preset 是均匀丰度近似，用于增强或削弱 H、He、O、Si、Ca 等谱线。它们只能说明“哪类元素组合在当前简化模型下更容易产生相似谱形”，不能直接当作真实丰度测量。例如 SN2026KIE 的最佳 preset 为 `ib_he_rich`，这不等价于把该源重新分类为 Ib；它只说明这个 preset 在当前单区模型中对 O/Ca 区域的形状更有利。

## 搜索与评分方法

脚本 `scripts/run_tardis_tuning.py` 会对每个目标生成一组候选 TARDIS YAML，运行 TARDIS，保存合成谱，再与选定观测谱比较。候选参数来自以下组合：

- luminosity offsets
- epoch offsets
- velocity scales
- density profile choices
- abundance preset choices
- analytic plasma/interaction physics preset choices
- optional CSVY model resources under `data/tardis_models/`

新版 `scripts/run_tardis_tuning.py` 可用 `--physics-preset current|literature|both` 控制 analytic 候选的 plasma 假设。`current` 保留原来的 LTE baseline；`literature` 使用 `nebular` ionization、`dilute-lte` excitation、`dilute-blackbody` radiative rates 和 `macroatom` line interaction，更接近 TARDIS 光球近似示例中常见的非 LTE 稀释辐射场设定。这个选项只用于比较谱形稳健性，不应解读为真实电离状态反演。CSVY model resources 仍保留资源模型自身的 plasma override。

评分不是直接比较原始 flux，而是先做以下处理：

1. 观测谱转到静止系。
2. TARDIS 模拟谱按 wavelength 排序。
3. 观测谱和模拟谱分别做平滑。
4. 使用宽窗口中位数估计 pseudo-continuum。
5. 将两条谱都归一化到局部连续谱附近。
6. 在全局重叠波段和诊断谱线窗口内计算差异。

总分越小表示当前评分函数下越接近。评分由以下部分组成：

$$
S =
{\rm RMSE}_{\rm broad}
+ 1.5\,{\rm RMSE}_{\rm line}
+ 0.75\,P_{\rm corr}
+ \frac{\Delta\lambda_{\rm min}}{300}
$$

其中：

- ${\rm RMSE}_{\rm broad}$ 是重叠波段的大尺度归一化残差；
- ${\rm RMSE}_{\rm line}$ 是诊断谱线窗口内的残差；
- $P_{\rm corr}=1-r$ 是相关系数惩罚项；
- $\Delta\lambda_{\rm min}$ 是谱线窗口内观测和模拟吸收谷位置的平均偏差，单位 Angstrom。

Ia 目标重点比较 Ca II H&K、Si II 5972、Si II 6355 和 Ca II NIR。Type II 目标重点比较 Hbeta、Fe II 5169 和 Halpha。Ibc 目标重点比较 Ca II H&K、Fe II 5169、O I 7774 和 Ca II NIR。

## 为什么早期结果是竖线状

最初的对比图中，TARDIS 模拟谱呈现大量竖线状尖峰，原因是提取了 `spectrum_real_packets`。TARDIS 是 Monte Carlo 程序，real packets 是实际逃逸 photon packets 的统计结果。如果 packet 数有限，直接画 real-packet spectrum 会看到很多离散、很窄的尖峰，看起来像竖线，而不是平滑连续谱。

后续脚本改为优先提取：

```python
sim.spectrum_solver.spectrum_integrated
```

`spectrum_integrated` 更适合用于连续谱形状和宽谱线比较。最终 adopted 图中橙色 TARDIS 曲线就是 integrated spectrum，并额外经过与观测谱一致的平滑和 pseudo-continuum normalization。

本轮测试 CSVY model resources 时发现，有些 CSVY 模型的 `spectrum_integrated` 在当前 TARDIS v2026.5.31 下只返回 `nan`，但 `spectrum_virtual_packets` 和 `spectrum_real_packets` 有有效数据。因此脚本现在会按 integrated、virtual、real 的顺序选择第一个包含足够 finite 点的谱。这个 fallback 可以让 CSVY 资源参与评分，但 virtual/real packet 光谱仍会比 integrated spectrum 更有 Monte Carlo 噪声，所以没有把这些 noisy CSVY 结果直接作为最终图。

## 最终 adopted 参数

| target | candidate | score | log L/Lsun | time (d) | velocity range (km/s) | density | abundance preset |
|---|---|---:|---:|---:|---|---|---|
| SN2026FVX | SN2026FVX_c000 | 1.037 | 9.40 | 25.7 | 4374--13538 | branch85_w7 | ia_standard |
| SN2026JLM | SN2026JLM_c001 | 1.753 | 9.40 | 32.5 | 5019--15534 | branch85_w7 | ia_si_rich |
| SN2026KID | SN2026KID_c002 | 1.136 | 8.80 | 25.0 | 5764--12488 | exponential | ii_h_rich |
| SN2026KIE | SN2026KIE_c000 | 1.287 | 9.00 | 31.3 | 8055--17452 | power_law | ib_he_rich |

从数值评分看，SN2026FVX、SN2026KID 和 SN2026KIE 的最终分数在约 1.0--1.3，SN2026JLM 的分数约 1.75。评分只用于同一套归一化和窗口下的模型筛选，不应跨不同超新星过度比较物理好坏。

## 新增资源与二次调参检查

本轮先检查了 `data/tardis_models/` 下载产物：7 个资源文件均已写入，4 个 Ia CSVY 文件都能通过 `csvy_model` 写入合法的 TARDIS 候选配置并运行。CSVY 文件本身是模型资源，不是可单独执行的 run config。随后进行了三类二次搜索：

| target | search | best score | previous adopted score | decision |
|---|---|---:|---:|---|
| SN2026FVX | Ia CSVY resources | 2.219 | 1.037 | 不采用；图像噪声和窄峰明显，差于 W7-like analytic 模型 |
| SN2026JLM | Ia CSVY resources + luminosity check | 1.952 | 1.753 | 不采用；分数和视觉均不优于 `ia_si_rich` analytic 模型 |
| SN2026KID | analytic quick refinement | 0.964 | 1.136 | quick 模型提示可能改进，但 final packet profile 复跑后为 1.219，不采用 |
| SN2026KIE | analytic refinement | 1.371 | 1.351 | 不采用；与旧图形状接近但分数略差 |

相关评分表和检查图已复制到：

- `assets/tardis/experiments/data/SN2026FVX_csvy_scores.csv`
- `assets/tardis/experiments/data/SN2026JLM_csvy_lum_scores.csv`
- `assets/tardis/experiments/data/SN2026KID_analytic_refine_scores.csv`
- `assets/tardis/experiments/data/SN2026KID_analytic_refine_final_scores.csv`
- `assets/tardis/experiments/data/SN2026KIE_analytic_refine_scores.csv`

这次二次调参的结论是：新下载的 Ia CSVY resources 对这两颗 Ia 目标没有带来更好的定性拟合；SN2026KID 的 quick refinement 虽然在 Halpha 区域看起来更接近，但高 packet/iteration 的 final 验证未保持优势，因此最终 adopted 表保持不变。

## 文献 preset 与 adopted-seed 细网格检查

在按文献修正光谱测量算法后，本轮又新增了 `--seed-source adopted`，直接围绕当前 adopted TARDIS 模型做小步细网格，而不是重新从 02 的自动 context seed 开始。局部搜索锁定当前 adopted 的 density/abundance，只扫描较小的 epoch 与 velocity perturbation，并用 `--physics-preset both` 同时比较当前 LTE baseline 和 `nebular + dilute-lte + macroatom` 文献型 photospheric plasma preset。

quick 搜索使用较低 packet 数做初筛；只有 quick score 低于旧 adopted score 的候选才做 final-packet 复跑。结果如下：

| target | focused quick best | quick score | final score | previous adopted score | decision |
|---|---|---:|---:|---:|---|
| SN2026FVX | SN2026FVX_c008 | 1.611 | -- | 1.037 | 不采用；局部搜索明显差于旧 W7-like 模型，literature preset 对 Ia 还出现不稳定极高分 |
| SN2026JLM | SN2026JLM_c012 | 1.342 | 1.811 | 1.753 | 不采用；quick 明显改善，但 final-packet 复跑未保持优势 |
| SN2026KID | SN2026KID_c012 | 1.032 | 1.263 | 1.136 | 不采用；quick 改善未通过 final 验证 |
| SN2026KIE | SN2026KIE_c014 | 1.292 | 1.287 | 1.351 | 采用；final score 保持改善，目视检查未发现主要谱线窗口退化 |

这轮检查说明，`literature_photospheric` plasma preset 不是普遍改进；四个目标的最佳 quick/final 候选仍来自 current LTE baseline。真正可采用的变化只有 SN2026KIE：将速度范围从 7671--16621 km/s 调整到 8055--17452 km/s 后，6200--6400 Angstrom 附近的过深吸收略减弱，Ca II NIR 区域残差也略小。该改进幅度不大，仍应作为定性模型，而不是精确物理反演。

本轮 focused-search 评分表和检查图已复制到：

- `assets/tardis/experiments/data/SN2026FVX_focused_lit_scores.csv`
- `assets/tardis/experiments/data/SN2026JLM_focused_lit_scores.csv`
- `assets/tardis/experiments/data/SN2026KID_focused_lit_scores.csv`
- `assets/tardis/experiments/data/SN2026KIE_focused_lit_scores.csv`
- `assets/tardis/experiments/data/SN2026JLM_focused_lit_final_scores.csv`
- `assets/tardis/experiments/data/SN2026KID_focused_lit_final_scores.csv`
- `assets/tardis/experiments/data/SN2026KIE_focused_lit_final_scores.csv`

## 分源模拟结果

### SN2026FVX

SN2026FVX 采用 `branch85_w7` 密度结构和 `ia_standard` 丰度 preset。最终模型参数为

- `log_lsun = 9.40`
- `time_explosion = 25.7 day`
- `v_start = 4373.9 km/s`
- `v_stop = 13538.3 km/s`

![SN2026FVX TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026FVX.png)

该模型在 Si II 6355 主吸收附近与观测谱基本对齐，是本次 Ia 模拟中最有用的部分。蓝端 Ca II H&K 附近仍有明显结构差异，Ca II NIR 区域模拟吸收偏深。整体上，SN2026FVX 的 TARDIS 模型可用于说明 Ia 关键谱线识别，尤其是 Si II 6355，但不适合用来给出精确物理参数。

### SN2026JLM

SN2026JLM 采用 `branch85_w7` 密度结构和 `ia_si_rich` 丰度 preset。最终模型参数为

- `log_lsun = 9.40`
- `time_explosion = 32.5 day`
- `v_start = 5018.6 km/s`
- `v_stop = 15533.7 km/s`

![SN2026JLM TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026JLM.png)

该模型在 Si II 6355 附近有对应吸收结构，但模拟吸收中心略偏蓝，Ca II NIR 区域偏深。蓝端谱形和观测也不完全一致。这个结果支持 SN Ia 谱线识别，但拟合质量不如 SN2026FVX 稳定。`ia_si_rich` 只表示提高 Si 相关特征后评分略优，不应理解为真实硅丰度测量。

### SN2026KID

SN2026KID 采用 `exponential` 密度结构和 `ii_h_rich` 丰度 preset。最终模型参数为

- `log_lsun = 8.80`
- `time_explosion = 25.0 day`
- `v_start = 5763.8 km/s`
- `v_stop = 12488.3 km/s`

![SN2026KID TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026KID.png)

SN2026KID 是四个目标中 TARDIS 对比最稳定的一个。Halpha 区域的 P-Cygni 形状、吸收位置和发射峰位置均与观测有较好对应。Hbeta 和 Fe II 5169 区域没有严重错位，但观测蓝端噪声和归一化不稳定仍会影响判断。该模型可作为 Type II 光谱中 Halpha 形成和速度范围的定性支持。

### SN2026KIE

SN2026KIE 采用 `power_law` 密度结构和 `ib_he_rich` 丰度 preset。最终模型参数为

- `log_lsun = 9.00`
- `time_explosion = 31.3 day`
- `v_start = 8054.9 km/s`
- `v_stop = 17452.3 km/s`

![SN2026KIE TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026KIE.png)

该模型在 O I 7774 和 Ca II NIR 区域产生了对应吸收结构。与上一版 adopted 模型相比，速度范围略向高速度移动后，约 6200--6400 Angstrom 附近的过深吸收稍有缓解，Ca II NIR 区域的残差略小，但 Ca II NIR 仍明显偏深。由于 SN2026KIE 只有一条光谱，且 stripped-envelope SN 的谱线混合较复杂，本结果只能说明简化 Ibc 模型能部分复现 O/Ca 区域，不应把 `ib_he_rich` preset 直接解释为重新分类为 Ib。

## 与数据处理结果的关系

前一份数据处理报告主要给出红移、类型、谱线速度、pEW、FWHM、黑体颜色温度和 QC 状态。TARDIS 模拟在本项目中扮演的是补充角色：

- 检查主要谱线识别是否合理；
- 检查观测谱线位置是否能由合理 ejecta 速度范围产生；
- 为报告或展示提供“观测谱 vs 辐射输运模型”的定性对比图；
- 帮助说明某些目标的谱形复杂性和模型局限。

因此，最终科学结论仍应优先依赖前一阶段的观测谱线测量表和 QC 结果。TARDIS 结果适合作为支持性图像和解释，不适合作为独立的物理拟合结论。

## 局限性

1. 每颗超新星只拟合一条代表性光谱，没有做多历元联合模型。
2. 丰度为均匀 preset，不是逐元素、逐壳层的真实丰度反演。
3. luminosity 和 time_explosion 是调谱形参数，不是严格从光变曲线约束得到。
4. 评分函数依赖 pseudo-continuum normalization 和线窗选择，不能替代人工光谱判断。
5. SN2026KIE 的 Ibc 谱线混合较复杂，目前模型只能部分复现 O/Ca 区域。
6. TARDIS 输出图优先使用 integrated spectrum；CSVY resource 结果需要 fallback 到 virtual/real packets 时，噪声会明显增加，不适合直接作为最终 adopted 图。
7. 连续跑多个 CSVY TARDIS 模型可能出现内存累计，长 grid 曾被系统以 exit 137 杀掉。后续如果继续大规模搜索，应使用更小 batch 或一候选一进程的隔离执行。

## 总结

本次 TARDIS 批量模拟为四个目标提供了可复现的定性辐射输运对比图和最终 adopted YAML 配置。二次调参测试了新下载的 Ia CSVY model resources、非 Ia analytic refinement，以及围绕 adopted seed 的文献 plasma preset 细网格。通过 final 验证并被采用的新增改进只有 SN2026KIE，score 从 1.351 降到 1.287；SN2026JLM 和 SN2026KID 的 quick 改善没有在 final-packet 复跑中保持。SN2026KID 的 Type II Halpha 匹配仍是四个目标中最稳定的；SN2026FVX 的 Ia Si II 6355 匹配较好；SN2026JLM 和 SN2026KIE 只能作为定性支持，仍存在明显谱线强度或位置差异。

最终可用于报告展示的图像为 `assets/tardis/figures/tardis_comparison_*.png`。若后续要做更严格物理解释，应结合光变曲线约束、更多历元光谱、分层丰度模型和更系统的 TARDIS 参数搜索。
