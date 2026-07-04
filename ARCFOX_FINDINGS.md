# ARCFOX Findings

## Command family `cmd=7`

- `BaicTelematicsSDK.sendCommand(...)` maps `cmd=7` to the `ElectircVehiRmtCtrlControlParse` business code.
- The concrete payload variants are selected by `commandStr` values like:
  - `10070101000101` / `02` / `03`
  - `10070101000201` / `02` / `03`
  - `10070101000401` / `02` / `03`
  - `10070101000801` / `02` / `03`
  - `10070101001601` / `02` / `03`
  - `10070101003201` / `02` / `03`
  - and the matching `...02...04`, `...04...04`, etc. variants for the second branch
- The helper wrappers show the structure:
  - `a.a(...)` sets `group`, `cmd`, `c`
  - `b.a(...)` sets `group`, `cmd`, `c`, `p1`
  - `c.a(...)` sets `group`, `cmd`, `c`, `p2`
- For the `cmd=7` family, the app uses:
  - `group = "7"`
  - `cmd = "1"`
  - `c = "1"` or `"2"` for open/close
  - `p3` / `p8` / `p9` / `p10` / `p11` / `p12` values `1` or `4`
- The previous `group=10 / cmd=7` scaffold in the HA code was wrong for this family and was updated to match the static evidence above.

## MQTT payload behavior

- `BQMqttService.publish46(...)` increments the air-command counter when the command string contains `1002` or equals:
  - `1038010101`
  - `1038010201`
  - `1038010102`
  - `1038010202`
- That strongly suggests these are climate-control-related commands.

## Auth notes

- The HA integration currently authenticates with:
  - `/auth/signin`
  - `/auth/signinsms`
  - `/auth/refreshtoken`
- `findBindUserList` is being called after auth to resolve vehicles.
- In code, token-auth requests now send a compatibility header set:
  - `Authorization: Bearer <token>`
  - `accessToken: <token>`
  - `token: <token>`
  - `X-Access-Token: <token>`
- If VIN is already known but `vehicleConfig` and `carState/query` both fail, the integration now falls back to a minimal vehicle stub so HA can still create the vehicle entity.
- VIN lookup now also tries to salvage vehicle fields from the stored login/auth response before falling back to the stub.
- The entity attributes and diagnostic sensor now expose:
  - `arcfox_connection_source`
  - `arcfox_last_request_path`
  - `arcfox_last_success_path`
  - `arcfox_last_error`
  - `arcfox_authenticated`
  - `arcfox_account_id`
- The control layer no longer uses the fake HTTP command fallback; if MQTT/BCTP is not configured, control actions now fail explicitly instead of returning misleading 404s.
- Earlier failures were caused by:
  - DNS resolution problems in HA
  - then API-side `请求参数错误`
  - then `401 Authentication failed`
- App-side log evidence now shows multiple separate services:
  - `https://sdk.baicmotor.com/service/2/app_log/...`
  - `https://sdk.baicmotor.com/service/2/device_register/...`
  - `https://warden.op-newmall.arcfox.cn/se_address_list`
  - `https://warden.op-newmall.arcfox.cn/se_user_center_account?...`
  - `https://a1-019443ef.easemob.com/1100220606108201/arcfox/token`
- Those URLs look like B2C / account center / analytics / chat token flows.
- They are not the same thing as the vehicle telemetry or remote-control backend.
- The app is likely using them alongside the real car backend, which is still the `sdkserver-*.bjev.com.cn` / MQTT side.
- Router-side packet capture also confirmed a live TLS target on `napi.arcfox.cn`, so the current ARCFOX client now probes both the configured base URL and the app-discovered ARCFOX gateway hostnames.
- APK `assets/config.json` now also confirms the current product/commercial gateway pair:
  - `https://hbt-app-rsa-pre.bjev.com.cn/`
  - `https://hbt-app-rsa.bjev.com.cn/`

## Vehicle status fields

- The app code contains a concrete car-state path:
  - `GET /rc/bctp/carState/query/{vin}`
- The vehicle config path is:
  - `GET /tsp/car/vehicleConfig/{vin}`
- Static APK string analysis shows the car-state payload uses fields that line up with the dashboard data:
  - `gps`
  - `kmTotal`
  - `limitedDriving`
  - `current`
  - `chargingleft`
  - `soc`
  - `insideTemperature`
  - `chrgDchaPwrDisp`
  - `InsdPM25DataDisp`
  - `status.statusDataSendTime`
  - `status.S3` through other `status.S*` flags
- For HA parsing, the numeric values may arrive as strings with units, so the model now strips the first numeric token from values like:
  - `63%`
  - `376 km`
  - `372 km`
- The parser now accepts these field names as candidates:
  - battery pct: `soc`, `chargingleft`, `fuelSoc`, `batteryPct`
  - range: `current`, `limitedDriving`, `rangeKm`, `enduranceMileage`, `kmTotal`
  - odometer: `kmTotal`, `totalMileage`, `mileage`, `odometerKm`
- Remote control failures under a proxy are consistent with direct TLS/MQTT traffic being blocked or certificate-pinned:
  - the app's control layer uses MQTT on `8883` for `emqx-*.bjev.com.cn`
  - HTTP proxy capture will not see that traffic unless the TLS/MQTT path is intercepted successfully
  - if the proxy is only on `8888/8889`, it can explain the "network connection not good" behavior for control operations

## Emulator install note

- `ARCFOX极狐_3.4.28_APKPure.apk` contains only `arm64-v8a` native libraries.
- The current emulator image is `x86_64`, so `adb install` fails with:
  - `INSTALL_FAILED_NO_MATCHING_ABIS`
- This means the APK will not run on the current emulator unless we switch to an ARM-compatible runtime or find an x86/x86_64 build of the app.
