# ARCFOX Findings

## B2C request compatibility update (2026-07-11)

- Added the mobile App's compatibility headers to the shared HTTP transport:
  - `X-Nonce`
  - `X-Client-Version`
- Corrected empty dynamic-info fields to use strings, matching the App.
- The current gateway and route are reachable, but credentials are never
  stored in this document.

## Command family `cmd=7`

- `BaicTelematicsSDK.sendCommand(...)` maps `cmd=7` to the body-control
  business code.
- The command family uses `group=7`, `cmd=1`, and two-state `c` values.
- Action slots are represented by `p3`, `p8`, `p9`, `p10`, `p11`, and `p12`.
- The previous `group=10 / cmd=7` scaffold was corrected to match the static
  protocol evidence.

## MQTT payload behavior

- Climate-related commands use a separate command family from body control.
- The command counter and payload layout are handled by the transport layer.

## B2C and vehicle status paths

- The integration supports the current B2C vehicle and dynamic-info paths as
  experimental read-only routes.
- Status parsing covers battery, range, mileage, charging, climate, location,
  door and vehicle-state fields.
- Runtime credentials, account identifiers, vehicle identifiers, device
  identifiers and authorization values are intentionally excluded from this
  document.

## Remote-control security

- Remote control requires a short-lived security authorization issued by the
  official App service.
- The authorization is refreshed at runtime and is not persisted in source,
  logs or documentation.
- The client also invalidates cached authorization after an account-session
  refresh.

## BCTP framing update

- The App sends a binary BCTP frame containing a protobuf business payload,
  rather than diagnostic JSON.
- The implementation includes the protocol header, service type, timestamp,
  sequence, length and protobuf payload structure.
- Topic generation is selected from the vehicle model at runtime; no concrete
  vehicle identifier is stored here.
- MQTT publishing uses QoS 1 and waits for PUBACK.

## Current implementation status

- Home Assistant entities, config flow, HTTP transport, MQTT publisher and
  BCTP command scaffold are implemented.
- Python compilation and JSON validation pass.
- Final live remote-control validation still requires the App's non-exportable
  client certificate and complete business protobuf encoding.

## Security note

Do not commit any real account, phone, vehicle, device, certificate, password,
security-code or access-token value. Keep those values in local Home Assistant
storage or a local secret store only.
