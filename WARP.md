# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a **Home Assistant configuration analysis project** for a multi-room underfloor heating (Fußbodenheizung) control system. The project contains original YAML configuration files and validation tools to identify errors and suggest improvements.

**Language:** German (documentation) with Home Assistant YAML configurations  
**Purpose:** Configuration analysis, validation, and documentation—not a running application

## Commands

### Validation
```bash
# Validate YAML syntax and check for configuration issues
python3 validate_config.py
# or
./validate_config.py
```

### Home Assistant Configuration Check
```bash
# If Home Assistant CLI is available locally
ha core check

# In Docker container
docker exec homeassistant python -m homeassistant --script check_config -c /config
```

## Architecture

### System Design
This configuration implements a **generic thermostat-based control system** for 6 rooms (Bad, Büro, Flur, Küche, Schlafzimmer, Wohnzimmer) with the following architecture:

1. **Virtual Layer:** Generic Thermostat climate entities that act as controllers
2. **Dummy Switch Layer:** Template switches linked to input_boolean helpers (required by generic_thermostat platform)
3. **Automation Layer:** Translates thermostat heating decisions into physical valve positions
4. **Physical Layer:** Z-Wave/Zigbee valve actuators (`number.heizung_*_fussboden_valve_closing_degree`)

### Key Architecture Pattern: Indirect Valve Control
The system uses **dummy switches** because Home Assistant's `generic_thermostat` platform requires a heater entity (switch) but the physical devices are `number` entities (valve positions 0-100%). The automation layer bridges this gap:

- Thermostat turns dummy switch ON → Automation calculates valve position → Number entity updated
- Temperature sensor → Thermostat logic → Dummy switch state → Valve automation

### Control Logic
**Binary control (not proportional):** Valves are either fully open (max_stufe) or fully closed (0) based on:
- Current temperature vs. target temperature
- Hysteresis zone to prevent oscillation
- Time-based scheduling (optional)
- Global maximum opening percentage limiter

### Known Issues
The configuration has **critical YAML syntax errors** in the dashboard file (incorrect indentation) and a **missing entity reference** (`input_number.fussbodenheizung_druck`). See `FEHLERANALYSE.md` for details.

### Temperature Sensor Conflict
**Küche and Wohnzimmer share the same temperature sensor** (`sensor.temp_wohnzimmer_sb`), which means both rooms will always have identical temperature readings and react in tandem.

## File Structure

- `README.md` - Project overview in German
- `FEHLERANALYSE.md` - Detailed error analysis in German
- `validate_config.py` - Python validation script with YAML syntax checking
- `original/` - Original Home Assistant YAML configurations:
  - `fussboden_heizung.yaml` - Complete package with entities, thermostats, and automations (42KB)
  - `fussboden_dashboard_neu.yaml` - Lovelace dashboard configuration with syntax errors

## Entity Naming Conventions

- **Input helpers:** `fussboden_<room>_<property>` or `fussboden_<global_setting>`
- **Climate entities:** `climate.fussboden_<room>_hk` (HK = Heizkreis)
- **Dummy switches:** `switch.fussboden_heater_<room>_dummy`
- **Physical valves:** `number.heizung_<room>_fussboden_valve_closing_degree`
- **Automations:** `fussboden_thermostat_valve_control_<room>` or `fussboden_sync_*`

## Validation Script Details

`validate_config.py` is a standalone Python 3 script that:
- Checks YAML syntax using PyYAML
- Validates indentation and whitespace
- Verifies automation structure (trigger/action requirements)
- Counts defined input_number, input_boolean, input_select, input_datetime entities
- Lists known issues from manual analysis

The script requires only Python 3's standard library plus PyYAML.
