#ifndef _BOARD_CONFIG_H_
#define _BOARD_CONFIG_H_

// 小纸壳机器人 · ESP32-S3-N16R8 版
// 主控：ESP32-S3-DevKitC-1 (N16R8)
// 音频：INMP441 麦克风 + MAX98357A 功放（与官方面包板接法一致）
// 外设：SSD1306 OLED、两路红外、TTP223 触摸、水平/俯仰两个舵机
//
// 选脚时已避开：0/3/45/46（启动引脚）、19/20（USB）、
// 26~37（Flash 与八线 PSRAM）、43/44（串口日志）

#include <driver/gpio.h>

// ---------- 音频（与 bread-compact-wifi 相同） ----------
#define AUDIO_INPUT_SAMPLE_RATE  16000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000

#define AUDIO_I2S_MIC_GPIO_WS   GPIO_NUM_4
#define AUDIO_I2S_MIC_GPIO_SCK  GPIO_NUM_5
#define AUDIO_I2S_MIC_GPIO_DIN  GPIO_NUM_6
#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_7
#define AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_15
#define AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_16

// ---------- 按键与指示灯 ----------
#define BUILTIN_LED_GPIO GPIO_NUM_48
#define BOOT_BUTTON_GPIO GPIO_NUM_0

// ---------- OLED（I2C） ----------
#define DISPLAY_SDA_PIN GPIO_NUM_41
#define DISPLAY_SCL_PIN GPIO_NUM_42
#define DISPLAY_WIDTH   128

#if CONFIG_OLED_SSD1306_128X32
#define DISPLAY_HEIGHT 32
#elif CONFIG_OLED_SSD1306_128X64
#define DISPLAY_HEIGHT 64
#elif CONFIG_OLED_SH1106_128X64
#define DISPLAY_HEIGHT 64
#define SH1106
#else
#error "OLED display type is not selected"
#endif

// 画面上下颠倒时把这两项同时改成 false
#define DISPLAY_MIRROR_X true
#define DISPLAY_MIRROR_Y true

// ---------- 触摸 TTP223 ----------
#define TOUCH_GPIO        GPIO_NUM_47
#define TOUCH_ACTIVE_HIGH true   // TTP223 默认触摸时输出高电平

// ---------- 红外（避障/反射式模块，3.3V 供电） ----------
#define IR_LEFT_GPIO    GPIO_NUM_9
#define IR_RIGHT_GPIO   GPIO_NUM_10
#define IR_ACTIVE_LEVEL 0        // 常见模块检测到物体时输出低电平；相反则改为 1

// ---------- 舵机（信号线接 GPIO，电源必须用独立 5V） ----------
#define SERVO_PAN_GPIO  GPIO_NUM_17   // 水平
#define SERVO_TILT_GPIO GPIO_NUM_18   // 俯仰

// 角度均为舵机角度（0~180）。先用保守范围，装好后再按机械结构放宽
#define SERVO_PAN_CENTER  90
#define SERVO_PAN_MIN     40
#define SERVO_PAN_MAX     140
#define SERVO_TILT_CENTER 90
#define SERVO_TILT_MIN    70
#define SERVO_TILT_MAX    115

// 方向装反时把对应项改成 true
#define SERVO_PAN_REVERSE  false
#define SERVO_TILT_REVERSE false

// 红外追踪：左侧红外触发时，水平角度增加(+1)还是减少(-1)
// 语音“看左边”对应角度减小，所以默认 -1，使两者方向一致；
// 方向装反时只改 SERVO_PAN_REVERSE，两者会一起翻转
#define TRACK_LEFT_SIGN (-1)

#endif  // _BOARD_CONFIG_H_
