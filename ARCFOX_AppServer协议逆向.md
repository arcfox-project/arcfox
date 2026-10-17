# ARCFOX AppServer 长连接协议逆向记录

本文记录新版极狐 App（3.4.33+）车控 SDK 使用的「AppServer 自定义长连接」传输层
逆向结论。**不含任何手机号 / VIN / userId / token / 证书等真实凭据。**

## 1. 结论速览

- 车控 SDK 版本 `1.3.9.1`（华为 ICVCS 体系，BAIC 定制），真实车控通道是一个自定义长连接。
- 目标：`36.152.80.247:443`，DNS 名 `squnit-api-ai.jd.com`（京东云托管）。
- 传输层 = **标准 TLS 1.3**，但每条 TLS record body 外面套一层 5 字节混淆帧头，
  且 body 与一个 **48 字节固定密钥** 循环异或。
- 去混淆后可见标准 TLS 1.3 ClientHello / ServerHello：
  - ClientHello：legacy_version `0x0304`，cipher `1301/1302/1303` + TLS1.2 备选，
    SNI `squnit-api-ai.jd.com`，ALPN `h2, http/1.1`，key_share X25519。
  - ServerHello：legacy_version `0x0303`，选中 `TLS_AES_256_GCM_SHA384`（0x1302）。
  - ClientHello 带自定义扩展 `0x0020`，内容为 `0x02` + zlib 压缩数据（疑似设备/会话指纹）。

## 2. 帧格式（已确认，字节级）

```
byte0          TLS 内容类型: 0x16 handshake / 0x14 CCS / 0x17 application data
byte1          0x5f
byte2          0x58
byte3..4       (body_len ^ 0x5c5c) 大端 uint16
body[0..n]     TLS record body 循环异或 key[i % 48]
```

- 注意 body 是 **TLS record body**，不含标准 TLS record 的 5 字节头。
- `0x16` 帧去混淆后 = TLS handshake message（`0x01` ClientHello / `0x02` ServerHello）。
- `0x14` 帧去混淆后 = `01`（ChangeCipherSpec）。
- `0x17` 帧去混淆后 = TLS 1.3 AES-GCM 密文，无法用该 XOR 密钥解出明文（需 TLS 会话密钥）。

## 3. 48 字节 XOR 密钥

密钥从握手帧尾部零填充区提取（同一会话 C2S/S2C 方向一致，双向通用）：

```
1a ff aa 3b 2b 1c 4e 2c 5c 1b fe ab 3a 3c 4c cc
2c 6b 1a fd ac 39 4c 5c 7a 58 59 1d fc ad 38 5c
7c 7b 6c 8a 1e fb ae 37 2a 1a 8a 8b 8a 1f fa af
```

该密钥未在 APK 的 dex / so / assets 中以明文出现，推测由 SDK 原生代码在运行时生成或
分散存储。`scripts/arcfox_appserver_codec.py` 已内置此密钥用于加/解混淆。

## 4. 业务层（待补全）

- 握手完成后 `0x17` 为 TLS 1.3 密文，内容为车控 JSON / protobuf（SDK 日志可见
  `dataBean`、`carControlStateBean`、`carTyreState`、`唤醒查询指令` 等字段）。
- SDK 日志（`/tmp/ctrl.log`）显示完整流程：`从APP接收:imei,vin,AID,appToken` →
  `从APP接收到建立连接` → `向AppServer发送控制指令` → `从AppServer接收到控制结果` →
  `查询数据库返回车辆状态` → `向APP反馈车辆状态:{...}`。
- 凭据形态：`AID`（用户 id）、`appToken`（32 hex，实为去掉连字符的 UUID）。
- 待办：解出业务 JSON 的精确 wire 格式（长度前缀/JSON/protobuf）与握手鉴权消息。

## 5. 与 REST / MQTT 路线的关系

- 老版 BCTP/MQTT 路线仍存在（`beapplibrary`，见 `ARCFOX_BCTP协议逆向.md`）。
- `assets/config.json` 揭示 ICVCS 网关：
  - BAIC 生产：`https://hbt-app-rsa.bjev.com.cn/`
  - BAIC 预发：`https://hbt-app-rsa-pre.bjev.com.cn/`
  - ICVCS 生产：`https://api-app.beijingauto.icvcs.com/`
- SDK 还暴露 REST 接口（`com.android.applibrary.manager.ApiNet`）：
  - `/auth/signinsms`、`/auth/signin`、`/auth/refreshtoken`
  - `/rc/online/query/`、`/rc/online/wakeUp/async/`
  - `/rc/bctp/carState/query/`
  - 基础地址：`https://sdkserver-be12.bjev.com.cn/api`（BE12 平台）。
- 登录链路（`mg.arcfox.cn`）：短信验证码登录 → `tspAccessToken`（JWT，约 1 年）+
  `tspUid` + `aid`；`getSdkToken` → 第三方 JWT；App 侧另生成 `appToken`(UUID)。

## 6. 复刻客户端要点

1. TCP 连 `36.152.80.247:443`，按第 2 节帧格式 + 第 3 节密钥收发 TLS 1.3 记录。
2. TLS 1.3 握手（X25519，cipher `TLS_AES_256_GCM_SHA384`），ClientHello 需带：
   - SNI `squnit-api-ai.jd.com`
   - ALPN `h2, http/1.1`
   - 自定义扩展 `0x0020`（待解出内容）
3. 握手完成后用 TLS 1.3 导出密钥加密业务 JSON（格式待补全）。
4. 鉴权依赖 `AID` + `appToken`(UUID) + `imei` + `vin`。

## 7. 工具

- `scripts/arcfox_appserver_codec.py`：帧打包/解包、XOR 加解混淆、SNI 诊断。
  示例：`python3 scripts/arcfox_appserver_codec.py /tmp/apserver_C2S.bin`
