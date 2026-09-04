#include "py/obj.h"
#include "storage.h"
#include "ZD25WQ80C.h"
#include <string.h>
#include "main.h"

#define PARTITION_START_ADDR  0xE0000 // Last 128KB of 1MB chip
#define NUM_BLOCKS            256     // 128KB / 512 bytes = 256 logical blocks
#define BLOCK_SIZE            512     // FAT block size
#define SEC_SIZE              4096    // Physical sector size of ZD25WQ80C

#define NUM_CACHE_SECTORS     4       // 4 sectors = 16KB LRU cache (prevents FAT/data write-thrashing)

// Expose the global flash driver handle from the template
extern ZD25WQ80C_t flash;

typedef struct {
    uint8_t data[SEC_SIZE];
    uint32_t sector_addr;
    bool dirty;
    uint32_t last_access;
} sector_cache_slot_t;

static sector_cache_slot_t cache[NUM_CACHE_SECTORS];
static volatile uint32_t bdev_last_write_tick = 0;
static bool cache_initialized = false;

static void init_cache_slots(void) {
    if (!cache_initialized) {
        for (int i = 0; i < NUM_CACHE_SECTORS; i++) {
            cache[i].sector_addr = 0xFFFFFFFFU;
            cache[i].dirty = false;
            cache[i].last_access = 0;
        }
        cache_initialized = true;
    }
}

static int ext_flash_init(void) {
    init_cache_slots();
    if (!flash.initialized) {
        // De-initialize first to reset hspi2 state and force MspInit to re-configure GPIO alternate functions
        extern SPI_HandleTypeDef hspi2;
        HAL_SPI_DeInit(&hspi2);

        // Initialize SPI2 peripheral
        extern void MX_SPI2_Init(void);
        MX_SPI2_Init();
        
        // Re-initialize FLASH_CS GPIO Pin (PB12) as output and de-assert it (HIGH)
        __HAL_RCC_GPIOB_CLK_ENABLE();
        GPIO_InitTypeDef GPIO_InitStruct = {0};
        GPIO_InitStruct.Pin = FLASH_CS_Pin;
        GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
        GPIO_InitStruct.Pull = GPIO_NOPULL;
        GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
        HAL_GPIO_Init(FLASH_CS_GPIO_Port, &GPIO_InitStruct);
        HAL_GPIO_WritePin(FLASH_CS_GPIO_Port, FLASH_CS_Pin, GPIO_PIN_SET);
        
        if (!initZD25WQ80C()) {
            return -1;
        }
    }
    return 0;
}

static int flush_slot(int slot_idx) {
    if (cache[slot_idx].dirty && cache[slot_idx].sector_addr != 0xFFFFFFFFU) {
        if (ZD25WQ80C_SectorErase(cache[slot_idx].sector_addr) != HAL_OK) {
            return -1;
        }
        for (uint32_t offset = 0; offset < SEC_SIZE; offset += ZD25WQ80C_PAGE_SIZE) {
            if (ZD25WQ80C_PageProgram(cache[slot_idx].sector_addr + offset, cache[slot_idx].data + offset, ZD25WQ80C_PAGE_SIZE) != HAL_OK) {
                return -1;
            }
        }
        cache[slot_idx].dirty = false;
    }
    return 0;
}

// Flush all dirty sectors in the cache
int ext_flash_flush(void) {
    for (int i = 0; i < NUM_CACHE_SECTORS; i++) {
        if (flush_slot(i) < 0) {
            return -1;
        }
    }
    return 0;
}

// Periodic background check to flush dirty cache safely outside USB interrupt context
void bdev_check_flush(void) {
    bool has_dirty = false;
    for (int i = 0; i < NUM_CACHE_SECTORS; i++) {
        if (cache[i].dirty) {
            has_dirty = true;
            break;
        }
    }
    if (has_dirty && (HAL_GetTick() - bdev_last_write_tick >= 50)) {
        ext_flash_flush();
    }
}

