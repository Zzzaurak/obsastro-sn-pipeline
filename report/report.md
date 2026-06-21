# 3. Data reduction and analyses（中文初稿，作者/贡献待填）

本节只写本项目中我负责的数据处理与光谱分析部分。当前 `report/` 目录已经包含本节引用的 CSV 和 PNG，复制整个 `report/` 文件夹到其他位置后仍可直接查看。

## 3.1 数据来源与基础归约状态

本次分析使用的是一维 BFOSC 光谱 FITS 文件，共 5 个目标、12 条光谱。它们是黄睿丰学长交付给我们的数据，已经是基础归约后的一维光谱，因此本工作没有从二维谱重新做 bias/flat、宇宙线剔除、二维波长定标、天空扣除和一维抽取，这些工作是学长处理好的。其中每颗超新星的最后一条光谱是我们与5月8日使用兴隆216拍摄的，其余是学长给的别的时间的数据。因此我们也缺少相应的误差。
<!-- 正式报告中建议补充一句数据提供方和归约来源；若这些光谱来自 TA 或合作组已归约数据，应明确说明“本节从已归约的一维光谱开始分析”。标准长缝光谱归约流程一般包括本底/平场校正、坏点和宇宙线处理、弧灯波长定标、天空背景扣除、一维抽取，以及标准星或仪器响应给出的相对流量校正；这里可在最终英文稿中加入合适文献引用。 -->

目标类型、发现日期和红移优先来自 TNS 的公开数据集。本项目不再手动测红移；当前 TNS 数据似乎没有 maximum light 或 peak date ，因此本文中的相位均为距发现日天数，不是相对最大光相位。对有 TNS 红移的目标，将观测波长按

$$
\lambda_{\rm rest} = \frac{\lambda_{\rm obs}}{1+z_{\rm TNS}}
$$

转到静止系。SN2026LMP 在 TNS 中缺少可靠红移，因此只做定性线型检查，不采用任何定量速度或 pEW 结论。

## 3.2 类型、红移和最终线表选择

类型判断以 Superfit/本地模板匹配和 TNS 分类为主要依据。为了避免弱线、混合线和缺红移目标进入定量结论，本次重新校对后采用更保守的线表：

- SN Ia（SN2026FVX、SN2026JLM）：采用 Ca II H&K 和 Si II 6355。Si II 5972 对局部窗口非常敏感，容易被 Si II 6355 的宽吸收污染 pEW，因此本次不列入最终采用表。
- SN II（SN2026KID）：只采用 Fe II 5169 作为速度量级指标。Halpha/Hbeta 在本批光谱中受发射结构、噪声和局部连续谱影响，不作为自动 adopted 速度。
- SN Ic（SN2026KIE）：单历元采用 Ca II H&K、Ca II NIR 和 O I 7774，但 Ca II NIR 较浅，解释时只作为辅助。
- SN2026LMP：粗分类接近 SN IIb，但缺少 TNS 红移，因此所有候选线保留为 `check`，不进入定量速度表。

| Target | Type | z | Spectra | Phase range (d) | Adopt/check | Adopted lines |
|---|---|---:|---:|---:|---:|---|
| SN2026FVX | SN Ia | 0.004846 | 4 | 1.7--51.6 | 7/1 | CaIIHK, SiII6355 |
| SN2026JLM | SN Ia | 0.016738 | 3 | 14.5--26.6 | 5/1 | CaIIHK, SiII6355 |
| SN2026KID | SN II | 0.0017 | 3 | 4.0--16.1 | 3/0 | FeII5169 |
| SN2026KIE | SN Ic | 0.00424 | 1 | 16.3--16.3 | 3/0 | CaIIHK, CaIINIR, OI7774 |
| SN2026LMP | SN IIb | — | 1 | — | 0/8 | none |

![Target status summary](assets/figures/target_status_table.png)

## 3.3 谱线测量算法

每条待测吸收线在静止系中截取局部窗口，先用 Savitzky-Golay 平滑压低像素噪声，再用窗口两侧的中位数点定义局部线性连续谱。归一化谱为

