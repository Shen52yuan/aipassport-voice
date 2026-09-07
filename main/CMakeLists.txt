idf_component_register(
    SRCS "main.c"
         "ui_pixel.c"
         "ui_pixel_math.c"
         "app_state.c"
         "app_protocol.c"
         "app_events.c"
         "app_sound.c"
         "app_ui.c"
         "nvs_settings.c"
         "adpcm.c"
         "audio_streamer.c"
         "ble_audio.c"
         "ble_dtm.c"      # 自 ESP-IDF 5.5.3 拷入:host 层 DTM API 未编入 libbt.a
         "console_cmds.c"
         "time_sync.c"
         "mode.c"
         "usb_link.c"
         "usb_link_framing.c"
         # v0.1.0 汉化:内嵌中文字库(lv_font_conv 生成,Noto Sans CJK SC/OFL)
         "fonts/font_cn_14.c"
         "fonts/font_cn_20.c"
    INCLUDE_DIRS "."
    REQUIRES bsp
             json
             nvs_flash
             console  # IDF >= 5.5: esp_console 组件已重命名为 console
             bt
             esp_pm       # 空闲 light sleep + CPU 变频(录音会话锁见 app_main)
             esp_driver_usb_serial_jtag
)