static int get_cache_slot(uint32_t sector_addr) {
    // 1. Check if already cached
    for (int i = 0; i < NUM_CACHE_SECTORS; i++) {
        if (cache[i].sector_addr == sector_addr) {
            cache[i].last_access = HAL_GetTick();
            return i;
        }
    }

    // 2. Find an empty slot
    for (int i = 0; i < NUM_CACHE_SECTORS; i++) {
        if (cache[i].sector_addr == 0xFFFFFFFFU) {
            if (ZD25WQ80C_Read(sector_addr, cache[i].data, SEC_SIZE) != HAL_OK) {
                return -1;
            }
            cache[i].sector_addr = sector_addr;
            cache[i].dirty = false;
            cache[i].last_access = HAL_GetTick();
            return i;
        }
    }

    // 3. Find LRU slot to evict
    int lru_slot = 0;
    uint32_t oldest_access = cache[0].last_access;
    for (int i = 1; i < NUM_CACHE_SECTORS; i++) {
        if (cache[i].last_access < oldest_access) {
            oldest_access = cache[i].last_access;
            lru_slot = i;
        }
    }

    // Flush dirty slot before evicting
    if (flush_slot(lru_slot) < 0) {
        return -1;
    }

    // Load new sector into LRU slot
    if (ZD25WQ80C_Read(sector_addr, cache[lru_slot].data, SEC_SIZE) != HAL_OK) {
        return -1;
    }
    cache[lru_slot].sector_addr = sector_addr;
    cache[lru_slot].dirty = false;
    cache[lru_slot].last_access = HAL_GetTick();
    return lru_slot;
}

volatile bool ext_flash_busy = false;

// Read blocks
int uct_bdev_readblocks(uint8_t *dest, uint32_t block_num, uint32_t num_blocks) {
    ext_flash_busy = true;
    int ret = 0;
    if (ext_flash_init() < 0) {
        ext_flash_busy = false;
        return -1;
    }

    for (uint32_t i = 0; i < num_blocks; i++) {
        uint32_t logical_block = block_num + i;
        uint32_t byte_addr = PARTITION_START_ADDR + logical_block * BLOCK_SIZE;
        uint32_t sector_addr = byte_addr & ~(SEC_SIZE - 1);
        uint32_t sector_offset = byte_addr & (SEC_SIZE - 1);

        // Check cache slots
        int slot = -1;
        for (int s = 0; s < NUM_CACHE_SECTORS; s++) {
            if (cache[s].sector_addr == sector_addr) {
                slot = s;
                cache[s].last_access = HAL_GetTick();
                break;
            }
        }

        if (slot >= 0) {
            memcpy(dest + i * BLOCK_SIZE, cache[slot].data + sector_offset, BLOCK_SIZE);
        } else {
            if (ZD25WQ80C_Read(byte_addr, dest + i * BLOCK_SIZE, BLOCK_SIZE) != HAL_OK) {
                ret = -1;
                break;
            }
        }
    }
    ext_flash_busy = false;
    return ret;
}

// Write blocks
int uct_bdev_writeblocks(const uint8_t *src, uint32_t block_num, uint32_t num_blocks) {
    ext_flash_busy = true;
    int ret = 0;
    if (ext_flash_init() < 0) {
        ext_flash_busy = false;
        return -1;
    }

    for (uint32_t i = 0; i < num_blocks; i++) {
        uint32_t logical_block = block_num + i;
        uint32_t byte_addr = PARTITION_START_ADDR + logical_block * BLOCK_SIZE;
        uint32_t sector_addr = byte_addr & ~(SEC_SIZE - 1);
        uint32_t sector_offset = byte_addr & (SEC_SIZE - 1);

        int slot = get_cache_slot(sector_addr);
        if (slot < 0) {
            ret = -1;
            break;
        }

        memcpy(cache[slot].data + sector_offset, src + i * BLOCK_SIZE, BLOCK_SIZE);
        cache[slot].dirty = true;
        bdev_last_write_tick = HAL_GetTick();
    }

    // Direct synchronous write-through: flush dirty sector to physical flash immediately
    if (ret == 0) {
        ret = ext_flash_flush();
    }

    ext_flash_busy = false;
    return ret;
}