$$
f_{\rm norm}(\lambda)=\frac{f_{\rm smooth}(\lambda)}{f_{\rm cont}(\lambda)}.
$$

根据杨轶老师的建议，本次不再用高斯轮廓拟合吸收线中心，而是在归一化谱中直接取吸收最低点：

$$
\lambda_{\rm min}=\arg\min f_{\rm norm}(\lambda).
$$

速度和线深定义为

$$
v=c\frac{\lambda_0-\lambda_{\rm min}}{\lambda_0}, \qquad
d=1-f_{\rm norm}(\lambda_{\rm min}),
$$

其中 $\lambda_0$ 为实验室静止波长。FWHM 是在半深度水平

$$
f_{1/2}=1-\frac{d}{2}
$$

左右寻找线性交点 $\lambda_{\rm L}$ 和 $\lambda_{\rm R}$，定义

$$
{\rm FWHM}=\lambda_{\rm R}-\lambda_{\rm L}.
$$

pEW 直接积分归一化谱中低于连续谱的正面积：

$$
{\rm pEW}=\int_{\lambda_1}^{\lambda_2}
\max\left[1-f_{\rm norm}(\lambda),0\right]\,d\lambda.
$$

误差棒是形式统计误差。速度误差由最低点波长不确定度传播；最低点波长不确定度由局部残差噪声和像素采样共同估计。pEW 误差由局部归一化残差噪声在吸收积分区内传播。FWHM 误差是半深度交点附近的采样级估计。新版 pipeline 还会在重算产物中输出 `velocity_sys_kms`、`pEW_sys_A`、`FWHM_sys_A`，记录改变平滑窗口和连续谱边缘比例后的经验散布。这些仍不是完整误差预算，没有完全包含 TNS 红移误差、波长定标系统误差、线混合和大气/仪器响应。

## 3.4 人工校对和最终采用规则

自动测量后，我们逐个查看了每个目标的局部诊断图。图中灰线为原始局部谱，黑线为平滑谱，橙线为局部连续谱，红虚线为实验室静止波长，绿虚线为本次采用的吸收最低点，紫色填充只表示 pEW 积分区域，不是高斯模型。

人工校对主要做了三类处理：

1. 删除/降权容易混线的谱线：Si II 5972 的 pEW 容易混入 Si II 6355，因此从最终采用表中移除。
2. 删除不稳的氢线自动速度：SN2026KID 的 Halpha/Hbeta 局部最低点受发射峰、噪声和连续谱影响，不作为 adopted 速度。
3. 缺红移目标不做定量采用：SN2026LMP 即使有候选线，也因为缺少 TNS 红移全部标为 `check`。

最终 `line_diagnostics_qc.csv` 共有 28 条候选测量，其中 18 条为 `adopt`、10 条为 `check`。我们查看了目标级局部诊断图：自动最低点明显不可靠的窄谷已经由 QC 留在 `check`，包括 SN2026FVX 2026-03-26 的 Ca II H&K、SN2026JLM 2026-05-04 的 Ca II H&K，以及 SN2026LMP 的所有缺红移候选线。

具体来说，SN2026KID 的 Fe II 5169 三个 adopted 点线深较浅，SN2026KIE 的 Ca II NIR pEW 误差大于测量值，SN2026FVX/SN2026JLM 早期 Ca II H&K 的 pEW 也受连续谱选择影响较大。这些点仍可作为速度量级或 line ID 支持，但不适合对 pEW 或 FWHM 做强物理解释。若后续要得到更严格的最终表，可以在 QC 中加入 pEW 信噪比或 systematics 阈值，把这些弱 adopted 行降为 `check`；代价是 Ia 早期 Ca II 和 core-collapse 速度覆盖会更少。

最终局部诊断图如下：

![SN2026FVX line diagnostics](assets/figures/SN2026FVX_line_diagnostics_grid.png)

![SN2026JLM line diagnostics](assets/figures/SN2026JLM_line_diagnostics_grid.png)

![SN2026KID line diagnostics](assets/figures/SN2026KID_line_diagnostics_grid.png)

![SN2026KIE line diagnostics](assets/figures/SN2026KIE_line_diagnostics_grid.png)

