# Arcfox Home Assistant Integration

这是一个用于将北汽极狐（ARCFOX）电动车接入 Home Assistant 的自定义集成，支持通过 HACS 或手动复制到 `custom_components/arcfox` 使用。

## 当前内容

- UI 配置流
- `DataUpdateCoordinator` 轮询架构
- 只读车联网（IOv）TCP 客户端，已完成握手和状态查询验证
- 车辆状态、胎压、充电、温度传感器
- 车辆定位实体
- 车辆门锁、空调、方向盘加热、除霜、座椅等控制实体（占位，尚未接入真实控制链路）
- 独立 transport 层
- BCTP/MQTT envelope 和 topic 构造骨架
- 原生 async MQTT publisher

## 当前状态

只读车辆状态链路已经打通：集成使用官方 App 的 IOv 网关（`arcfoxapp-new-iov.bjev.com.cn:60115`）完成握手，并通过在线状态查询和完整状态查询读取电池、续航、总里程、胎压、位置、温度、门锁、充电等状态。

远程控制链路（IOv/AppServer TCP）已完成握手验证，`appToken`/`imei`/`aid` 有效时可直接鉴权；真实下发指令尚未夜间实测。

由于 ARCFOX 没有公开完整的车联网开发文档，接口和协议仍需要通过官方 App 的公开行为进行验证。仓库中的文档和代码不保存任何真实账户、车辆、设备或授权信息。

## 令牌同步（推荐）

实测结论：手机 App「半个月不用重新登录」并不是 mg 账号 token 被刷新，而是**车控通道根本不依赖它**。车辆读写走 IOv/AppServer TCP，鉴权凭据是手机 App 车控 SDK 的 `appToken`（32 位 hex，即 `control_sdk_log` 里的 `appToken:` 字段）+ `imei` + `aid` + `vin`；TSP REST 另用约一年有效的 `tspAccessToken`（JWT）。mg 账号的 `access_token` 只用于用户/商城等接口，与车辆状态无关。

手机已登录 App 时，用一条命令把当前 `appToken` 同步到 HA：

```bash
python3 tools/arcfox_sync.py --serial <adb-serial> --apply \
  --ha-host <ha-host> --ha-ssh-port 22222 --ha-user root \
  --ha-password '<ssh-password>' --restart
```

脚本会读取手机 `/sdcard/Android/data/com.bjev.arcfox/files/control_sdk_log` 最新日志，
提取 `appToken`/`imei`/`aid`/`vin`，先做 IOv 握手校验，再备份并写回 HA 的
`core.config_entries`（更新 `remote_token`、`options.app_token`、`imei`），最后重启 HA。
无需 root、无需验证码、无需密码登录。

当 HA 再次出现 4402/鉴权失败时，通常只是手机 App 重新登录后 `appToken` 轮换了，
重新跑一遍上面命令即可，即「刷新 token」。

## 登录与令牌

集成保留 B2C 账户域（`hbt-app-rsa.bjev.com.cn`）的登录/续期路径，供需要 mg 账号
REST 数据时使用：

- 配置流可输入「手机号 + 密码」或「手机号 + 短信验证码」完成登录，并把 `access_token` / `refresh_token` 写入配置。
- `access_token` 过期时自动用 `refresh_token` 调 `/viam/v1/auth/token` 续期并重试请求。
- 若 `refresh_token` 也失效且保存了密码，会回退到密码登录；密码登录要求图片验证码时会在配置流中提示输入。
- 密码仅在本地 Home Assistant `.storage` 中保存，不会写入本仓库。

## 只读状态查询 CLI

仓库提供独立的只读查询脚本，用于在 Home Assistant 之外验证协议：

```bash
ACCESS_TOKEN='<app access token>' ARCFOX_VIN='<vin>'   ARCFOX_AID='<aid>' ARCFOX_IMEI='<15-digit imei>'   python3 scripts/arcfox_iov.py
```

该脚本只执行在线状态查询和完整状态查询，不会发送任何控制命令。

## 安装

### 手动安装

将 `custom_components/arcfox` 复制到 Home Assistant 配置目录：

```text
config/custom_components/arcfox
```

重启 Home Assistant，然后在“设置 → 设备与服务”中添加 ARCFOX。

### HACS

仓库包含 `hacs.json`，可作为自定义仓库导入。

## 已实现的实体

- `sensor`
  - 电池电量
  - 续航里程
  - 总里程
  - 车内温度
  - 车外温度
  - 电池温度
  - 四轮胎压
  - 充电状态
  - 充电功率
  - 充电电压
  - 充电电量
  - 充电目标电量
- `binary_sensor`
  - 充电中
  - 已插枪
  - 车辆在线
  - 服务端数据就绪
