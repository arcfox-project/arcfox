# Arcfox Home Assistant Integration

这是一个用于将北汽极狐（ARCFOX）电动车接入 Home Assistant 的自定义集成，支持通过 HACS 或手动复制到 `custom_components/arcfox` 使用。

## 当前内容

- UI 配置流
- `DataUpdateCoordinator` 轮询架构
- 车辆状态传感器
- 车辆门锁实体
- 空调、方向盘加热、除霜开关
- 空调温度设定
- 座椅加热/通风档位选择
- 车辆定位实体
- 唤醒、后备箱、车窗、天窗、闪灯鸣笛和刷新按钮
- 独立 transport 层
- BCTP/MQTT envelope 和 topic 构造骨架
- 原生 async MQTT publisher

## 当前状态

Home Assistant 集成架构已经完成，当前重点是完善 ARCFOX App 使用的车辆状态和远程控制协议。

由于 ARCFOX 没有公开完整的车联网开发文档，接口和协议仍需要通过官方 App 的公开行为进行验证。仓库中的文档和代码不保存任何真实账户、车辆、设备或授权信息。

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
- `binary_sensor`
  - 充电中
  - 已插枪
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

远程控制还依赖官方 App 使用的客户端证书和完整业务 protobuf 编码，因此 MQTT/BCTP 当前不是开箱即用。真实授权材料、车辆标识、设备标识和证书不能写入源码、README、日志或公开仓库。

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

1. `custom_components/arcfox/api.py`
2. `custom_components/arcfox/models.py`
3. `custom_components/arcfox/protocol.py`
4. `custom_components/arcfox/bctp.py`
5. `custom_components/arcfox/transport.py`

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