![SN2026LMP line diagnostics](assets/figures/SN2026LMP_line_diagnostics_grid.png)

## 3.5 最终关键谱线测量结果

### SN2026FVX

SN2026FVX 是本样本中时间覆盖最长的 SN Ia。Si II 6355 速度从约 $1.45\times10^4$ km/s 下降到约 $8.4\times10^3$ km/s；Ca II H&K 也从约 $1.63\times10^4$ km/s 降到约 $8.7\times10^3$ km/s。2026-03-26 的 Ca II H&K 自动最低点过窄，被保留为 `check` 而不采用。

| Phase (d) | Line | v (km/s) | pEW (A) | FWHM (A) | Depth |
|---:|---|---:|---:|---:|---:|
| 1.7 | CaIIHK | 16252 ± 1467 | 9.4 ± 15.9 | 45.2 ± 5.5 | 0.18 |
| 20.7 | CaIIHK | 9736 ± 418 | 7.9 ± 3.2 | 36.7 ± 5.5 | 0.11 |
| 51.6 | CaIIHK | 8742 ± 732 | 29.8 ± 8.2 | 47.0 ± 5.5 | 0.44 |
| 1.7 | SiII6355 | 14550 ± 843 | 12.4 ± 14.6 | 60.4 ± 5.5 | 0.13 |
| 8.7 | SiII6355 | 11004 ± 324 | 62.5 ± 1.9 | 126.0 ± 5.5 | 0.47 |
| 20.7 | SiII6355 | 10237 ± 324 | 85.9 ± 1.6 | 128.6 ± 5.5 | 0.65 |
| 51.6 | SiII6355 | 8441 ± 324 | 23.3 ± 3.7 | 58.4 ± 5.5 | 0.26 |

### SN2026JLM

SN2026JLM 也是 SN Ia，但观测集中在发现后约 14.5--26.6 天。Si II 6355 速度保持在约 $1.1\times10^4$ km/s，变化不明显；Ca II H&K 的两个采用点显示较高到较低速度的变化，但中间历元被标为 `check`。

| Phase (d) | Line | v (km/s) | pEW (A) | FWHM (A) | Depth |
|---:|---|---:|---:|---:|---:|
| 14.5 | CaIIHK | 16017 ± 413 | 12.8 ± 20.2 | 24.7 ± 5.4 | 0.24 |
| 26.6 | CaIIHK | 11526 ± 310 | 22.8 ± 17.2 | 51.7 ± 5.4 | 0.32 |
| 14.5 | SiII6355 | 11410 ± 768 | 74.9 ± 10.1 | 138.2 ± 5.4 | 0.57 |
| 22.5 | SiII6355 | 11242 ± 832 | 88.3 ± 8.0 | 146.3 ± 5.4 | 0.59 |
| 26.6 | SiII6355 | 11337 ± 512 | 77.4 ± 8.7 | 139.6 ± 5.4 | 0.55 |

### SN2026KID

SN2026KID 为 SN II。最终只采用 Fe II 5169 作为膨胀速度量级指标。三个历元的速度为约 $0.8$--$1.1\times10^4$ km/s，但误差较大、线深较浅，因此不应过度解释为严格单调演化。

| Phase (d) | Line | v (km/s) | pEW (A) | FWHM (A) | Depth |
|---:|---|---:|---:|---:|---:|
| 4.0 | FeII5169 | 11454 ± 2714 | 11.5 ± 7.8 | 85.7 ± 5.5 | 0.07 |
| 5.0 | FeII5169 | 7723 ± 1358 | 11.5 ± 8.5 | 49.3 ± 5.5 | 0.10 |
| 16.1 | FeII5169 | 8795 ± 718 | 18.7 ± 7.7 | 46.8 ± 5.5 | 0.16 |

### SN2026KIE

SN2026KIE 为单历元 SN Ic。Ca II H&K 和 O I 7774 给出约 $1.1\times10^4$ km/s 的速度量级，支持 stripped-envelope SN 的解释。Ca II NIR 线深较浅且 pEW 误差大，只作为辅助。

