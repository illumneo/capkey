idf_component_register(SRCS
                    "app_main.cpp"
                    "touch_processing.cpp"
                    "gestureDetector.cpp"
                    "keyMap.cpp"
                    "capture.cpp"
                    "hid_action.cpp"
                    "hid_completion.cpp"
                    "usb_keyboard.cpp"
                    INCLUDE_DIRS "."
                    REQUIRES esp_driver_touch_sens
                    PRIV_REQUIRES esp_timer esp_app_format esp_tinyusb usb)

if(EXISTS "${SDKCONFIG}")
    file(SHA256 "${SDKCONFIG}" SWIPE_CONFIG_SHA256)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE SWIPE_SDKCONFIG_SHA256="${SWIPE_CONFIG_SHA256}")
endif()

# Stable source identity for the actual processing and key mapping, independent
# of the host replay wrapper and of whether telemetry happens to be attached.
set(SWIPE_RECOGNIZER_IDENTITY "")
foreach(SWIPE_SOURCE capture.cpp capture.h touch_processing.cpp touch_processing.h
                     gestureDetector.cpp gestureDetector.h gestureConfig.h
                     gestureTypes.h gestureLayout.h keyMap.cpp keyMap.h
                     hid_action.cpp hid_action.h hid_completion.cpp hid_completion.h
                     usb_keyboard.cpp usb_keyboard.h)
    file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/${SWIPE_SOURCE}" SWIPE_SOURCE_SHA)
    string(APPEND SWIPE_RECOGNIZER_IDENTITY "${SWIPE_SOURCE}:${SWIPE_SOURCE_SHA}\n")
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
                 "${CMAKE_CURRENT_SOURCE_DIR}/${SWIPE_SOURCE}")
endforeach()
string(SHA256 SWIPE_RECOGNIZER_SHA "${SWIPE_RECOGNIZER_IDENTITY}")
target_compile_definitions(${COMPONENT_LIB} PRIVATE
                          SWIPE_RECOGNIZER_SHA256="${SWIPE_RECOGNIZER_SHA}")
