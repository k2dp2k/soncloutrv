# Home Assistant Fußbodenheizung - Fehleranalyse

## Projektbeschreibung

Dieses Projekt enthält eine detaillierte Analyse der Home Assistant Konfiguration für eine Fußbodenheizungssteuerung. Die Analyse fokussiert sich auf das Auffinden von Fehlern, Inkonsistenzen und Verbesserungspotential.

## Projektstruktur

```
homeassistant-heating-analysis/
├── README.md                           # Diese Datei
├── FEHLERANALYSE.md                    # Detaillierte Fehleranalyse
├── original/                           # Original YAML-Dateien
│   ├── fussboden_dashboard_neu.yaml   # Dashboard-Konfiguration
│   └── fussboden_heizung.yaml         # Package mit Entities & Automationen
└── validate_config.py                  # Python-Script zur YAML-Validierung
```

## Analysierte Dateien

### 1. fussboden_dashboard_neu.yaml
Lovelace Dashboard für die Fußbodenheizung mit:
- Globalen Einstellungen (Max. Stufe, Hysterese, Zeitsteuerung)
- Thermostaten für 6 Räume (Bad, Büro, Flur, Küche, Schlafzimmer, Wohnzimmer)
- Schnellszenen (Komfort, Eco, Nacht, Aus)
- System-Status Anzeige

### 2. fussboden_heizung.yaml
Home Assistant Package mit:
- Input Helper (Number, DateTime, Boolean, Select)
- Template Sensoren
- Generic Thermostat Konfigurationen
- Dummy Switches
- Automationen für Ventilsteuerung
- Sync-Automationen zwischen Thermostat und Input Number
- Anti-Verkalkung Automation
- Scripts für Szenen

## Gefundene Fehler

### Kritische Fehler
- ❌ **YAML Syntax-Fehler** im Dashboard (falsche Einrückung)
- ❌ **Fehlende Entity** `input_number.fussbodenheizung_druck`

### Warnungen
- ⚠️ Doppelte Sensor-Verwendung (Küche & Wohnzimmer)
- ⚠️ Binäre Ventilsteuerung ohne Proportionalität
- ⚠️ Ungenutzte Input Select Helper

Siehe [FEHLERANALYSE.md](./FEHLERANALYSE.md) für Details.

## System-Übersicht

### Unterstützte Räume
1. **Bad** 🚿
   - Sensor: `sensor.temperatur_badezimmer_temperature`
   - Ventil: `number.heizung_bad_fussboden_valve_closing_degree`

2. **Büro** 💼
   - Sensor: `sensor.sbht_003c_a7e0_temperature`
   - Ventil: `number.heizung_buro_fussboden_valve_closing_degree`

3. **Flur** 🚪
   - Sensor: `sensor.indoor_outdoor_meter_280f`
   - Ventil: `number.heizung_flur_fussboden_valve_closing_degree`

4. **Küche** 🍳
   - Sensor: `sensor.temp_wohnzimmer_sb` ⚠️ (geteilt mit Wohnzimmer)
   - Ventil: `number.heizung_kuche_fussboden_valve_closing_degree`

5. **Schlafzimmer** 🛏️
   - Sensor: `sensor.temperatur_schlaf_temperature`
   - Ventil: `number.heizung_schlafzimmer_fussboden_valve_closing_degree`

6. **Wohnzimmer** 🛋️
   - Sensor: `sensor.temp_wohnzimmer_sb` ⚠️ (geteilt mit Küche)
   - Ventil: `number.heizung_wohnzimmer_fussboden_valve_closing_degree`

### Features
- ⚙️ Globale Einstellungen (Hysterese, Max. Öffnungs-Stufe)
- ⏰ Zeitsteuerung mit Start/Ende-Zeit
- 🎯 Szenen: Komfort (22°C), Eco (18°C), Nacht, Aus
- 🔄 Anti-Verkalkung (Wöchentlich Sonntag 03:00)
- 📊 Ventil-Position für jeden Raum
- 🔁 Bidirektionale Sync zwischen UI und Thermostat

## Validierung

### YAML Syntax prüfen
```bash
python3 validate_config.py
```

### Home Assistant Config Check
```bash
# Lokal
ha core check

# Im Docker Container
docker exec homeassistant python -m homeassistant --script check_config -c /config
```

## Empfohlene Nächste Schritte

1. ✅ Fehleranalyse durchgelesen → **FEHLERANALYSE.md**
2. 🔧 YAML-Syntax-Fehler beheben (Dashboard)
3. 🔧 Fehlende Entity hinzufügen oder Automation deaktivieren
4. 🔍 Separate Sensoren für Küche/Wohnzimmer evaluieren
5. 💡 Proportionale Ventilsteuerung implementieren (optional)

## Home Assistant Version

Diese Konfiguration wurde analysiert für:
- Home Assistant Core
- Lovelace Dashboard
- Generic Thermostat Integration

## Lizenz

Dieses Projekt ist eine Analyse der bestehenden Konfiguration und dient ausschließlich zu Dokumentationszwecken.