| Phase (d) | Line | v (km/s) | pEW (A) | FWHM (A) | Depth |
|---:|---|---:|---:|---:|---:|
| 16.3 | CaIIHK | 11287 ± 418 | 29.6 ± 12.4 | 25.6 ± 5.5 | 0.42 |
| 16.3 | CaIINIR | 13799 ± 672 | 6.1 ± 15.2 | 43.3 ± 5.5 | 0.09 |
| 16.3 | OI7774 | 11184 ± 847 | 15.7 ± 13.8 | 92.1 ± 5.5 | 0.17 |

### SN2026LMP

SN2026LMP 的粗分类近似 SN IIb，但没有 TNS 红移。所有候选线都只作为定性检查，不采用速度、pEW 或 FWHM 作为科学结论。最终 CSV 中这些行保存在 `assets/data/line_diagnostics_check.csv`。

## 3.6 演化图和辅助诊断

下面的演化图会同时显示 `adopt` 和 `check` 行，用来保留人工复核痕迹；正式定量结论只引用前面表中的 `adopt` 测量。图中透明度较低或孤立的 `check` 点，尤其是 SN2026LMP 的缺红移候选线，只能作为诊断参考，不进入速度、pEW 或 FWHM 结论。误差棒缺失或很大时，表示最低点定位、局部噪声或连续谱窗口带来的不确定性较大。

![Line velocity evolution](assets/figures/final5_line_velocity_evolution.png)

![pEW evolution](assets/figures/final5_pew_evolution.png)

![FWHM evolution](assets/figures/final5_fwhm_evolution.png)

![Line depth evolution](assets/figures/final5_line_depth_evolution.png)

黑体颜色温度只作为连续谱形状 proxy。新版产物会用 `T_qc_flag` 将非 Ia 或缺红移目标降为 `check`。SN2026KID、SN2026KIE 和 SN2026LMP 的蓝端形状/红移条件不够可靠，因此温度不作为主要科学结论。

![Blackbody color temperature](assets/figures/final5_blackbody_temperature.png)

## 3.7 TARDIS 辐射输运模拟作为定性辅助分析

除了前面的经验谱线测量，我还使用 TARDIS 做了一组一维 Monte Carlo 辐射输运模拟，用来检查主要谱线识别和速度范围是否合理。这里需要明确：TARDIS 在本项目中只是辅助分析，不是主证据链，也不是严格的物理参数反演。由于本项目每颗超新星的光谱历元较少、光变曲线约束不足，模型中的 luminosity、爆炸后时间、速度边界、密度结构和丰度 preset 都是为了让合成光谱在主要谱线位置和大尺度谱形上接近观测，而不能直接解释为真实的抛射物质量、元素丰度或爆炸能量。



本次没有对每个历元分别建模，而是每颗有可靠红移和分类的超新星选取一条代表性早期光谱。四个 TARDIS 目标分别为 SN2026FVX、SN2026JLM、SN2026KID 和 SN2026KIE；SN2026LMP 因缺少可靠 TNS 红移，没有做 TARDIS 定量比较。观测谱仍按前文同样的方式除以 $(1+z)$ 转到静止系。模拟谱和观测谱都经过相同的平滑和 pseudo-continuum normalization 后比较，因此图中重点是谱线位置和相对形状，而不是绝对流量。

TARDIS 候选参数主要包括总 luminosity、爆炸后时间、速度范围、密度 profile、丰度 preset 和 plasma 设定。Ia 目标使用 `branch85_w7` 这类 W7-like 密度结构；II 和 Ibc 目标使用 `exponential` 或 `power_law` 这类简化密度结构。丰度不是逐层拟合，而是少量 uniform preset，例如 `ia_standard`、`ia_si_rich`、`ii_h_rich` 和 `ib_he_rich`。我还测试了 TARDIS 包自带的 Ia CSVY 分层模型资源，以及更接近文献光球近似的 `nebular + dilute-lte + macroatom` plasma preset。实际检查发现，这些更复杂或更“文献化”的设置并不自动给出更好的拟合；最终采用仍以 final-packet 复跑和目视检查为准。

