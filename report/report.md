# 3. Data reduction and analyses（中文初稿，作者/贡献待填）

本节只写本项目中我负责的数据处理与光谱分析部分。当前 `report/` 目录已经包含本节引用的 CSV 和 PNG，复制整个 `report/` 文件夹到其他位置后仍可直接查看。

## 3.1 数据来源与基础归约状态

本次分析使用的是项目 `data/SN*/` 下的一维 BFOSC 光谱 FITS 文件，共 5 个目标、12 条光谱。它们已经是基础归约后的一维光谱，因此本工作没有从二维谱重新做 bias/flat、宇宙线剔除、二维波长定标、天空扣除和一维抽取。正式报告中建议补充一句数据提供方和归约来源；若这些光谱来自 TA 或合作组已归约数据，应明确说明“本节从已归约的一维光谱开始分析”。标准长缝光谱归约流程一般包括本底/平场校正、坏点和宇宙线处理、弧灯波长定标、天空背景扣除、一维抽取，以及标准星或仪器响应给出的相对流量校正；这里可在最终英文稿中加入合适文献引用。

目标类型、发现日期和红移优先来自 TNS public catalog。本项目不再手动测红移；当前 TNS 缓存没有 maximum-light 或 peak-date 字段，因此本文中的相位均为距发现日天数，不是相对最大光相位。对有 TNS 红移的目标，将观测波长按

$$
\lambda_{\rm rest} = \frac{\lambda_{\rm obs}}{1+z_{\rm TNS}}
$$

转到静止系。SN2026LMP 在 TNS 中缺少可靠红移，因此只做定性线型检查，不采用任何定量速度或 pEW 结论。

## 3.2 可复现流程

主环境为 `astro_env`。本节结果由新版 `notebooks/02_spectral_analysis_pipeline.ipynb` 重新执行得到；notebook 当前配置为处理 5 个目标、保存 `final5_*` 产物。可复现命令如下：

```bash
conda activate astro_env
jupyter nbconvert --to notebook --execute --inplace notebooks/02_spectral_analysis_pipeline.ipynb
```

在无法启动 Jupyter kernel 的受限环境中，也可以用同一套模块入口重算批处理产物：

```bash
conda activate astro_env
python scripts/build_analysis_products.py
```

本次最终报告使用 notebook 保存的 `output/analysis_pipeline/final5_*.csv`，并已复制为 `report/assets/data/*.csv`。主要文件为：

- `assets/data/spectra_summary.csv`：每条 FITS 光谱的观测日期、距发现日相位、波长覆盖、仪器信息。
- `assets/data/target_status.csv`：目标级汇总，含类型、红移、光谱数、采用谱线和 QC 数量。
- `assets/data/line_diagnostics_qc.csv`：所有测量线的完整 QC 表。
- `assets/data/key_line_summary.csv`：本节最终采用的 18 条关键谱线测量。
- `assets/data/line_diagnostics_check.csv`：人工检查后仍不进入定量结论的 10 条候选线。

## 3.3 类型、红移和最终线表选择

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

## 3.4 谱线测量算法

每条待测吸收线在静止系中截取局部窗口，先用 Savitzky-Golay 平滑压低像素噪声，再用窗口两侧的中位数点定义局部线性连续谱。归一化谱为

$$
f_{\rm norm}(\lambda)=\frac{f_{\rm smooth}(\lambda)}{f_{\rm cont}(\lambda)}.
$$

根据老师建议，本次不再用高斯轮廓拟合吸收线中心，而是在归一化谱中直接取吸收最低点：

$$
\lambda_{\rm min}=\arg\min f_{\rm norm}(\lambda).
$$

速度和线深定义为

$$
v=c\frac{\lambda_0-\lambda_{\rm min}}{\lambda_0}, \qquad
d=1-f_{\rm norm}(\lambda_{\rm min}),
$$

其中 $\lambda_0$ 为实验室静止波长。FWHM 也不再由高斯 $\sigma$ 换算，而是在半深度水平

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

## 3.5 人工校对和最终采用规则

自动测量后，我逐个查看了每个目标的局部诊断图。图中灰线为原始局部谱，黑线为平滑谱，橙线为局部连续谱，红虚线为实验室静止波长，绿虚线为本次采用的吸收最低点，紫色填充只表示 pEW 积分区域，不是高斯模型。旧版的紫色高斯拟合曲线已经移除。

人工校对主要做了三类处理：

1. 删除/降权容易混线的谱线：Si II 5972 的 pEW 容易混入 Si II 6355，因此从最终采用表中移除。
2. 删除不稳的氢线自动速度：SN2026KID 的 Halpha/Hbeta 局部最低点受发射峰、噪声和连续谱影响，不作为 adopted 速度。
3. 缺红移目标不做定量采用：SN2026LMP 即使有候选线，也因为缺少 TNS 红移全部标为 `check`。

最终局部诊断图如下：

![SN2026FVX line diagnostics](assets/figures/SN2026FVX_line_diagnostics_grid.png)

![SN2026JLM line diagnostics](assets/figures/SN2026JLM_line_diagnostics_grid.png)

![SN2026KID line diagnostics](assets/figures/SN2026KID_line_diagnostics_grid.png)

![SN2026KIE line diagnostics](assets/figures/SN2026KIE_line_diagnostics_grid.png)

![SN2026LMP line diagnostics](assets/figures/SN2026LMP_line_diagnostics_grid.png)

## 3.6 最终关键谱线测量结果

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

## 3.7 演化图和辅助诊断

下面的演化图只画最终采用表中的测量结果。误差棒缺失或很大时，表示最低点定位、局部噪声或连续谱窗口带来的不确定性较大。

![Line velocity evolution](assets/figures/final5_line_velocity_evolution.png)

![pEW evolution](assets/figures/final5_pew_evolution.png)

![FWHM evolution](assets/figures/final5_fwhm_evolution.png)

![Line depth evolution](assets/figures/final5_line_depth_evolution.png)

黑体颜色温度只作为连续谱形状 proxy。新版产物会用 `T_qc_flag` 将非 Ia 或缺红移目标降为 `check`。SN2026KID、SN2026KIE 和 SN2026LMP 的蓝端形状/红移条件不够可靠，因此温度不作为主要科学结论。

![Blackbody color temperature](assets/figures/final5_blackbody_temperature.png)

宿主/环境窄线只按局部线指数和 S/N 粗测，不能替代严格流量定标后的金属丰度、消光或星形成率诊断。新版 summary 同时记录 detected row 数和唯一窄线种类数，写报告时优先使用唯一线种类数。

![Host-line detections](assets/figures/final5_host_line_detections.png)

## 3.8 本节结果的限制

1. 本节从已归约一维光谱开始，未重新做二维光谱归约；最终稿需要补充数据提供方和归约来源。
2. 谱线速度依赖 TNS 红移。缺红移的 SN2026LMP 不做定量采用。
3. 最低点法比高斯拟合更直接，但仍依赖窗口、平滑尺度和连续谱定义；宽线混合处的 pEW 系统误差可能明显大于表中形式误差。
4. 本节只给出稀疏光谱下的经验诊断，不等价于辐射输运物理拟合；TARDIS 结果应作为定性辅助而非主证据。
