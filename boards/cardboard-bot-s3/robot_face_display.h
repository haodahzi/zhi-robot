#ifndef _ROBOT_FACE_DISPLAY_H_
#define _ROBOT_FACE_DISPLAY_H_

// 机器人脸 OLED 显示：整块屏幕只画眼睛和嘴巴，不显示状态栏、Wi-Fi 信号、对话文字。
//
// - 表情由大模型通过 SetEmotion 给出，映射到几种脸型（见 FaceFor）
// - 空闲时定时眨眼；机器人说话时嘴巴一张一合
// - 只有“系统提示”（配网热点说明、设备激活验证码、错误提示）才会临时显示文字，
//   这样第一次配网和绑定设备时仍然能看到需要的信息；提示清除后恢复为脸
// - 在 config.h 里把 DISPLAY_FACE_ONLY 改为 0 即可恢复官方的状态栏+文字界面
//
// LVGL 的单色屏里“黑色”就是点亮的像素，所以下面用黑色画眼睛和嘴巴。

#include <cstring>
#include <string>

#include <esp_log.h>
#include <lvgl.h>

#include "application.h"
#include "display/oled_display.h"
#include "lvgl_font.h"
#include "lvgl_theme.h"
#include "system_info.h"

class RobotFaceDisplay : public OledDisplay {
public:
    using OledDisplay::OledDisplay;

