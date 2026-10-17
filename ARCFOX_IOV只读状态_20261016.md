# ARCFOX IOv 只读状态协议（2026-10-16 验证通过）

本文记录极狐 App 车联网（IOv）TCP 网关的只读状态查询协议。已用独立
Python 客户端完整跑通握手 → 在线查询 → 完整状态查询，并复现出与 App
一致的车辆状态数据。

> 只包含协议格式与字段映射，不包含任何账户、VIN、IMEI、令牌等敏感信息。

## 网关

| 项 | 值 |
| --- | --- |
| 主机 | `arcfoxapp-new-iov.bjev.com.cn` |
| 端口 | `60115`（生产环境 `0` 对应 `arcfoxapp-iov.bjev.com.cn:60015`） |
| 传输 | 明文 TCP，非 TLS |

## 帧格式

固定 26 字节头，后接业务负载，再后接 57 字节凭据后缀。

```
byte 0        msg_type: 1=握手, 2=数据
byte 1        main version = 8
byte 2        ci version = 2
byte 3..17    15 字节 IMEI ASCII
byte 18..19   liushuihao，小端
byte 20..21   bodyMessageType，小端有符号 short
byte 22..25   bodyLength，小端（只计业务负载长度）
byte 26..     AES 加密的业务负载
尾部 57 字节  VIN(17) + AID(小端 u64, 8) + remoteToken(32)
```

## 握手

固定密钥/向量 `1234567812345678`。

- ClientHello bodyType=1，protobuf 字段：1=clientId, 2=clientRandom(16),
  3=signature, 4=appId(`ae9db49b-7b8e-411d-ae16-e227a782b7af`)。
  - 签名前数据：`\x01\x00 + le16(clientId) + clientRandom`，SHA256 后
    AES-CBC 加密。
- ServerHello bodyType=2，返回 result、serverId、serverRandom、signature。
- ClientFinish bodyType=3，服务端 ServerFinish bodyType=4，result=0 表示成功。
- 会话密钥/向量（非简单拼接）：
  - `key = md5(xor(FIXED_KEY, clientRandom) + md5(xor(FIXED_KEY, serverRandom)))`
  - `iv  = md5(clientRandom + FIXED_IV + serverRandom)`

## 只读查询

### 在线状态

- 请求 bodyType = `-32759`（OnlineID），payload = `QueryProto.Query{vin=1}`。
- 响应 bodyType = `6`，`QueryProto.QueryOnlineResponse{seq=1, vin=2, online=3}`。

### 完整状态

- 请求 bodyType = `-32511`（DRIVE_CAR_DATA），payload = `StringTransferProto.StringTransfer{seq=1, vin=2, content=3}`。
- content 为 JSON：

```json
{
  "ST": "查询时间",
  "queryItems": { "S1": "", "S2": "", "...": "" },
  "token": "NZ<vin后6位><yyMMddHHmmss><4位序列>",
  "vinNo": "VIN"
}
```

- 响应 bodyType = `4098`（CarDataResponse），同样为 StringTransfer，
  content 含 `queryResult`，即 `S*` 字段的状态值。

## S 字段映射（摘自 `order.e.c()`）

| S 字段 | 含义 |
| --- | --- |
| S1 | 充电状态 chargeState |
| S2 | 空调状态 airState |
| S3 | 除霜状态 defrostState |
| S4 | 门锁状态 lockState（0/1） |
| S5 | 充放电功率 kW |
| S6 | 车窗状态 |
| S7 | 天窗状态 |
| S8 | 充放电电压 V |
| S15 | 驱动/环境温度 |
| S22 | 充电枪状态 |
| S24 | 当前电量 % |
| S25 | 剩余充电时间 |
| S26 | 充电电量 kWh |
| S28 | 电池温度 |
| S35 | 续航里程 km |
| S36 | 位置 `lng;lat` |
| S39 | 后备箱状态 |
| S40 | 总里程 km |
| S42–S46 | 四门状态 |
| S47 | 充电目标电量 |
| S48 | 车内温度 |
| S53 | 放电状态 |
| S56 | 左前轮胎压 JSON |
| S57 | 右前轮胎压 JSON |
| S58 | 左后轮胎压 JSON |
| S59 | 右后轮胎压 JSON |
| S65 | 直流充电枪状态 |
| S110–S120 | 哨兵/生命体征/远程查看等 |

胎压 JSON 中 `TPV` 为胎压值（kPa）。更多字段见
`custom_components/arcfox/iov.py` 的 `S_FIELD_MAP`。

## 安全边界

本协议当前只实现只读查询，不含任何控制指令（锁车、车窗、天窗、寻车、
闪灯鸣笛、空调等）。控制链路需另行验证后再接入 Home Assistant。
