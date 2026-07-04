# ARCFOX 协议问题记录

这是当前对极狐 ARCFOX 接入 Home Assistant 的协议整理和未决问题记录。

## 已确认

- `cmd=2`
  - 空调设温
  - `p1` 是温度
- `cmd=6`
  - 当前按“座椅舒适总开关”处理
  - 仍需实车报文确认最终语义
- `cmd=7`
  - 车身动作簇
  - 覆盖车窗、门、后备箱、闪灯鸣笛、天窗
- `cmd=8`
  - 座椅加热/通风
  - 四席位、档位控制
  - 代码层已拆成 `seat_heat` / `seat_wind`
- `cmd=16`
  - 方向盘加热
- `cmd=33`
  - 空调主控
- `cmd=38`
  - 前/后除霜

## 认证链路

- 早先抓到的 `sdkserver-be12.bjev.com.cn/api` 这条车控 SDK 链路，登录相关接口是：
  - `POST /auth/signinsms`
  - `POST /auth/signin`
  - `POST /auth/refreshtoken`
- 这条链路里，SDK 代码显示登录请求会带：
  - `userId`
  - `vin`
  - `smsCode`
  - 某些分支还会带 `p10` / 证书内容
- 但最新手机抓包说明，App 的 UI 登录实际先走的是 B2C 层：
  - 图形验证码资源来自 `captcha.alicaptcha.com`
  - 会话和账号中心请求落到 `warden.op-newmall.arcfox.cn`
  - 登录态相关请求还会访问 `a1-019443ef.easemob.com` 和 `huanxin.arcfox.cn`
- B2C SDK 里可以确认：
  - `/protocol/login/service` 被注册成 `InnerLoginImpl`
  - `InnerLoginImpl.getUserToken()` 返回 `arcFoxToken`
  - `InnerLoginImpl.getUserPin()` 返回 `pin`
  - `LoginInterceptor` 会附加 cookie `third-login-from=21;mfs_jh_session=<token>;`
- 目前还没有抓到真正的车控后端请求，尤其是：
  - `sdkserver-be12.bjev.com.cn`
  - `findBindUserList`
  - `findUserCarBind`
  - `carState/query`
  - `bluetoothRemoteKey`
- 结论：
  - App 登录成功不等于我们已经拿到车控 SDK 的完整认证串
  - 下一步要补的是“进入车辆主页后”的车控请求抓包，而不是继续猜登录字段

## 车控链路

- 进入“我的AT”后，App 会启动 `BQMqttService`
- MQTT 服务器按车型选择：
  - `ssl://emqx-be12.bjev.com.cn:8883`
  - `ssl://emqx-be12-pub.bjev.com.cn:8883`
  - `ssl://emqx-n5.bjev.com.cn:8883`
  - `ssl://emqx-test.bjev.com.cn:8883`
- MQTT 连接参数：
  - `CLIENTID = vin-userId-imei`
  - `username = MOBILE_<userId>`
  - `password = accessToken`
- MQTT 订阅 topic 形如：
  - `bctp/<model>/standard/server/<vin>/topic/20/05`
  - `bctp/<model>/standard/appsdk/<vin>/topic/21`
  - `bctp/<model>/standard/server/<vin>/topic/20/04`
  - `bctp/<model>/standard/server/<vin>/topic/20/03`
- 车控成功前的本地依赖：
  - `SPHelper.saveUserInfo(...)` 保存 `userId / accessToken / refreshToken / vin`
  - `rcKey`、`rcKeyCks` 需要落到 `SPHelper`
  - `BQMqttService` 会优先读取本地证书，再回退 AndroidKeyStore
- 这意味着：
  - 手机 App 的“网络连接不畅”更像是 MQTT/证书层失败
  - 不是普通 HTTP 登录失败
  - 代理里看不到 `sdkserver-be12` 并不奇怪，因为控制页主要在走 MQTT

### 已确认的命令串

`BaicTelematicsSDK.sendCommand(...)` 里已经确认的常用命令串如下：

- `10070101000101`
  - `group=7`
  - `cmd=1`
  - `c=1`
  - `p3=1`
- `10070102000104`
  - `group=7`
  - `cmd=1`
  - `c=2`
  - `p3=4`
- `10070101000801`
  - `group=7`
  - `cmd=1`
  - `c=1`
  - `p10=1`
- `10070102000804`
  - `group=7`
  - `cmd=1`
  - `c=2`
  - `p10=4`
- `10070101001601`
  - `group=7`
  - `cmd=1`
  - `c=1`
  - `p11=1`
- `10070102001604`
  - `group=7`
  - `cmd=1`
  - `c=2`
  - `p11=4`
- `10070101003201`
  - `group=7`
  - `cmd=1`
  - `c=1`
  - `p12=1`
- `10070102003204`
  - `group=7`
  - `cmd=1`
  - `c=2`
  - `p12=4`