- `lock`
  - 车辆门锁
- `switch`
  - 空调开关
  - 方向盘加热
  - 前除霜
  - 后除霜
- `number`
  - 空调设定温度
- `select`
  - 四个座椅的加热/通风档位
- `device_tracker`
  - 车辆位置
- `button`
  - 唤醒车辆
  - 打开/关闭车窗
  - 打开/关闭天窗
  - 打开后备箱
  - 闪灯鸣笛
  - 立即刷新

## 协议实现

当前已整理的命令簇包括：

| 命令簇 | 用途 |
| --- | --- |
| `cmd=2` | 空调设温 |
| `cmd=6` | 座椅舒适总开关（待实车确认） |
| `cmd=7` | 车身动作 |
| `cmd=8` | 座椅加热/通风 |
| `cmd=16` | 方向盘加热 |
| `cmd=33` | 空调主控 |
| `cmd=38` | 前/后除霜 |

命令规格集中在 `custom_components/arcfox/protocol.py`，API 层负责调用，transport 层负责发送。

`custom_components/arcfox/bctp.py` 已包含 BCTP header、envelope、protobuf payload 和运行时 topic 构造骨架。`mqtt_client.py` 提供 QoS 1 的原生异步 MQTT 发布器。

## 远程控制状态

远程控制仍依赖尚未完全验证的控制链路，因此 `switch` / `lock` / `button` / `select` / `number` 控制实体当前不是开箱即用，也不会向车辆发送控制指令。真实授权材料、车辆标识、设备标识和证书不能写入源码、README、日志或公开仓库。

只读状态走官方 App 的 IOv TCP 网关（`custom_components/arcfox/iov.py`），凭据通过配置流传入：
- `access_token`：App 访问令牌
- `remote_token`：手机端车控 SDK 的短时效令牌（32 位十六进制，即 App 日志里的
  `appToken`）。配置后 IOv 只读通道直接使用它，不再通过 `access_token` 向
  `mg.arcfox.cn` 换取；`access_token` 过期时仍可借此恢复只读状态。
- `vin`：车辆识别码
- `aid`：账户 aid（可选）
- `imei`：15 位设备标识（可选）

`remote_token` 可以从已登录手机的
`/sdcard/Android/data/com.bjev.arcfox/files/control_sdk_log` 最新日志中提取
（`appToken:` 字段），也可用 `scripts/arcfox_pull_account.py` 自动提取。

## Android 缓存只读验证

`scripts/arcfox_adb_status.py` 可以通过 ADB 读取官方 Android App 已经写入的
Control SDK 日志，并输出脱敏后的车辆状态 JSON。它只执行目录读取和文件读取，
不会启动 App、查询车辆或发送控制命令。

```bash
python3 scripts/arcfox_adb_status.py \
  --adb /path/to/adb \
  --serial YOUR_ADB_SERIAL
```

也可以离线解析之前复制的日志：

```bash
python3 scripts/arcfox_adb_status.py --file /path/to/control_sdk_log.text
```

目前可解析电池电量、续航、总里程、空调、充电、四门、后备厢、车窗和天窗状态。
锁止状态暂时输出 `lock_state_code` 原始码，等待与官方 App 界面交叉验证后再转换为
布尔值。输出中的 `observed_at` 是最近一次状态记录时间；该方式读取的是缓存，官方
App 长时间未连接车辆时数据可能过期。

脚本不会输出 VIN、设备标识、位置或令牌。使用完毕后建议关闭无线调试，并撤销不再
使用的 ADB 主机授权。

## 开发入口

主要代码位置：

1. `custom_components/arcfox/iov.py`（只读 IOv TCP 协议与状态字段映射）
2. `custom_components/arcfox/api.py`
3. `custom_components/arcfox/models.py`
4. `custom_components/arcfox/protocol.py`
5. `custom_components/arcfox/bctp.py`
6. `custom_components/arcfox/transport.py`

协议未决事项记录在 [ARCFOX_协议问题记录.md](ARCFOX_协议问题记录.md)。

## 安全注意事项

请勿提交以下内容：

- 账户或手机号
- 车辆识别信息
- 手机设备标识
- 访问令牌、刷新令牌或 App 令牌
- 密码、安全码、客户端证书或私钥
- Home Assistant 长期访问令牌

这些内容应只保存在本地 Home Assistant 的安全存储中。

## 参考

- Home Assistant integration file structure:
  https://developers.home-assistant.io/docs/creating_integration_file_structure/
- Home Assistant config flow:
  https://developers.home-assistant.io/docs/core/integration/config_flow/
- Home Assistant data fetching:
  https://developers.home-assistant.io/docs/integration_fetching_data/