    void SetupUI() override {
        if (face_ != nullptr) {
            return;
        }
        OledDisplay::SetupUI();  // 官方界面照常创建，然后用整屏的“脸”盖在上面

        DisplayLockGuard lock(this);
        auto screen = lv_screen_active();

        face_ = lv_obj_create(screen);
        lv_obj_set_size(face_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_pos(face_, 0, 0);
        StyleBare(face_);
        lv_obj_set_style_bg_opa(face_, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(face_, lv_color_white(), 0);

        group_ = lv_obj_create(face_);
        lv_obj_set_size(group_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_pos(group_, 0, 0);
        StyleBare(group_);

        for (int i = 0; i < 2; i++) {
            eye_[i] = lv_obj_create(group_);
            StyleBare(eye_[i]);
            lv_obj_set_style_bg_opa(eye_[i], LV_OPA_COVER, 0);
            lv_obj_set_style_bg_color(eye_[i], lv_color_black(), 0);
            lv_obj_set_style_radius(eye_[i], LV_RADIUS_CIRCLE, 0);
            eye_arc_[i] = MakeArc(group_);
        }
        mouth_arc_ = MakeArc(group_);
        mouth_open_ = lv_obj_create(group_);
        StyleBare(mouth_open_);
        lv_obj_set_style_radius(mouth_open_, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(mouth_open_, 3, 0);
        lv_obj_set_style_border_color(mouth_open_, lv_color_black(), 0);
        mouth_flat_ = lv_obj_create(group_);
        StyleBare(mouth_flat_);
        lv_obj_set_style_bg_opa(mouth_flat_, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(mouth_flat_, lv_color_black(), 0);
        lv_obj_set_style_radius(mouth_flat_, LV_RADIUS_CIRCLE, 0);

        text_label_ = lv_label_create(face_);
        lv_obj_set_width(text_label_, LV_HOR_RES - 8);
        lv_label_set_long_mode(text_label_, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_align(text_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(text_label_, lv_color_black(), 0);
        auto lvgl_theme = static_cast<LvglTheme*>(current_theme_);
        if (lvgl_theme != nullptr && lvgl_theme->text_font() != nullptr) {
            lv_obj_set_style_text_font(text_label_, lvgl_theme->text_font()->font(), 0);
        }
        lv_label_set_text(text_label_, "");
        lv_obj_center(text_label_);
        lv_obj_add_flag(text_label_, LV_OBJ_FLAG_HIDDEN);

        ApplyFace(kEyeOval, kEyeOval, kMouthSmile);
        timer_ = lv_timer_create(
            [](lv_timer_t* t) { static_cast<RobotFaceDisplay*>(lv_timer_get_user_data(t))->OnTick(); },
            120, this);
    }

    // 不显示状态栏文字、通知和对话内容
    void SetStatus(const char* status) override { (void)status; }
    void ShowNotification(const char* notification, int duration_ms = 3000) override {
        (void)notification;
        (void)duration_ms;
    }
    void ShowNotification(const std::string& notification, int duration_ms = 3000) override {
        (void)notification;
        (void)duration_ms;
    }
    void UpdateStatusBar(bool update_all = false) override { (void)update_all; }

    void SetEmotion(const char* emotion) override {
        DisplayLockGuard lock(this);
        if (face_ == nullptr) {
            return;
        }
        FaceFor(emotion == nullptr ? "" : emotion, base_left_, base_right_, base_mouth_);
        if (!listening_) {
            ApplyFace(base_left_, base_right_, base_mouth_);
        }
    }

    // 只有系统提示（配网说明、激活验证码、错误）才临时显示文字
    void SetChatMessage(const char* role, const char* content) override {
        if (role == nullptr || std::strcmp(role, "system") != 0) {
            return;
        }
        DisplayLockGuard lock(this);
        if (face_ == nullptr) {
            return;
        }
        bool has_text = content != nullptr && content[0] != '\0';
        if (has_text && SystemInfo::GetUserAgent() == content) {
            has_text = false;  // 开机时的版本号不显示
        }
        if (has_text) {
            std::string text(content);
            for (auto& c : text) {
                if (c == '\n') c = ' ';
            }
            lv_label_set_text(text_label_, text.c_str());
            lv_obj_center(text_label_);
            lv_obj_add_flag(group_, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(text_label_, LV_OBJ_FLAG_HIDDEN);
            showing_text_ = true;
        } else if (showing_text_) {
            lv_obj_add_flag(text_label_, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(group_, LV_OBJ_FLAG_HIDDEN);
            showing_text_ = false;
        }
    }

private:
    enum EyeStyle { kEyeOval, kEyeWide, kEyeNarrow, kEyeLine, kEyeArcUp, kEyeArcSad };
    enum MouthStyle { kMouthSmile, kMouthBigSmile, kMouthFrown, kMouthFlat, kMouthOpen };

    lv_obj_t* face_ = nullptr;
    lv_obj_t* group_ = nullptr;
    lv_obj_t* eye_[2] = {nullptr, nullptr};
    lv_obj_t* eye_arc_[2] = {nullptr, nullptr};
    lv_obj_t* mouth_arc_ = nullptr;
    lv_obj_t* mouth_open_ = nullptr;
    lv_obj_t* mouth_flat_ = nullptr;
    lv_obj_t* text_label_ = nullptr;
    lv_timer_t* timer_ = nullptr;

    EyeStyle base_left_ = kEyeOval;
    EyeStyle base_right_ = kEyeOval;
    MouthStyle base_mouth_ = kMouthSmile;
    bool listening_ = false;
    EyeStyle eye_style_[2] = {kEyeOval, kEyeOval};
    MouthStyle mouth_style_ = kMouthSmile;
    bool blink_closed_ = false;
    bool talk_open_ = false;
    bool showing_text_ = false;
    int tick_ = 0;

    static void StyleBare(lv_obj_t* obj) {
        lv_obj_set_style_bg_opa(obj, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(obj, 0, 0);
        lv_obj_set_style_outline_width(obj, 0, 0);
        lv_obj_set_style_shadow_width(obj, 0, 0);
        lv_obj_set_style_pad_all(obj, 0, 0);
        lv_obj_set_style_radius(obj, 0, 0);
        lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
    }

    static lv_obj_t* MakeArc(lv_obj_t* parent) {
        lv_obj_t* arc = lv_arc_create(parent);
        lv_obj_remove_style(arc, nullptr, LV_PART_KNOB);
        lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);
        lv_arc_set_rotation(arc, 0);
        lv_obj_set_style_pad_all(arc, 0, 0);
        lv_obj_set_style_arc_opa(arc, LV_OPA_TRANSP, LV_PART_INDICATOR);
        lv_obj_set_style_arc_color(arc, lv_color_black(), LV_PART_MAIN);
        lv_obj_set_style_arc_rounded(arc, true, LV_PART_MAIN);
        lv_obj_add_flag(arc, LV_OBJ_FLAG_HIDDEN);
        return arc;
    }

    static void PlaceArc(lv_obj_t* arc, int cx, int cy, int d, int a0, int a1, int width) {
        lv_obj_set_size(arc, d, d);
        lv_obj_set_pos(arc, cx - d / 2, cy - d / 2);
        lv_arc_set_bg_angles(arc, a0, a1);
        lv_obj_set_style_arc_width(arc, width, LV_PART_MAIN);
        lv_obj_remove_flag(arc, LV_OBJ_FLAG_HIDDEN);
    }

    static void PlaceBox(lv_obj_t* obj, int cx, int cy, int w, int h) {
        lv_obj_set_size(obj, w, h);
        lv_obj_set_pos(obj, cx - w / 2, cy - h / 2);
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
    }

    // 以 64 像素高为基准，按实际屏高缩放纵向尺寸
    int S(int v) const { return v * height_ / 64; }

    static void FaceFor(const std::string& e, EyeStyle& left, EyeStyle& right, MouthStyle& mouth) {
        left = right = kEyeOval;
        mouth = kMouthSmile;
        if (e == "happy" || e == "laughing" || e == "loving" || e == "kissy" || e == "delicious") {
            left = right = kEyeArcUp;
            mouth = (e == "kissy" || e == "delicious") ? kMouthSmile : kMouthBigSmile;
        } else if (e == "funny" || e == "silly" || e == "cool" || e == "confident") {
            mouth = kMouthBigSmile;
        } else if (e == "sad" || e == "crying") {
            left = right = kEyeArcSad;
            mouth = kMouthFrown;
        } else if (e == "embarrassed") {
            left = right = kEyeArcSad;
            mouth = kMouthFlat;
        } else if (e == "angry") {
            left = right = kEyeNarrow;
            mouth = kMouthFrown;
        } else if (e == "surprised" || e == "shocked") {
            left = right = kEyeWide;
            mouth = kMouthOpen;
        } else if (e == "thinking" || e == "confused") {
            mouth = kMouthFlat;
        } else if (e == "sleepy" || e == "relaxed") {
            left = right = kEyeLine;
        } else if (e == "winking") {
            right = kEyeArcUp;
        }
        // 其他（neutral、gear、robot_2 等）都用默认的圆眼睛+小微笑
    }

    void ApplyEye(int i, int cx, int cy) {
        lv_obj_add_flag(eye_[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(eye_arc_[i], LV_OBJ_FLAG_HIDDEN);
        switch (eye_style_[i]) {
            case kEyeOval:
                PlaceBox(eye_[i], cx, cy, 16, blink_closed_ ? 3 : S(26));
                break;
            case kEyeWide:
                PlaceBox(eye_[i], cx, cy, S(22), blink_closed_ ? 3 : S(22));
                break;
            case kEyeNarrow:
                PlaceBox(eye_[i], cx, cy, 20, S(9));
                break;
            case kEyeLine:
                PlaceBox(eye_[i], cx, cy, 18, 3);
                break;
            case kEyeArcUp:
                PlaceArc(eye_arc_[i], cx, cy + S(6), 24, 205, 335, 4);
                break;
            case kEyeArcSad:
                PlaceArc(eye_arc_[i], cx, cy + S(6), 24, 215, 325, 3);
                break;
        }
    }

    void ApplyMouth() {
        lv_obj_add_flag(mouth_arc_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(mouth_open_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(mouth_flat_, LV_OBJ_FLAG_HIDDEN);
        int cx = width_ / 2;
        MouthStyle m = talk_open_ ? kMouthOpen : mouth_style_;
        switch (m) {
            case kMouthSmile:
                PlaceArc(mouth_arc_, cx, S(36), S(26), 30, 150, 3);
                break;
            case kMouthBigSmile:
                PlaceArc(mouth_arc_, cx, S(32), S(34), 20, 160, 3);
                break;
            case kMouthFrown:
                PlaceArc(mouth_arc_, cx, S(54), S(26), 210, 330, 3);
                break;
            case kMouthFlat:
                PlaceBox(mouth_flat_, cx, S(46), 14, 3);
                break;
            case kMouthOpen:
                PlaceBox(mouth_open_, cx, S(46), S(14), S(14));
                break;
        }
    }

    void ApplyEyes() {
        int cx = width_ / 2;
        int ey = S(26);
        ApplyEye(0, cx - 26, ey);
        ApplyEye(1, cx + 26, ey);
    }

    void ApplyFace(EyeStyle left, EyeStyle right, MouthStyle mouth) {
        eye_style_[0] = left;
        eye_style_[1] = right;
        mouth_style_ = mouth;
        blink_closed_ = false;
        ApplyEyes();
        ApplyMouth();
    }

    // 每 120ms 调用一次（在 LVGL 任务内，已持有锁）
    void OnTick() {
        if (showing_text_) {
            return;
        }
        tick_++;

        // 聆听时眼睛睁大,作为“正在听你说话”的提示
        bool listening = Application::GetInstance().GetDeviceState() == kDeviceStateListening;
        if (listening != listening_) {
            listening_ = listening;
            if (listening_) {
                ApplyFace(kEyeWide, kEyeWide, kMouthSmile);
            } else {
                ApplyFace(base_left_, base_right_, base_mouth_);
            }
            return;
        }

        bool changed_eyes = false;
        bool changed_mouth = false;

        bool can_blink = eye_style_[0] == kEyeOval || eye_style_[0] == kEyeWide;
        if (blink_closed_) {
            blink_closed_ = false;
            changed_eyes = true;
        } else if (can_blink && tick_ % 33 == 0) {
            blink_closed_ = true;
            changed_eyes = true;
        }

        bool speaking = Application::GetInstance().GetDeviceState() == kDeviceStateSpeaking;
        bool want_open = speaking && ((tick_ / 2) % 2 == 0);
        if (want_open != talk_open_) {
            talk_open_ = want_open;
            changed_mouth = true;
        }

        if (changed_eyes) ApplyEyes();
        if (changed_mouth) ApplyMouth();
    }
};

#endif  // _ROBOT_FACE_DISPLAY_H_
