#ifndef _ROBOT_HEAD_H_
#define _ROBOT_HEAD_H_

// 小纸壳机器人的“头部”：两个舵机 + 两路红外。
// - 后台任务每 20ms 运行一次，负责平滑转动、点头/摇头动作和红外追踪
// - 通过 MCP 工具把动作开放给大模型（对话中可以说“看左边”“点点头”）

#include <atomic>
#include <string>

#include <driver/gpio.h>
#include <driver/ledc.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "config.h"
#include "mcp_server.h"
#include "settings.h"

class RobotHead {
public:
    enum Gesture { kGestureNone = 0, kGestureNod, kGestureShake, kGestureCenter };

    RobotHead() {
        LoadCalibration();
        InitIr();
        InitServos();
        RegisterTools();
        xTaskCreate([](void* arg) { static_cast<RobotHead*>(arg)->Loop(); }, "robot_head", 4096,
                    this, 3, nullptr);
    }

    // 可在任意任务中调用；动作由后台任务执行
    void PlayGesture(Gesture gesture) { gesture_.store(gesture); }

    void SetTracking(bool enable) { tracking_.store(enable); }

    // pan/tilt 为相对中位的偏移角度
    void Look(int pan_offset, int tilt_offset) {
        SetTarget(pan_center_ + pan_offset, tilt_center_ + tilt_offset);
        // 大模型指定方向后，暂停红外追踪 3 秒，避免立刻被拉回；
        // 并让“无目标回中”的计时推迟，使头保持 kVoiceHoldMs 毫秒再回中
        int64_t now = esp_timer_get_time();
        hold_until_us_.store(now + 3000000);
        last_seen_us_.store(now + (int64_t)(kVoiceHoldMs - kRecenterAfterMs) * 1000);
    }

    bool ir_left() const { return gpio_get_level(IR_LEFT_GPIO) == IR_ACTIVE_LEVEL; }
    bool ir_right() const { return gpio_get_level(IR_RIGHT_GPIO) == IR_ACTIVE_LEVEL; }

private:
    static constexpr const char* TAG = "RobotHead";
    static constexpr ledc_timer_t kTimer = LEDC_TIMER_1;
    static constexpr ledc_channel_t kPanChannel = LEDC_CHANNEL_2;
    static constexpr ledc_channel_t kTiltChannel = LEDC_CHANNEL_3;
    static constexpr int kTickMs = 20;
    static constexpr float kCruiseStep = 2.0f;   // 每 20ms 最多转 2°（约 100°/秒）
    static constexpr float kGestureStep = 3.0f;
    static constexpr int kRecenterAfterMs = 5000; // 红外 5 秒无目标则回中
    static constexpr int kVoiceHoldMs = 30000;    // 语音转头后保持 30 秒再回中

    int pan_center_ = SERVO_PAN_CENTER;
    int tilt_center_ = SERVO_TILT_CENTER;

    std::atomic<int> target_pan_{SERVO_PAN_CENTER};
    std::atomic<int> target_tilt_{SERVO_TILT_CENTER};
    std::atomic<int> gesture_{kGestureNone};
    std::atomic<bool> tracking_{true};
    std::atomic<int64_t> hold_until_us_{0};
    std::atomic<int64_t> last_seen_us_{0};

    // 仅后台任务使用
    float pan_ = SERVO_PAN_CENTER;
    float tilt_ = SERVO_TILT_CENTER;
    int stable_count_ = 0;

    int pan_min() const { return pan_center_ - (SERVO_PAN_CENTER - SERVO_PAN_MIN); }
    int pan_max() const { return pan_center_ + (SERVO_PAN_MAX - SERVO_PAN_CENTER); }
    int tilt_min() const { return tilt_center_ - (SERVO_TILT_CENTER - SERVO_TILT_MIN); }
    int tilt_max() const { return tilt_center_ + (SERVO_TILT_MAX - SERVO_TILT_CENTER); }

    static int Clamp(int value, int low, int high) {
        return value < low ? low : (value > high ? high : value);
    }

    void LoadCalibration() {
        Settings settings("cardboard", false);
        pan_center_ = Clamp(settings.GetInt("pan_c", SERVO_PAN_CENTER), 60, 120);
        tilt_center_ = Clamp(settings.GetInt("tilt_c", SERVO_TILT_CENTER), 60, 120);
        target_pan_ = pan_center_;
        target_tilt_ = tilt_center_;
        pan_ = pan_center_;
        tilt_ = tilt_center_;
    }

