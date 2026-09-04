cmake_minimum_required(VERSION 3.10)

# --- CROSS-COMPILATION TOOLCHAIN SETUP ---
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY arm-none-eabi-objcopy)
set(CMAKE_SIZE arm-none-eabi-size)

# Tell CMake to bypass the executable linker test (avoids bare-metal syscall missing errors)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Global hardware flags required for all targets (Kernel + Python)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -Os -g3 -Wall -Wno-pointer-to-int-cast -Wno-int-to-pointer-cast -Wno-incompatible-pointer-types")
set(CMAKE_ASM_FLAGS "${CMAKE_ASM_FLAGS} -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard")

project(UCT_Micromouse C CXX ASM)

# 1. Build our C proxy kernel library
add_subdirectory(src/kernel)

# 2. Define the main firmware executable target
# Path to Jesse's template repository submodule
set(TEMPLATE_DIR "../external/MicroMouseTemplate/MicroMouseProgramming_Code")

# 3. Dynamically find all source files in Jesse's template
file(GLOB_RECURSE HAL_SOURCES "${TEMPLATE_DIR}/Drivers/STM32L4xx_HAL_Driver/Src/*.c")
if(HAL_SOURCES)
    list(FILTER HAL_SOURCES EXCLUDE REGEX "_template\\.c$")
endif()
file(GLOB_RECURSE CORE_SOURCES "${TEMPLATE_DIR}/Core/Src/*.c")
if(CORE_SOURCES)
    list(FILTER CORE_SOURCES EXCLUDE REGEX "instrumented/")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "Core/Src/main\\.c$")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "Diagnostics_main\\.c$")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "FlashDumper_main\\.c$")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "FlashWriter_main\\.c$")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "Diagnostics_it\\.c$")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "StandaloneFlash_it\\.c$")
    list(FILTER CORE_SOURCES EXCLUDE REGEX "stm32l4xx_it\\.c$")
endif()
file(GLOB_RECURSE USB_SOURCES "${TEMPLATE_DIR}/USB_DEVICE/App/*.c" "${TEMPLATE_DIR}/USB_DEVICE/Target/*.c")
file(GLOB_RECURSE MIDDLEWARE_SOURCES "${TEMPLATE_DIR}/Middlewares/ST/STM32_USB_Device_Library/Core/Src/*.c" "${TEMPLATE_DIR}/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Src/*.c")
file(GLOB_RECURSE PIKA_SOURCES "src/pikascript/pikascript-api/*.c" "src/pikascript/pikascript-core/*.c" "src/pikascript/pikascript-lib/*.c")
list(APPEND PIKA_SOURCES "src/kernel/src/uct_mouse_wrapper.c")
file(GLOB STARTUP_SCRIPT "${TEMPLATE_DIR}/Core/Startup/*.s")

# 3.1 Locate Simulink Autocoded Sources
if(NOT DEFINED SIMULINK_ERT_DIR OR SIMULINK_ERT_DIR STREQUAL "")
    set(SIMULINK_ERT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../build/UCT_KDeploy_ert_rtw")
endif()
file(GLOB SIMULINK_SOURCES "${SIMULINK_ERT_DIR}/*.c")
if(SIMULINK_SOURCES)
    list(FILTER SIMULINK_SOURCES EXCLUDE REGEX "ert_main\\.c")
endif()

# Mute Jesse's application loops so we can supply our own cleanly
set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/${TEMPLATE_DIR}/Core/Src/MicroMouse_main.c" APPEND PROPERTY COMPILE_DEFINITIONS 
    "main=jesse_legacy_main" 
    "HAL_UART_RxCpltCallback=jesse_legacy_uart_callback"
    "HAL_TIM_PeriodElapsedCallback=jesse_legacy_period_elapsed_callback"
    "Error_Handler=jesse_legacy_Error_Handler"
)

set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/${TEMPLATE_DIR}/Core/Src/VCP.c" APPEND PROPERTY COMPILE_DEFINITIONS 
    "HAL_UART_RxCpltCallback=jesse_legacy_uart_callback_vcp"
)

# Common sources and include paths for both targets
set(COMMON_SOURCES
    src/main.c
    src/stm32l4xx_it.c
    ${HAL_SOURCES}
    ${CORE_SOURCES}
    ${USB_SOURCES}
    ${MIDDLEWARE_SOURCES}
    ${STARTUP_SCRIPT}
)

