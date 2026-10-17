# ARCFOX 远程控制 REST 通道逆向（2026-10-16）

结论：App 的远程控制走 B2C 账户域 `hbt-app-rsa.bjev.com.cn` 的 REST 接口（`/vctrl/v1/controls/*`），
不是 legacy 的 `sdkserver-be12.bjev.com.cn`，也不是 AppServer 长连接。

## 鉴权链路

1. 用 App 的 OAuth `app_token`（client_credentials）调 `POST /vcam/v1/auth/accounts/login`
   做密码登录，得到 B2C JWT `accessToken` + `refreshToken`。
2. `POST /vctrl/v2/security-code/check`，body `{"safeCode": "<App 安全码>"}`，
   头带 `Authorization: <B2C JWT>`、`token_type: user_token`，返回短时效 `rcToken`（字符串）。
3. 控制请求带 `X-Vehicle-Id: <数字车辆ID>`、`rcToken: <rcToken>`、`token_type: user_token`。

## 控制端点（已从 Retrofit 接口 + 调用方还原）

| 动作 | 方法/路径 | rcToken | Query 参数 |
| --- | --- | --- | --- |
| 上锁 | POST `/vctrl/v1/controls/doors` | 是 | `open=false` |
| 解锁 | POST `/vctrl/v1/controls/doors` | 是 | `open=true` |
| 开窗 | POST `/vctrl/v1/controls/windows` | 是 | `open=true&openType=10` |
| 关窗 | POST `/vctrl/v1/controls/windows` | 是 | `open=false` |
| 开天窗 | POST `/vctrl/v1/controls/skylight` | 是 | `open=true&range=10` |
| 关天窗 | POST `/vctrl/v1/controls/skylight` | 是 | `open=false&range=10` |
| 开后备箱 | POST `/vctrl/v1/controls/elec-trunk` | 是 | `open=true` |
| 寻车（闪灯鸣笛） | POST `/vctrl/v1/controls/flashing-honking` | 否 | `type=1` |
| 空调开 | POST `/vctrl/v1/controls/air-conditioner` | 是 | `enabled=true&targetTemp=24` |
| 空调关 | POST `/vctrl/v1/controls/air-conditioner` | 是 | `enabled=false` |
| 空调调温 | POST `/vctrl/v1/controls/air-conditioner` | 是 | `enabled=true&targetTemp=<℃>` |
| 方向盘加热开 | POST `/vctrl/v1/controls/steering-wheel/heat` | 否 | `open=true&level=1` |
| 方向盘加热关 | POST `/vctrl/v1/controls/steering-wheel/heat` | 否 | `open=false` |
| 前除霜开/关 | POST `/vctrl/v1/controls/hvac` | 是 | `enabled=<bool>&pos=1` |
| 后除霜开/关 | POST `/vctrl/v1/controls/hvac` | 是 | `enabled=<bool>&pos=2` |

要点：
- `X-Vehicle-Id` 是 B2C 车辆列表里的**数字** vehicleId，不是 VIN。
- 门锁/车窗/天窗走 App 的“非 protect 兜底路径”；App 优先走 protect 证书签名，兜底即上面这些明文 REST。
- `open/close` 语义：`open=true` 是解锁/开，`open=false` 是上锁/关（与 App `doors.door=1/2` 一致）。

## 代码落地

`custom_components/arcfox/api.py`：
- 新增 `_REST_CONTROL_SPECS` 端点表与 `_send_rest_command()`。
- `_send_command()` 在 `command_transport=http`（当前 HA 配置）时走 REST 分支。
- `_request_b2c()` 支持 `check_code=False`（控制接口返回 AppServer 结果码，非 0/200 信封），
  并修复了刷新重试时丢请求头的问题。
- `_ensure_remote_control_token()` 校验安全码并缓存短时效 rcToken（240s）。

## 还差什么（需要用户提供）

1. **App 安全码**：极狐 App 里设置的远程控制安全码（只放 HA 配置，不落仓库）。
2. **B2C 登录**：当前 HA 里的 `access_token` 是 legacy 令牌（已过期/被拒：`API-GATEWAY.4402`），
   需要用新账号重新登录拿 B2C JWT。密码登录还需要 App 的 OAuth `app_token`（client_credentials）。

## 已知/待办

- legacy IOv 只读通道的 token 于 2026-10-16 11:56 起被网关拒绝，只读数据同样需要重新登录恢复。
- 座位加热/通风、唤醒、空调预约等 REST 请求体较复杂，暂未映射到 HTTP 控制分支（当前会明确报“HTTP 不支持”）。