    void InitIr() {
        gpio_config_t config = {
            .pin_bit_mask = (1ULL << IR_LEFT_GPIO) | (1ULL << IR_RIGHT_GPIO),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = IR_ACTIVE_LEVEL == 0 ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
            .pull_down_en = IR_ACTIVE_LEVEL == 0 ? GPIO_PULLDOWN_DISABLE : GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&config));
    }

    void InitServos() {
        ledc_timer_config_t timer = {.speed_mode = LEDC_LOW_SPEED_MODE,
                                     .duty_resolution = LEDC_TIMER_14_BIT,
                                     .timer_num = kTimer,
                                     .freq_hz = 50,
                                     .clk_cfg = LEDC_AUTO_CLK};
        ESP_ERROR_CHECK(ledc_timer_config(&timer));

        InitChannel(kPanChannel, SERVO_PAN_GPIO);
        InitChannel(kTiltChannel, SERVO_TILT_GPIO);
        WriteServos();
    }

    void InitChannel(ledc_channel_t channel, gpio_num_t gpio) {
        ledc_channel_config_t config = {.gpio_num = gpio,
                                        .speed_mode = LEDC_LOW_SPEED_MODE,
                                        .channel = channel,
                                        .intr_type = LEDC_INTR_DISABLE,
                                        .timer_sel = kTimer,
                                        .duty = 0,
                                        .hpoint = 0};
        ESP_ERROR_CHECK(ledc_channel_config(&config));
    }

    // 0~180° 对应 500~2500us 脉宽，周期 20ms，14 位分辨率
    static void WriteAngle(ledc_channel_t channel, float angle, bool reverse) {
        if (reverse) {
            angle = 180.0f - angle;
        }
        float pulse_us = 500.0f + angle / 180.0f * 2000.0f;
        uint32_t duty = (uint32_t)(pulse_us * 16384.0f / 20000.0f);
        ledc_set_duty(LEDC_LOW_SPEED_MODE, channel, duty);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, channel);
    }

    void WriteServos() {
        WriteAngle(kPanChannel, pan_, SERVO_PAN_REVERSE);
        WriteAngle(kTiltChannel, tilt_, SERVO_TILT_REVERSE);
    }

    void SetTarget(int pan, int tilt) {
        target_pan_.store(Clamp(pan, pan_min(), pan_max()));
        target_tilt_.store(Clamp(tilt, tilt_min(), tilt_max()));
    }

    static float Approach(float current, float target, float step) {
        if (target > current + step) return current + step;
        if (target < current - step) return current - step;
        return target;
    }

    // 向目标角度走一步；已到位返回 true
    bool Step(float step) {
        float target_pan = target_pan_.load();
        float target_tilt = target_tilt_.load();
        if (pan_ == target_pan && tilt_ == target_tilt) {
            return true;
        }
        pan_ = Approach(pan_, target_pan, step);
        tilt_ = Approach(tilt_, target_tilt, step);
        WriteServos();
        return false;
    }

    // 仅在后台任务内使用：阻塞直到转到指定角度
    void MoveTo(int pan, int tilt, float step) {
        SetTarget(pan, tilt);
        while (!Step(step)) {
            vTaskDelay(pdMS_TO_TICKS(kTickMs));
        }
        vTaskDelay(pdMS_TO_TICKS(60));
    }

    void RunGesture(int gesture) {
        int pan = target_pan_.load();
        int tilt = target_tilt_.load();
        switch (gesture) {
            case kGestureNod:
                for (int i = 0; i < 2; i++) {
                    MoveTo(pan, tilt - 12, kGestureStep);
                    MoveTo(pan, tilt + 8, kGestureStep);
                }
                MoveTo(pan, tilt, kGestureStep);
                break;
            case kGestureShake:
                for (int i = 0; i < 2; i++) {
                    MoveTo(pan - 18, tilt, kGestureStep);
                    MoveTo(pan + 18, tilt, kGestureStep);
                }
                MoveTo(pan, tilt, kGestureStep);
                break;
            case kGestureCenter:
                MoveTo(pan_center_, tilt_center_, kCruiseStep);
                break;
            default:
                break;
        }
        last_seen_us_.store(esp_timer_get_time());
    }

    // 只有一侧红外触发时朝那一侧转；两侧都触发说明已正对，保持不动
    void UpdateTracking() {
        int64_t now = esp_timer_get_time();
        bool left = ir_left();
        bool right = ir_right();

        if (left != right) {
            last_seen_us_.store(now);
            // 连续 3 次（60ms）读数一致才动作，过滤抖动
            if (++stable_count_ >= 3) {
                int direction = left ? TRACK_LEFT_SIGN : -TRACK_LEFT_SIGN;
                SetTarget(target_pan_.load() + direction, target_tilt_.load());
            }
            return;
        }

        stable_count_ = 0;
        if (left && right) {
            last_seen_us_.store(now);
        } else if (now - last_seen_us_.load() > (int64_t)kRecenterAfterMs * 1000) {
            SetTarget(pan_center_, tilt_center_);
        }
    }

    void Loop() {
        last_seen_us_.store(esp_timer_get_time());
        while (true) {
            int gesture = gesture_.exchange(kGestureNone);
            if (gesture != kGestureNone) {
                RunGesture(gesture);
            } else if (tracking_.load() && esp_timer_get_time() > hold_until_us_.load()) {
                UpdateTracking();
            }
            Step(kCruiseStep);
            vTaskDelay(pdMS_TO_TICKS(kTickMs));
        }
    }

    void RegisterTools() {
        auto& mcp_server = McpServer::GetInstance();

        mcp_server.AddTool(
            "self.head.look",
            "转动机器人的头。pan 为水平偏移角度（负数向左，正数向右，0 为正前方）；"
            "tilt 为俯仰偏移角度（负数低头，正数抬头）。",
            PropertyList({Property("pan", kPropertyTypeInteger, 0, -50, 50),
                          Property("tilt", kPropertyTypeInteger, 0, -20, 25)}),
            [this](const PropertyList& properties) -> ReturnValue {
                Look(properties["pan"].value<int>(), properties["tilt"].value<int>());
                return true;
            });

        mcp_server.AddTool(
            "self.head.gesture",
            "让机器人做一个头部动作。action 可选：nod（点头，表示同意或打招呼）、"
            "shake（摇头，表示否定）、center（回到正前方）。",
            PropertyList({Property("action", kPropertyTypeString)}),
            [this](const PropertyList& properties) -> ReturnValue {
                std::string action = properties["action"].value<std::string>();
                if (action == "nod") {
                    PlayGesture(kGestureNod);
                } else if (action == "shake") {
                    PlayGesture(kGestureShake);
                } else if (action == "center") {
                    PlayGesture(kGestureCenter);
                } else {
                    return std::string("{\"error\": \"unknown action\"}");
                }
                return true;
            });

        mcp_server.AddTool(
            "self.head.set_tracking",
            "打开或关闭红外追踪。打开后，机器人的头会自动转向靠近它的手或物体。",
            PropertyList({Property("enable", kPropertyTypeBoolean)}),
            [this](const PropertyList& properties) -> ReturnValue {
                SetTracking(properties["enable"].value<bool>());
                return true;
            });

        mcp_server.AddTool(
            "self.head.get_state",
            "读取机器人头部状态：当前水平/俯仰偏移角度、左右红外是否检测到物体、追踪是否开启。",
            PropertyList(), [this](const PropertyList& properties) -> ReturnValue {
                std::string json = "{\"pan\": " + std::to_string(target_pan_.load() - pan_center_) +
                                   ", \"tilt\": " +
                                   std::to_string(target_tilt_.load() - tilt_center_) +
                                   ", \"ir_left\": " + (ir_left() ? "true" : "false") +
                                   ", \"ir_right\": " + (ir_right() ? "true" : "false") +
                                   ", \"tracking\": " + (tracking_.load() ? "true" : "false") + "}";
                return json;
            });

        mcp_server.AddTool(
            "self.head.calibrate",
            "校准舵机中位并保存，仅在用户明确要求校准时使用。参数为舵机角度（90 为理论中位）。",
            PropertyList({Property("pan_center", kPropertyTypeInteger, 90, 60, 120),
                          Property("tilt_center", kPropertyTypeInteger, 90, 60, 120)}),
            [this](const PropertyList& properties) -> ReturnValue {
                pan_center_ = properties["pan_center"].value<int>();
                tilt_center_ = properties["tilt_center"].value<int>();
                Settings settings("cardboard", true);
                settings.SetInt("pan_c", pan_center_);
                settings.SetInt("tilt_c", tilt_center_);
                PlayGesture(kGestureCenter);
                return true;
            });
    }
};

#endif  // _ROBOT_HEAD_H_