评分函数不是比较原始 flux，而是在全局重叠波段和几个诊断谱线窗口中比较归一化谱形。总分由 broad RMSE、谱线窗口 RMSE、相关系数惩罚和吸收谷位置偏差组成，分数越低表示在当前归一化和线窗定义下越接近。Ia 目标重点比较 Ca II H&K、Si II 5972、Si II 6355 和 Ca II NIR；SN II 重点比较 Hbeta、Fe II 5169 和 Halpha；Ibc 重点比较 Ca II H&K、Fe II 5169、O I 7774 和 Ca II NIR。

最终采用的 TARDIS 参数如下：

| Target | Candidate | Score | log L/Lsun | time (d) | velocity range (km/s) | Density | Abundance preset |
|---|---|---:|---:|---:|---|---|---|
| SN2026FVX | SN2026FVX_c000 | 1.037 | 9.40 | 25.7 | 4374--13538 | branch85_w7 | ia_standard |
| SN2026JLM | SN2026JLM_c001 | 1.753 | 9.40 | 32.5 | 5019--15534 | branch85_w7 | ia_si_rich |
| SN2026KID | SN2026KID_c002 | 1.136 | 8.80 | 25.0 | 5764--12488 | exponential | ii_h_rich |
| SN2026KIE | SN2026KIE_c000 | 1.287 | 9.00 | 31.3 | 8055--17452 | power_law | ib_he_rich |

从单目标结果看，SN2026FVX 的 Ia 模型在 Si II 6355 主吸收附近与观测谱基本对齐，能支持 Ia 谱线识别；蓝端 Ca II H&K 和 Ca II NIR 仍有明显强度差异。SN2026JLM 的 Si II 6355 也有对应结构，但模拟吸收中心略偏蓝，Ca II NIR 偏深，因此只作为定性支持。SN2026KID 是四个目标中 TARDIS 对比最稳定的一个，Halpha 区域的 P-Cygni 形状和速度范围与观测有较好对应，可作为 Type II 光谱解释的 sanity check。SN2026KIE 的 Ibc 模型能部分复现 O I 7774 和 Ca II NIR 区域；最新 adopted 模型将速度范围略向高速度移动后，6200--6400 Angstrom 附近的过深吸收稍有缓解，但 Ca II NIR 仍偏深。

![SN2026FVX TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026FVX.png)

![SN2026JLM TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026JLM.png)

![SN2026KID TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026KID.png)

![SN2026KIE TARDIS comparison](assets/tardis/figures/tardis_comparison_SN2026KIE.png)

在调参过程中还出现过一个技术问题：早期图中的 TARDIS 模拟谱看起来像很多竖线，而不是连续谱。这是因为当时直接提取了 `spectrum_real_packets`；TARDIS 是 Monte Carlo 程序，real packets 在 packet 数有限时会呈现离散尖峰。后续脚本改为优先使用 `spectrum_integrated`，只有当某些 CSVY resource 模型的 integrated spectrum 为 `nan` 时才 fallback 到 virtual/real packets。因此最终采用图中的橙色曲线更适合做连续谱形状和宽谱线比较。

总体来说，TARDIS 与前面的经验谱线测量是互补关系。经验测量给出速度、pEW、FWHM 和 QC 表，是本节主要定量结果；TARDIS 用来检查这些谱线识别和速度范围是否能由合理的一维 ejecta 模型产生。最终科学结论仍应优先引用前面的 adopted line table；TARDIS 图适合作为报告中的定性辅助图。

## 3.8 本节结果的限制

1. 本节从已归约一维光谱开始，未重新做二维光谱归约，我们对其中产生的误差等细节并不清晰。
2. 谱线速度依赖 TNS 红移。缺红移的 SN2026LMP 不做定量采用。
3. 最低点法比高斯拟合更直接，但仍依赖窗口、平滑尺度和连续谱定义；宽线混合处的 pEW 系统误差可能明显大于表中形式误差。
4. TARDIS 模型只拟合每颗超新星的一条代表性光谱，丰度为简化 preset，没有进行多历元联合拟合或真实分层丰度反演。
5. 本节只给出稀疏光谱下的经验诊断和定性辐射输运检查，不等价于完整物理拟合；TARDIS 结果应作为辅助而非主证据。