说明：

- `p3`、`p10`、`p11`、`p12` 对应的是 body-control 里的不同动作槽位
- `c=1` / `c=2` 基本可视作开 / 关两态
- 我们现在的 Home Assistant 动作层已经能映射这些槽位，但 BCTP protobuf 还没完全复刻，所以控制发送还差最后一层编码

## BCTP 报文结构

### 顶层协议头

`BctpProtoEntity` 的核心字段已经坐实：

- `protocolName`
- `frameworkProtocolVersion = 1`
- `vin`
- `deviceNumber = 3123`
- `terminalBarcode`
- `qos = 1`
- `type`
- `compressFlag`
- `sendTime`
- `businessProtocolDatauUnitType = 2`
- `messageNumber`
- `serviceProtocolVersion = 1`
- `businessProtocolDataUnitLength`
- `bctpEntity`

### 编码规则

`BctpParseUtils.encode(...)` 的流程是：

1. 先把业务 protobuf 对象 `toByteArray()`
2. 再把上面的顶层协议头拼起来
3. `type` 用十六进制字符串转字节
4. 时间字段是 10 字节结构
5. 如 `compressFlag == 2`，解码时会走 `Snappy`

### 控制包

`BctpControlCmdEntity` 结构是：

- `header`
- `body`
- `Cyber`

其中 `Cyber` 字段包含：

- `userID`
- `keyID`
- `CMAC`

计算逻辑：

- `keyID` 来自 `SPHelper.getRckeyIsCloudCks(...)`
- `CMAC` 用 `rckey` 对整个 JSON 做校验

### 远程启动/透明传输

另一条分支会走：

- `ElectricRtmTransparentTransmission`

里面的内容包含：

- `token = SDKREMOTESTART<随机数>`
- `content = BctpRemoteStartCmdEntity` 的 JSON

这说明：

- 现在仓库里的 MQTT scaffold 还只是把 topic 和头部框架搭起来
- 真正能下发控制，还差业务 protobuf 类和 `BctpParseUtils.encode(...)` 的完整替换

### topic 路由

App 里实际 topic 前缀和车型强相关，已确认：

- `BE12` -> `bctp/BE12/standard/terminal/<VIN>/topic/21`
- `N5` / `N50AB` / `N51AB` / `N50AS` / `N51AS` -> `bctp/N5/standard/terminal/<VIN>/topic/21`
- `N80KS` -> `bctp2/N80KS/standard/terminal/<VIN>/topic/21`
- `B31CS` -> `bctp2/B31CS/standard/terminal/<VIN>/topic/21`
- `N60` -> `bctp2/N60AS/standard/terminal/<VIN>/topic/21`

这也是为什么当前集成里不能死写 `N5`。

## 当前代码状态

- Home Assistant 实体已经接入
- `switch`
  - 空调
  - 方向盘加热
  - 前除霜
  - 后除霜
  - 座椅舒适总开关
- `number`
  - 空调设定温度
- `select`
  - 四个座椅的加热/通风档位
- `button`
  - 唤醒
  - 车窗
  - 天窗
  - 后备箱
  - 闪灯鸣笛
  - 刷新
- `transport.py`
  - 已定义底层传输契约
  - 当前仍是 HTTP 占位实现
  - 已补一个 BCTP command transport scaffold
- `mqtt_client.py`
  - 已补原生 async MQTT publisher
  - 支持可选 broker 配置
  - 命令发布可直接打 debug 日志
- `const.py`
  - 默认 API base URL 已切到 `https://sdkserver-be12.bjev.com.cn/api`
- 认证字段已切到 `user_id` / `vin` / `sms_code` / `refresh_token`
- `protocol.py`
  - 已整理 command spec
  - `api.py` 通过规格表调用动作
- `bctp.py`
  - 已补 BCTP header / envelope / topic 构造骨架
  - 命令层可直接生成 publish request
- `cmd=8` 动作
  - 已接到 `async_set_seat_option`
  - 现在能走统一命令通道
- 实体层
  - 命令调用现在优先传完整 vehicle 对象，方便后续命中 VIN topic

## 仍需确认

1. `cmd=6` 的最终业务对象
2. `cmd=8` 中 heat / wind 的真实协议分界
3. `cmd=7` 六个槽位是否需要进一步细分到车门/除霜等具体动作
4. 实车返回体的成功/失败码
5. 车辆状态回读字段是否存在更稳定的官方字段名
6. 继续补齐 `lock` / `wake_up` 等未映射命令的 BCTP 头字段，减少 HTTP 回退

## 风险点

- 目前 `api.py` 仍然保留占位 HTTP 路径
- `cmd=6`、`cmd=8` 仍然带有推断色彩
- 如果后续抓到真实 MQTT / protobuf 报文，协议层大概率还要再收一轮
- 车辆列表查询目前按单 VIN 拉取，若一个账号多车，后面需要再补列表接口
