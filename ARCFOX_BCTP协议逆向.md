# ARCFOX BCTP 远控协议逆向记录

本文基于本地 JADX 反编译结果（`BaicTelematicsSDK.sendCommand`、`CommandUtils.formOrderByPb`、
`BctpParseUtilsKt.composeBctpAgreement`、`AceMacUtil`、`BQMqttService`）整理，是对
`ARCFOX_协议问题记录.md` 中“推测”部分的替换与确认。所有结论均来自静态反编译，未写入任何真实凭据。

## 1. BCTP 帧结构（已确认，字节级）

来源：`BctpParseUtilsKt.composeBctpAgreement` / `decomposeBctpAgreement`。

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 1 | protocolName | 普通车型 `0`；N80KS / B31CS 为 `103` |
| 1 | 1 | frameworkProtocolVersion | `1` |
| 2 | 17 | vin | ASCII |
| 19 | 4 | deviceNumber | 大端，恒为 `3123` |
| 23 | 30 | terminalBarcode | 仅 protocolName=103 时存在，`"0"*30` |
| 23/53 | 2 | type | 4 位 hex 业务码（见第 4 节），首字节高位置 0 |
| 25/55 | 1 | compressFlag | `0` |
| 26/56 | 10 | sendTime | 见下方编码 |
| 36/66 | 1 | businessProtocolDatauUnitType | `2` |
| 37/67 | 2 | messageNumber | 大端，自增 |
| 39/69 | 2 | serviceProtocolVersion | `1` |
| 41/71 | 4 | businessProtocolDataUnitLength | 大端，body 长度 |
| 45/75 | n | body | protobuf 业务负载 |

### sendTime 10 字节编码（已确认，之前代码有 1 字节偏移错误）

`BctpParseUtilsKt.toByteDateFromLongTime` 输出：

```
[0, year_hi, year_lo, month, day, hour, minute, second, millis_hi, millis_lo]
```

- 第 0 字节恒为 `0`
- 年份占 `[1:3]`（大端 short）
- 毫秒占 `[8:10]`（`epoch_millis % 1000` 的大端 short）

已修正 `custom_components/arcfox/bctp.py:_bctp_date_bytes`。

## 2. 业务 protobuf（已确认）

远控控制类指令的业务负载是 `ElectircVehiRmtCtrlControlBuf.ElectircVehiRmtCtrlControl`：

```proto
message ElectircVehiRmtCtrlControl {
  string cmddown = 1;
}
```

即只有一个 `cmddown` 字符串字段，内容是 JSON 透传。protobuf 编码 = `0x0A + varint(len) + json`。

查询/设置类分别对应 `ElectircVehiRmtCtrlQuery` / `ElectircVehiRmtCtrlSet`，结构相同（均为 `string cmddown = 1`）。

## 3. cmddown JSON 结构（已确认）

`cmddown` = `Gson(BctpControlCmdEntity)`，顶层为：

```json
{
  "header": {"VER":"1","GROUP":"10","CMD":"7","TOKEN":"...","ST":"...","SEQ":"...","DOWN":"1"},
  "body": {"c":"1","p2":"1","p3":"1"},
  "cyber": {"userID":"...","keyID":"00","CMAC":"..."}
}
```

- `header`：字段名大写，全部为字符串。`DOWN` 默认 `"1"`；`UP` 为 null（Gson 省略）。
- `body`：`RemoteRequestBean`。`group`/`cmd`/`businessCode` 在序列化前被置空，因此 body 只保留 `c`、`p1..p12` 等非空字段。
- `cyber`：仅特定车型存在（见第 6 节），非 CMAC 车型无此字段。

## 4. 命令映射（已确认，修正旧记录）

关键修正：旧记录写的是 `group=7, cmd=1`，反编译显示车身控制簇实际是 **`group=10, cmd=7`**。
命令串 `10070101000101` 的解读为 `10`(group) + `07`(cmd) + `01`(c) + `01`(p2) + `0001`(p3 区域) + `01`。

`BaicTelematicsSDK.sendCommand` 中 body-control（cmd=7）槽位：

| 动作 | c | p2(槽位掩码) | 值字段 | 开 | 关 |
|---|---|---|---|---|---|
| 车窗 | 1/2 | 1 | p3 | 1 | 4 |
| 除霜 | 1/2 | 2 | p8 | 1 | 4 |
| 门锁 | 1/2 | 4 | p9 | 1 | 4 |
| 后备箱 | 1/2 | 8 | p10 | 1 | 4 |
| 闪灯鸣笛 | 1/2 | 16 | p11 | 1 | 4 |
| 天窗 | 1/2 | 32 | p12 | 1 | 4 |

座椅（cmd=8）槽位：`group=10, cmd=8`，`p2` 为座椅掩码（左前 1 / 右前 2 / 左后 4 / 右后 8），
值字段对应 `p3/p8/p9/p10`，档位 `1/2/3`。

其它簇（`group=10`）：空调设温 `cmd=2`（`p1`=温度）、空调主控 `cmd=33`、除霜 `cmd=38`（`p1` 区分前后）、
方向盘加热 `cmd=16`、座椅舒适总开关 `cmd=6`。

已同步修正 `custom_components/arcfox/protocol.py`。

## 5. TOKEN / ST / SEQ（已确认格式）