set(COMMON_INCLUDES
    src/kernel/inc
    ${TEMPLATE_DIR}/Core/Inc
    ${TEMPLATE_DIR}/USB_DEVICE/App
    ${TEMPLATE_DIR}/USB_DEVICE/Target
    ${TEMPLATE_DIR}/Drivers/STM32L4xx_HAL_Driver/Inc
    ${TEMPLATE_DIR}/Drivers/STM32L4xx_HAL_Driver/Inc/Legacy
    ${TEMPLATE_DIR}/Drivers/CMSIS/Device/ST/STM32L4xx/Include
    ${TEMPLATE_DIR}/Drivers/CMSIS/Include
    ${TEMPLATE_DIR}/Middlewares/ST/STM32_USB_Device_Library/Core/Inc
    ${TEMPLATE_DIR}/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc
)

set(LINKER_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/${TEMPLATE_DIR}/STM32L476VETX_FLASH.ld")
set(COMMON_LINK_OPTIONS
    -T${LINKER_SCRIPT}
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    -specs=nosys.specs
    -Wl,--gc-sections
)

# --- TARGET 1: PikaScript Firmware ---
add_executable(pikascript_firmware ${COMMON_SOURCES} ${PIKA_SOURCES})
target_compile_definitions(pikascript_firmware PRIVATE USE_HAL_DRIVER USE_FULL_LL_DRIVER STM32L476xx COMPILING_FOR_PIKASCRIPT)
target_include_directories(pikascript_firmware PRIVATE ${COMMON_INCLUDES} src/pikascript/pikascript-api src/pikascript/pikascript-core src/pikascript/pikascript-lib)
target_link_options(pikascript_firmware PRIVATE ${COMMON_LINK_OPTIONS} -Wl,-Map=pikascript_firmware.map)
target_link_libraries(pikascript_firmware PRIVATE uct_kernel m)

# Post-build bin generation for PikaScript
add_custom_command(TARGET pikascript_firmware POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary pikascript_firmware pikascript_firmware.bin
    COMMAND ${CMAKE_COMMAND} -E copy pikascript_firmware.bin ${CMAKE_CURRENT_SOURCE_DIR}/binaries/pikascript.bin
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_SOURCE_DIR}/../build/bin
    COMMAND ${CMAKE_COMMAND} -E copy pikascript_firmware.bin ${CMAKE_CURRENT_SOURCE_DIR}/../build/bin/pikascript.bin
    COMMAND ${CMAKE_SIZE} pikascript_firmware
    COMMENT "Building pikascript_firmware.bin, updating release binary, and printing footprint..."
)

# --- TARGET 2: Simulink Firmware ---
add_executable(simulink_firmware ${COMMON_SOURCES} ${SIMULINK_SOURCES})
target_compile_definitions(simulink_firmware PRIVATE USE_HAL_DRIVER USE_FULL_LL_DRIVER STM32L476xx COMPILING_FOR_SIMULINK)
target_include_directories(simulink_firmware PRIVATE ${COMMON_INCLUDES} "${SIMULINK_ERT_DIR}")
target_link_options(simulink_firmware PRIVATE ${COMMON_LINK_OPTIONS} -Wl,-Map=simulink_firmware.map)
target_link_libraries(simulink_firmware PRIVATE uct_kernel m)

# Post-build bin generation for Simulink
add_custom_command(TARGET simulink_firmware POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary simulink_firmware simulink_firmware.bin
    COMMAND ${CMAKE_COMMAND} -E copy simulink_firmware.bin ${CMAKE_CURRENT_SOURCE_DIR}/binaries/simulink.bin
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_SOURCE_DIR}/../build/bin
    COMMAND ${CMAKE_COMMAND} -E copy simulink_firmware.bin ${CMAKE_CURRENT_SOURCE_DIR}/../build/bin/simulink.bin
    COMMAND ${CMAKE_SIZE} simulink_firmware
    COMMENT "Building simulink_firmware.bin, updating release binary, and printing footprint..."
)

# --- Custom Flash Targets ---
add_custom_target(flash_pika
    COMMAND st-flash --reset write pikascript_firmware.bin 0x08000000
    DEPENDS pikascript_firmware
    COMMENT "Flashing PikaScript firmware and automatically resetting board..."
)

add_custom_target(flash_simulink
    COMMAND st-flash --reset write simulink_firmware.bin 0x08000000
    DEPENDS simulink_firmware
    COMMENT "Flashing Simulink firmware and automatically resetting board..."
)