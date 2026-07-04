# Arcfox Home Assistant Integration

这是一个用于将北汽极狐（ARCFOX）电动车接入 Home Assistant 的自定义集成骨架，适合通过 HACS 或手动复制到 `custom_components/arcfox` 使用。

当前仓库已经包含：

- UI 配置流
- `DataUpdateCoordinator` 轮询架构
- 车辆传感器
- 车辆锁实体
- 空调/方向盘加热/除霜开关实体
- 空调温度设定
- 座椅加热/通风档位选择
- 车辆定位实体
- 唤醒、后备箱、闪灯鸣笛与手动刷新按钮
- 独立的 transport 层，方便后面替换成 MQTT/BCTP
- BCTP/MQTT 的 envelope 和 topic 骨架
- BCTP publish-only transport scaffold
- 原生 async MQTT publisher，支持可选 broker 配置
- 仓库级 `logo.png` 和集成级 `custom_components/arcfox/icon.png`，用于展示图标
- 配置流已支持直接导入 app 会话的 `access token`，不再强制要求短信验证码

## 当前状态

Home Assistant 这一层已经是完整结构，当前重点已经转到 app 会话和 BCTP 远控协议。

原因很直接：极狐车联网接口没有公开官方开发文档，真实接入通常需要从官方 App 抓包、反编译或已有民间 SDK 中整理登录、车辆列表、状态查询、远程控制等接口。

也就是说：

- 这个仓库现在可以作为正式开发起点
- Home Assistant 架构已经搭好
- 真正决定能否连上车辆的是 `api.py` 中的接口地址、鉴权字段和响应结构映射

## 目录结构

```text
custom_components/
  arcfox/
    __init__.py
    api.py
    bctp.py
    binary_sensor.py
    button.py
    config_flow.py
    const.py
    coordinator.py
    device_tracker.py
    entity.py
    lock.py
    manifest.json
    models.py
    sensor.py
    strings.json
    switch.py
    translations/
      en.json
      zh-Hans.json
hacs.json
```

## 开发重点

你后续主要需要改这几个位置：

1. `custom_components/arcfox/api.py`
2. `custom_components/arcfox/models.py`
3. 如果返回字段变化较大，再补对应实体平台

### 需要补齐的接口

- 登录
- 刷新 token
- 查询账号车辆列表
- 查询单车状态
- 远程锁车 / 解锁
- 远程开启 / 关闭空调
- 唤醒车辆

## 安装

### 手动安装

复制 `custom_components/arcfox` 到你的 Home Assistant 配置目录：

```text
config/custom_components/arcfox
```

然后重启 Home Assistant，在“设备与服务”中添加 `ARCFOX`.

### HACS

仓库已经包含 `hacs.json`，可以作为自定义仓库导入。

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

## `cmd=7` 现状

当前代码里已经把 `cmd=7` 这组 body-control 命令整理成统一封装，按目前静态证据映射为：

- `window`
- `defrost`
- `door`
- `trunk`
- `flashHonk`
- `sunroof`

其中已接入 Home Assistant 的是：

- 前除霜
- 打开/关闭车窗
- 打开/关闭天窗
- 打开后备箱
- 闪灯鸣笛

## `cmd=6` 现状

`100601010001 / 100601010002 -> group=10 cmd=6` 目前按“座椅舒适总开关”处理，后续等实车报文再最终确认具体业务对象。

## 协议归一化

当前已经整理出来的高置信映射如下：

| 命令簇 | 用途 | 备注 |
| --- | --- | --- |
| `cmd=2` | 空调设温 | `p1` 为温度 |
| `cmd=6` | 座椅舒适总开关 | 先按总开关处理 |
| `cmd=7` | 车身动作 | 车窗、门、后备箱、闪灯鸣笛、天窗 |
| `cmd=8` | 座椅加热/通风 | 四席位，按档位控制，代码层拆成 `seat_heat` / `seat_wind` |
| `cmd=16` | 方向盘加热 | 两态控制 |
| `cmd=33` | 空调主控 | 开关和复合参数 |
| `cmd=38` | 前/后除霜 | `p1` 区分前后 |

对应到 Home Assistant 目前暴露的控制项：

- 空调开关
- 空调温度
- 方向盘加热
- 前后除霜
- 座椅加热 / 通风
- 车窗 / 天窗 / 后备箱 / 闪灯鸣笛

代码里已经把这些动作抽成统一的 command spec，集中放在 `custom_components/arcfox/protocol.py`，`api.py` 只负责调用规格表并交给 `transport.py`。

`custom_components/arcfox/bctp.py` 里已经补了 BCTP 的 header、envelope 和 topic 构造骨架。

`custom_components/arcfox/transport.py` 已经定义好底层传输契约，并补了一个可挂 MQTT 发布器的 BCTP command transport scaffold。`api.py` 现在会在可识别的命令上优先走这个命令通道，没挂 transport 时则回退到现有 HTTP 占位实现。座椅命令已经拆成 `seat_heat` 和 `seat_wind` 两个显式动作。

当前默认 API base URL 已切到 APK 配置里出现的 `https://hbt-app-rsa-pre.bjev.com.cn`，客户端会自动轮询一组候选入口，包括 `hbt-app-rsa.bjev.com.cn`、`napi.arcfox.cn` 和 `arcfoxapp-new-iov.bjev.com.cn`，以覆盖 app 新旧网关切换的情况。登录路径切到 `/auth/signin`，车辆状态优先走 `/rc/bctp/carState/query/{vin}` 和 `/tsp/car/vehicleConfig/{vin}`。

配置里已经可以选择 `http` 或 `mqtt` 命令通道。`mqtt` 模式下会使用本仓库内置的原生 MQTT publisher 直连 broker，再发布 BCTP envelope。

调试时建议把 `custom_components.arcfox` 的日志级别开到 `debug`，这样会直接打印命令走的是 MQTT 还是 HTTP，以及 BCTP publish request 的完整结构。

更详细的未决问题和后续待办放在 [ARCFOX_协议问题记录.md](/home/peter/workplace/arcfox/ARCFOX_协议问题记录.md)。

## Logo

当前仓库使用的 ARCFOX logo 来源于用户提供的图样，并保留了一个参考来源：

- https://favpng.com/png_view/arcfox-logo-png/7MCDBLCk

## 下一步建议

如果你要把它接到真实极狐车辆，最有效的路径是：

1. 用 app 登录后拿到 `userId / accessToken / refreshToken / vin`
2. 在 Home Assistant 配置里导入这组会话
3. 先验证只读 REST 车况接口
4. 再补齐 BCTP protobuf 编码和 MQTT 下发

## 参考

- Home Assistant integration file structure:
  https://developers.home-assistant.io/docs/creating_integration_file_structure/
- Home Assistant config flow:
  https://developers.home-assistant.io/docs/core/integration/config_flow/
- Home Assistant data fetching:
  https://developers.home-assistant.io/docs/integration_fetching_data/