// IOCTL handler
int uct_bdev_ioctl(uint32_t op, uint32_t arg) {
    ext_flash_busy = true;
    int ret = -1;
    switch (op) {
        case BDEV_IOCTL_INIT:
            {
                // Force SPI flash re-initialization to restore GPIO alternate functions after MicroPython pin resets
                extern ZD25WQ80C_t flash;
                flash.initialized = false;
            }
            ret = ext_flash_init();
            break;
        case BDEV_IOCTL_SYNC:
            ret = ext_flash_flush();
            break;
        case BDEV_IOCTL_NUM_BLOCKS:
            ret = NUM_BLOCKS;
            break;
        case BDEV_IOCTL_IRQ_HANDLER:
            ret = ext_flash_flush();
            break;
    }
    ext_flash_busy = false;
    return ret;
}

// Systematically de-initialize custom peripherals and clear/disable NVIC interrupts before soft-reboot
void board_start_soft_reset(void) {
    extern int ext_flash_flush(void);
    ext_flash_flush();
    extern volatile bool mouse_initialized;
    mouse_initialized = false;
    
    // Enable DMA clocks to safely access CCR registers without HardFault
    __HAL_RCC_DMA1_CLK_ENABLE();
    __HAL_RCC_DMA2_CLK_ENABLE();
    
    // Stop all motor PWM actuation immediately if initialized
    if (mouse_initialized) {
        TIM3->CCR3 = 0;
        TIM3->CCR4 = 0;
    }
    
    // Force disable all DMA channels to prevent background transfers during reboot transition
    DMA1_Channel1->CCR &= ~DMA_CCR_EN;
    DMA1_Channel2->CCR &= ~DMA_CCR_EN;
    DMA1_Channel3->CCR &= ~DMA_CCR_EN;
    DMA1_Channel4->CCR &= ~DMA_CCR_EN;
    DMA1_Channel5->CCR &= ~DMA_CCR_EN;
    DMA1_Channel6->CCR &= ~DMA_CCR_EN;
    DMA1_Channel7->CCR &= ~DMA_CCR_EN;
    DMA2_Channel1->CCR &= ~DMA_CCR_EN;
    DMA2_Channel2->CCR &= ~DMA_CCR_EN;
    DMA2_Channel3->CCR &= ~DMA_CCR_EN;
    DMA2_Channel4->CCR &= ~DMA_CCR_EN;
    DMA2_Channel5->CCR &= ~DMA_CCR_EN;
    DMA2_Channel6->CCR &= ~DMA_CCR_EN;
    DMA2_Channel7->CCR &= ~DMA_CCR_EN;
    
    // Disable NVIC interrupts for custom peripherals (keep VCP/USB interrupts active)
    NVIC_DisableIRQ(TIM1_UP_TIM16_IRQn);
    NVIC_DisableIRQ(TIM1_CC_IRQn);
    NVIC_DisableIRQ(TIM3_IRQn);
    NVIC_DisableIRQ(TIM4_IRQn);
    NVIC_DisableIRQ(TIM5_IRQn);
    NVIC_DisableIRQ(TIM6_DAC_IRQn);
    NVIC_DisableIRQ(TIM7_IRQn);
    NVIC_DisableIRQ(ADC1_2_IRQn);
    NVIC_DisableIRQ(DMA1_Channel1_IRQn);
    NVIC_DisableIRQ(DMA2_Channel3_IRQn);
    NVIC_DisableIRQ(DMA2_Channel6_IRQn);
    NVIC_DisableIRQ(DMA2_Channel7_IRQn);
    
    // Clear any pending interrupts to prevent immediately jumping into unmapped handlers in new vector table
    NVIC_ClearPendingIRQ(TIM1_UP_TIM16_IRQn);
    NVIC_ClearPendingIRQ(TIM1_CC_IRQn);
    NVIC_ClearPendingIRQ(TIM3_IRQn);
    NVIC_ClearPendingIRQ(TIM4_IRQn);
    NVIC_ClearPendingIRQ(TIM5_IRQn);
    NVIC_ClearPendingIRQ(TIM6_DAC_IRQn);
    NVIC_ClearPendingIRQ(TIM7_IRQn);
    NVIC_ClearPendingIRQ(ADC1_2_IRQn);
    NVIC_ClearPendingIRQ(DMA1_Channel1_IRQn);
    NVIC_ClearPendingIRQ(DMA2_Channel3_IRQn);
    NVIC_ClearPendingIRQ(DMA2_Channel6_IRQn);
    NVIC_ClearPendingIRQ(DMA2_Channel7_IRQn);
}
