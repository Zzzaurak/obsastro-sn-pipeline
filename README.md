# SN 观测流水线 (Supernova Observing Pipeline)

从 [TNS (Transient Name Server)](https://www.wis-tns.org) 获取超新星目标数据，计算观测夜间可见性窗口，并生成观测报告。

## 目录结构

```
sn-pipline/
├── configs/
│   └── sn_parameter.json      # 观测参数配置文件
├── src/
│   ├── pipeline.py            # 核心流水线（数据获取、观测窗计算、报告生成）
│   ├── config.py              # 配置加载工具
│   ├── coordinates.py         # 坐标格式转换（度 ↔ 时角）
│   ├── observability.py       # 可观测性计算
│   ├── target.py              # Target 数据模型
│   ├── time_utils.py          # 时间/天文计算（儒略日、太阳位置等）
│   ├── tns.py                 # TNS API 集成
│   └── utils.py               # 工具函数（HTTP、认证、CSV 等）
├── scripts/
│   └── fetch_target_params.py # 目标参数获取入口脚本
├── output/                    # 输出目录（报告 + 找星图）
├── data/                      # TNS 公共目录缓存
├── requirements.txt           # Python 依赖
└── .env                       # TNS 用户凭证（不上传 git）
```

## 环境准备

### 1. Python 环境

使用 `tardis` conda 环境，已预装所需依赖：

```bash
conda activate tardis
```

如需新环境安装依赖：

```bash
pip install -r requirements.txt
```

所需依赖：
- `astropy>=5.0` — 天文坐标与可见性计算
- `numpy>=1.21` — 数值计算

### 2. TNS 凭证配置

编辑 `.env` 文件，填入你的 TNS 账户信息：

```env
TNS_USER_ID=你的ID
TNS_USER_NAME=你的用户名
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
conda activate tardis
python scripts/fetch_target_params.py
```

或直接以模块方式运行：

```bash
python -m src.pipeline
```

### 3. 查看输出

报告保存在 `output/sn_report_{日期}_{目标}.txt`，找星图保存在 `output/images/`。

## 输出报告内容

| 项目 | 说明 | 示例 |
|------|------|------|
| **Target** | 目标名称与发现日期 | `SN 2026kid (4/22)` |
| **Type** | 暂现源类型 | `SN II`, `Ia`, `CV`, `Unclassified` |
| **RA / Dec** | 赤经赤纬（时角 + 度） | `15:15:57.23 / +56:18:32.1` |
| **Mag** | 最新测光星等（含日期和滤光片） | `16.2 Clear- (4/23)` |
| **Window** | 目标高度角 ≥ 30° 的时间窗口 | `20:30 - 03:50 (+1d) CST` |
| **Max Altitude** | 当晚最大高度角及时间 | `73.7 deg at 00:20 CST` |
| **Finding Chart** | 找星图（TNS 下载 + Aladin Lite 链接） | 本地 PNG 文件 + 在线星图 URL |

## TNS 数据获取方式

本流水线使用 **user 模式** 访问 TNS：

1. **公共目录 CSV** — 下载 `tns_public_objects.csv.zip`（缓存于 `data/`，24 小时内复用），从中提取目标基本参数（名称、类型、坐标、发现日期、红移、星等）
2. **目标页面抓取** — 访问 TNS 目标页面，提取最新测光数据和找星图链接

## 注意事项

- `.env` 包含 TNS 凭证，**不要提交到 git**
- `output/` 和 `data/` 已被 `.gitignore` 排除
- TNS 公共目录约 100MB，首次运行需要下载
- 观测窗口计算使用 astropy（自动退化为纯 Python 计算）