- header `TOKEN`：`CommandUtils.getToken(businessCode)` = `"A" + 10位随机数 + MMddHHmmss + businessCode`。
- header `ST`：`TimeUtils.getTimeMill(now)` = `yyyy-MM-dd HH:mm:ss.SSS`。
- header `SEQ`：`CommandUtils.seq` 自增；帧头 `messageNumber`：独立 `AtomicInteger` 自增。

## 6. CMAC 签名（已确认算法）

`AceMacUtil.calculateCMACString(keyHex, message)` = **AES-CMAC（RFC 4493）**：
- key = `rcKey` 的 hex 解码（16/24/32 字节）
- message = `Gson(BctpControlCmdEntity)` 的 UTF-8
- 输出大写 hex

`buildCyBerMac` 逻辑：
- 仅对 N80KS / N50AS / C66TB_Z04 / C66TB / C37TB / N50AB / N51AS / N53TB / C12HB / B31CS 生效；**N5 系列不签名**。
- `keyID` = `getRckeyIsCloudCks` 为真时 `"00"`，否则 `"01"`。
- `cyber = {userID, keyID, CMAC}`。

已新增 `custom_components/arcfox/cmac.py`（纯 AES-CMAC，已对 RFC 4493 与 `cryptography` 参考实现交叉验证）。

## 7. MQTT 连接参数（已确认）

来源：`BQMqttService.doClientConnection` / `init`（`beapplibrary` 与 `applibrary` 两个 SDK）。

- 地址（按车型平台，生产环境）：
  - BE12 → `ssl://emqx-be12.bjev.com.cn:8883`
  - N5（N50/N51）→ `ssl://emqx-n5.bjev.com.cn:8883`
  - N80KS → `ssl://emqx-n8.bjev.com.cn:8883`（注意是 `emqx-n8`，不是 `n80`）
  - BE12 北京专版（C66TB_Z04）→ `ssl://emqx-be12-pub.bjev.com.cn:8883`
  - KAOLA / KAOLA_C01 / KAOLA_C04（`applibrary` C46 平台）→ `ssl://emqx-c46.bjev.com.cn:8883`
  - 测试环境统一 `ssl://emqx-test.bjev.com.cn:8883`（C46 为 `ssl://emqx-test-c46.bjev.com.cn:8883`）
- `clientId` = `vin-userId-imei`
- `username` = `MOBILE_<userId>`
- `password` = `accessToken`
- TLS 客户端证书：
  - 本地证书模式：`files/<userId>.crt` + `files/<userId>.key`（PKCS8 PEM），由登录后动态申请；
  - 或 AndroidKeyStore 别名 `be12privatecert`（私钥不可导出）。
- 订阅/发布 topic：`bctp/<model>/standard/terminal/<VIN>/topic/21`（车型前缀见 `_infer_topic_route`）。

**这是从 HA 直连 MQTT 的真正硬门槛**：仅填 username/password 不够，必须有该次登录会话的动态客户端证书。

## 7.1 客户端证书自助申请/换发（已确认，已实现脚本）

关键结论：私钥是**本地生成**的，服务端只收 CSR（`p10`），因此无需 root/导出手机，
只要知道 `userId`（手机号）+ `VIN` + 短信验证码，就能在任何客户端申请/换发证书。

- `POST /auth/signinsms`，body `{userId, vin}` → 发短信验证码。
- `POST /auth/signin`，body `{userId, vin, smsCode, p10}` → 返回 `data.certificate`（客户端证书）+ `data.token`（accessToken，MQTT 密码）+ `data.rcKey`。
- CSR：RSA-2048 + SHA1WithRSA，subject `C=CN, CN=MOBILE_<userId>_<epochMilli>`（见 `CsrUtil.genCSR`）。
- HTTP 头：`User-Agent: volley/0`、`baic_traceId: <uuid>`、`Content-Type: application/json`。
- 换发分支（本地已有证书，仅刷新 token）：`/auth/signin` 不带 `p10`，body `{userId, vin, smsCode}`。

API 基础地址（生产）：BE12 → `https://sdkserver-be12.bjev.com.cn/api`、N5 → `https://sdkserver-n5.bjev.com.cn/api`、
N80 → `https://sdkserver-n80.bjev.com.cn/api`、C46/KAOLA → `https://sdkserver.bjev.com.cn/api`。

实现：`scripts/arcfox_bootstrap_cert.py`（生成 `<userId>.crt/.key` 并打印 MQTT 参数）。

## 8. 仍未确认

- `BctpProtoEnum` 各枚举的 `getValue()` 精确 hex 值（`beremotelibrary` 为运行时/独立库，未在 APK dex 中反编译出）。
  当前 `bctp.py` 回退为 `10<cmd:02d>`，需实车报文最终确认。
- header `DOWN="2"` 的完整命令串集合（已确认包括 `101904/101903/100104/100003/100002/10190300/10010302/10010301/10000102/10000101`）。
- `rcKey` 与 `getRckeyIsCloudCks` 的运行时来源（SPHelper 写入时机）。

## 9. 落地清单

- 只读状态：字段映射已基本齐全，缺“活 token + 真机验证”。
- 远控：帧编码 / cmddown / CMAC 已补齐，剩余 = 动态客户端证书 + `type` 精确值 + 实车联调。
- 证书获取：放弃模拟器导出路线，改用自助申请 `scripts/arcfox_bootstrap_cert.py`（仅需 userId + VIN + 短信验证码）。
- 验证：拿到证书后用 `scripts/arcfox_mqtt_probe.py`（已支持 `--certfile/--keyfile`）验证双向 TLS 建链，再回读 `type` 精确值。
