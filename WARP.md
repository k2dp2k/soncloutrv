# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a **Home Assistant Custom Integration** for smart thermostat control with SONOFF TRVZB devices, specifically optimized for radiant floor heating (Fußbodenheizung) systems.

**Project Name:** SonTRV  
**Language:** German (documentation) with Python 3.12+ code  
**Purpose:** Production-ready Home Assistant integration installable via HACS  
**Repository:** https://github.com/k2dp2k/soncloutrv

## Commands

### Installation
```bash
# Via HACS (recommended)
# Add custom repository: https://github.com/k2dp2k/soncloutrv
# Install from HACS UI

# Manual installation
cp -r custom_components/soncloutrv /config/custom_components/
```

### Development
```bash
# No specific build/test commands yet
# Integration is tested by installing in Home Assistant

# Check Python syntax (if pylint/ruff available)
pylint custom_components/soncloutrv/
ruff check custom_components/soncloutrv/
```

## Architecture

### System Design
SonTRV is a **Custom Integration** that wraps SONOFF TRVZB climate entities with additional features:

1. **Wrapper Climate Entity:** Custom climate platform that proxies to the underlying TRVZB
2. **External Temperature:** Injects external sensor data via `external_temperature_input`
3. **5-Step Valve Control:** Maps presets (*,1,2,3,4,5) to valve positions (0%, 20%, 40%, 60%, 80%, 100%)
4. **Thermal Inertia Handling:** Configurable min_cycle_duration (1-60 min) for slow-response systems
5. **Anti-Calcification:** Automatic valve exercise every 7 days to prevent sticking

### Key Components

- **climate.py:** Main thermostat wrapper with preset mode control
- **sensor.py:** 5 diagnostic sensors (valve position, TRV temp, battery, temp diff, avg valve)
- **number.py:** Live-configurable hysteresis (0.1-2.0°C) and inertia (1-60 min)
- **switch.py:** Anti-calcification enable/disable
- **button.py:** Manual valve exercise trigger
- **config_flow.py:** UI-based setup wizard

### Control Logic
**Proportional 5-step control:**
- Preset mode determines max valve opening
- Hysteresis prevents rapid cycling
- Min update interval respects thermal inertia
- External temperature sensor for accurate control

### SONOFF TRVZB Entity Requirements
The integration expects these entities from the TRV:
- `climate.*` - Base climate entity
- `number.*_valve_opening_degree` - Valve control (0-100%)
- `number.*_external_temperature_input` - Temperature injection
- `sensor.*_battery` - Battery level
- `sensor.*_local_temperature` - TRV internal sensor

## File Structure

- `README.md` - Project overview in German
- `LICENSE` - MIT License
- `hacs.json` - HACS integration manifest
- `custom_components/soncloutrv/` - Integration code
  - `__init__.py` - Integration setup
  - `manifest.json` - Home Assistant manifest
  - `config_flow.py` - UI configuration wizard
  - `climate.py` - Main thermostat wrapper (ClimateEntity)
  - `sensor.py` - 5 diagnostic sensors per thermostat
  - `number.py` - Hysteresis & inertia number entities
  - `switch.py` - Anti-calcification switch
  - `button.py` - Manual valve exercise button
  - `translations/` - DE & EN translations
  - `icon.png` - Integration icon
  - `README.md` - Detailed integration docs
- `README_PLUGIN.md` - Plugin architecture documentation
- `README_WRAPPER.md` - Wrapper pattern explanation
- `README_SONOFF_TRVZB.md` - SONOFF TRVZB hardware details
- `TESTING.md` - Testing strategy
- `FEHLERANALYSE.md` - Legacy YAML config analysis (archival)

## Entity Naming Conventions

- **Climate entities:** `climate.sontrv_<name>` (user-defined name during setup)
- **Sensors:** `sensor.<name>_ventilposition`, `sensor.<name>_trv_temperatur`, etc.
- **Numbers:** `number.<name>_hysterese`, `number.<name>_tragheit_min_update_intervall`
- **Switch:** `switch.<name>_verkalkungsschutz`
- **Button:** `button.<name>_ventil_durchbewegen`

**Underlying SONOFF TRVZB entities** (referenced during setup):
- `climate.heizung_<room>_fussboden` - Base TRV climate entity
- `number.heizung_<room>_fussboden_valve_opening_degree` - Valve control
- `number.heizung_<room>_fussboden_external_temperature_input` - Temp injection
- `sensor.heizung_<room>_fussboden_battery` - Battery sensor
- `sensor.heizung_<room>_fussboden_local_temperature` - TRV temp sensor

## Integration Features

### Key Features
- **External Temperature Sensors:** Use accurate room sensors instead of TRV-internal sensors
- **5-Step Valve Control:** Preset modes map to valve positions (*, 1-5 = 0%-100%)
- **Intelligent Hysteresis:** Configurable dead band (0.1-2.0°C) to prevent rapid cycling
- **Thermal Inertia:** Min update interval (1-60 min) for slow-response heating systems
- **Anti-Calcification:** Automatic valve exercise every 7 days
- **Live Configuration:** All settings adjustable via UI (number/switch entities)
- **Comprehensive Sensors:** 5 diagnostic sensors per thermostat
- **Full Translations:** German and English UI

### Target Hardware
- **Primary:** SONOFF TRVZB (Zigbee2MQTT or ZHA)
- **Requirements:** TRV must support `valve_opening_degree` and `external_temperature_input`

### Installation Method
- **HACS:** Custom repository (recommended)
- **Manual:** Copy to `custom_components/soncloutrv/`

### Configuration
- **Setup:** Via UI (Settings → Devices & Services → Add Integration → SonTRV)
- **No YAML required:** Fully UI-configurable
