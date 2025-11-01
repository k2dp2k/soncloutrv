# CHANGELOG - SonTRV Integration

## [1.1.1] - 2025-11-01 - Critical Bug Fixes 🔧

### Fixed
- **🔴 CRITICAL: Thermostat unresponsive to temperature changes**
  - `async_set_temperature()` now calls `_async_control_heating()` immediately
  - Previously: Users had to wait 5+ minutes or change preset to trigger heating
  - Now: Heating responds instantly (< 1 second) when target temperature is changed
  - Issue: https://github.com/k2dp2k/soncloutrv/issues/x

- **🔴 CRITICAL: Integration fails to load**
  - Fixed: `CONF_NAME` incorrectly imported from local `const.py` instead of `homeassistant.const`
  - Error message: "cannot import name 'CONF_NAME' from 'custom_components.soncloutrv.const'"
  - Solution: Import `CONF_NAME` from `homeassistant.const` in `sensor.py`

- **🔴 CRITICAL: Event Loop blocking during Valve Exercise**
  - Replaced blocking `asyncio.sleep(300)` with non-blocking `async_call_later()`
  - Duration: 10-minute operation now doesn't freeze Home Assistant
  - Files affected: `switch.py`, `button.py`
  - Implementation: Split exercise into 3 async steps with callbacks

- **🔴 CRITICAL: Entity lookups fail in Number/Switch/Button**
  - Fixed entity ID mismatch between Climate and control entities
  - Issue: Constructed entity IDs didn't match actual entity IDs
  - Solution: Use `_entity_id_base` attribute for reliable entity lookup
  - Impact: Number entities (hysteresis, inertia, gain) now functional

- **🔴 CRITICAL: Timezone-unaware datetime operations**
  - Replaced all `datetime.now()` with `dt_util.now()` for timezone awareness
  - Files affected: `climate.py` (3 locations), `switch.py` (3 locations)
  - Impact: Prevents timing issues in different timezones

### Changed
- **Exception Handling Improvements**
  - Added `try/except` blocks in `__init__.py` platform setup
  - Added exception handling in `number.py`, `switch.py`, `button.py` entity lookups
  - Replaced bare `except:` clauses with specific exception types in `sensor.py`
  - Better error logging with `_LOGGER.error()` and `_LOGGER.debug()`

- **Config Entry Management**
  - Fixed `config_flow.py` to merge (not replace) config data during options update
  - Prevents loss of critical `valve_entity` and `temp_sensor` settings

- **Code Quality**
  - Added proper None checks before operations
  - Added `ZeroDivisionError` handling in efficiency calculations
  - Improved code structure with explicit returns

### Tested
- ✅ Integration loads without errors
- ✅ Temperature changes trigger immediate heating response
- ✅ Valve Exercise doesn't freeze Home Assistant
- ✅ Number entities (hysteresis, inertia) now functional
- ✅ Switch/Button can find climate entity
- ✅ Options update preserves critical settings
- ✅ Timezone-aware time calculations work correctly

### Migration Notes
None required - fully backward compatible with v1.1.0 configurations.

---

## [1.1.0] - 2025-10-27 - Production Ready 🚀

### Added
- **Switchable Control Modes** - Toggle between Binary and Proportional via `select.[name]_steuermodus`
- **Proportional as Default** - Optimized for floor heating with smooth, stepless control
- **Anti-Calcification Protection** - Auto valve exercise every 7 days (enabled by default)
- **Live Configuration** - Adjust hysteresis, inertia, and proportional gain without restart

### Changed
- **Control Mode Selection** - Binary or Proportional mode with auto-reload on change
- **Proportional Mode Default** - Better suited for floor heating thermal dynamics

### Fixed
- Duplicate `DEFAULT_HYSTERESIS` constant removed
- Sensor entity ID lookup improved for Zigbee2MQTT/ZHA compatibility
- Battery attribute handling (`_battery`, `battery`, `_battery_level`)

### Known Issues
None

---

## [1.0.0] - 2025-10-27 - Initial Release

### Added
- ✅ External temperature sensor support
- ✅ 5-step valve control (* = 0%, 1-5 = 20%-100%)
- ✅ Intelligent hysteresis (0.1-2.0°C configurable)
- ✅ Thermal inertia handling (1-60 min configurable)
- ✅ Anti-calcification valve exercise
- ✅ 5 comprehensive diagnostic sensors per thermostat
- ✅ Live configuration (Number entities)
- ✅ Full German and English translations
- ✅ SONOFF TRVZB support (Zigbee2MQTT / ZHA)

### Features
- Wrapper climate entity over SONOFF TRVZB
- External temperature injection via `external_temperature_input`
- Proportional 5-step valve control
- Hysteresis to prevent rapid cycling
- Min update interval for thermal inertia
- Automatic anti-calcification
- Comprehensive diagnostic sensors
- Full UI-based configuration
- No YAML required

### Support
- Home Assistant 2023.1.0+
- SONOFF TRVZB via Zigbee2MQTT or ZHA
- Any Zigbee TRV with `valve_opening_degree` and `external_temperature_input` support

---

# Version Comparison

| Feature | v1.0.0 | v1.1.0 | v1.1.1 |
|---------|--------|--------|--------|
| External Temperature Sensors | ✅ | ✅ | ✅ |
| 5-Step Valve Control | ✅ | ✅ | ✅ |
| Intelligent Hysteresis | ✅ | ✅ | ✅ |
| Control Modes (Binary/Proportional) | ❌ | ✅ | ✅ |
| Anti-Calcification | ✅ | ✅ | ✅ |
| Diagnostic Sensors | ✅ | ✅ | ✅ |
| Live Configuration | ✅ | ✅ | ✅ |
| Immediate Temp Response | ❌ | ❌ | ✅ |
| Timezone-Aware Time | ❌ | ❌ | ✅ |
| Robust Error Handling | ⚠️ | ⚠️ | ✅ |
| Non-Blocking Valve Exercise | ❌ | ❌ | ✅ |

