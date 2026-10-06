# 小纸壳机器人 × 小智

ESP32-S3 + 小智固件的自定义板型 `cardboard-bot-s3`（舵机转头、红外追踪、触摸）。

- `boards/cardboard-bot-s3/`：板型代码（引脚、舵机、红外、MCP 工具）
- `register-board.patch`：把板型注册进上游 `78/xiaozhi-esp32`（基于提交 `0d576d3`）
- `.github/workflows/build-firmware.yml`：云端编译，产物是 `merged-binary.bin`

## 云端编译

推送到本仓库会自动编译；也可以在 Actions 页面手动运行。完成后在运行详情页底部的
Artifacts 下载 `xiaozhi-cardboard-bot-s3`，解压得到 `merged-binary.bin`，刷入地址 `0x0`。

## 调参

方向、角度范围等都在 `boards/cardboard-bot-s3/config.h`，改完推送即可重新编译，不需要动接线。
