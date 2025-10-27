# Underfloor Heating Control

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/yourusername/underfloor-heating-control.svg)](https://github.com/yourusername/underfloor-heating-control/releases)

Eine Home Assistant Custom Component für die Steuerung von Fußbodenheizungen mit direkter Ventilpositionierung.

A Home Assistant Custom Component for controlling underfloor heating systems with direct valve positioning.

## Features / Funktionen

- 🎯 **Direkte Ventilsteuerung** - Steuert number entities (z.B. Z-Wave/Zigbee Ventile) direkt
- 🔄 **Zwei Steuerungsmodi**:
  - **Binär**: Ein/Aus Steuerung mit Hysterese (wie original)
  - **Proportional**: Stufenlose Regelung basierend auf Temperaturdifferenz
- ⏰ **Zeitsteuerung** - Optional mit Start- und Endzeit
- 🌡️ **Flexible Konfiguration** - Alle Parameter über UI einstellbar
- 🔧 **Keine Dummy-Switches nötig** - Direkte Integration ohne Zwischenschicht
- 🔄 **State Restoration** - Behält Einstellungen nach Neustart
- 📊 **Valve Position Attribute** - Zeigt aktuelle Ventilposition an

## Installation

### HACS (Empfohlen / Recommended)

1. Öffne HACS in Home Assistant
2. Klicke auf "Integrations"
3. Klicke auf das Menü (⋮) oben rechts und wähle "Custom repositories"
4. Füge die URL hinzu: `https://github.com/yourusername/underfloor-heating-control`
5. Kategorie: "Integration"
6. Klicke "Add"
7. Suche nach "Underfloor Heating Control" und installiere es
8. Starte Home Assistant neu

### Manuelle Installation

1. Kopiere den `custom_components/underfloor_heating_control` Ordner in dein `config/custom_components` Verzeichnis
2. Starte Home Assistant neu

## Konfiguration / Configuration

### Über die UI

1. Gehe zu **Einstellungen** → **Geräte & Dienste**
2. Klicke auf **+ Integration hinzufügen**
3. Suche nach "Underfloor Heating Control"
4. Folge dem Konfigurationsassistenten:

#### Erforderliche Parameter / Required Parameters

- **Name**: Name für die Heizungssteuerung
- **Ventil Entity**: Die `number` Entity des Ventils (z.B. `number.heizung_bad_fussboden_valve_closing_degree`)
- **Temperatursensor**: Sensor Entity für die Raumtemperatur (z.B. `sensor.temperatur_badezimmer_temperature`)

#### Optionale Parameter / Optional Parameters

- **Minimale/Maximale Temperatur**: Temperaturbereich (Standard: 6-28°C)
- **Zieltemperatur**: Anfängliche Solltemperatur (Standard: 20°C)
- **Hysterese**: Temperaturdifferenz für Ein/Aus-Schaltung (Standard: 1.0°C)
- **Kalt-/Warmtoleranz**: Feinabstimmung der Schaltpunkte (Standard: 0.3°C)
- **Minimale Zyklusdauer**: Mindestzeit zwischen Ventilstellungen in Sekunden (Standard: 300s / 5min)
- **Maximale Ventilöffnung**: Maximale Öffnung in Prozent (Standard: 83%)
- **Steuerungsmodus**: 
  - `binary` - Ein/Aus Steuerung (wie Original)
  - `proportional` - Stufenlose Regelung (empfohlen)
- **Proportionalverstärkung**: Verstärkungsfaktor für proportionale Regelung (Standard: 10.0)
- **Zeitsteuerung**: Optional aktivieren mit Start-/Endzeit

### Beispielkonfiguration / Example Configuration

Für einen Raum "Bad" mit Z-Wave Ventil:

```yaml
# Wird automatisch über UI erstellt / Created automatically via UI
```

Die Integration erstellt eine Climate Entity:
- `climate.underfloor_heating` (oder dein gewählter Name)

Mit Attributen:
- `valve_position`: Aktuelle Ventilöffnung in %
- `control_mode`: binary oder proportional
- `time_control_enabled`: Zeitsteuerung aktiv

## Verwendung / Usage

### Über die UI

Die Climate Entity kann wie jeder andere Thermostat verwendet werden:
- Zieltemperatur einstellen
- Ein-/Ausschalten
- Status und Ventilposition überwachen

### In Automationen

```yaml
automation:
  - alias: "Wohnzimmer Komfort-Modus"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.fussboden_wohnzimmer
        data:
          temperature: 22
```

### Szenen / Scenes

```yaml
scene:
  - name: "Heizung Nacht"
    entities:
      climate.fussboden_bad:
        temperature: 18
        hvac_mode: heat
      climate.fussboden_wohnzimmer:
        temperature: 19
        hvac_mode: heat
```

## Steuerungsmodi / Control Modes

### Binär-Modus (Binary Mode)

Traditionelle Ein/Aus-Steuerung:
- Ventil öffnet voll bei: `Ist-Temp < (Soll-Temp - Hysterese)`
- Ventil schließt bei: `Ist-Temp >= Soll-Temp`
- Hysterese verhindert schnelles Ein/Aus-Schalten

**Vorteile**: Einfach, bewährt
**Nachteile**: Kann zu Temperaturschwankungen führen

### Proportional-Modus (Proportional Mode)

Stufenlose Regelung:
- Ventilöffnung proportional zur Temperaturdifferenz
- Sanftere Temperaturregelung
- Weniger Schwankungen

**Vorteile**: Bessere Temperaturstabilität, Energieeffizienter
**Nachteile**: Komplexer, benötigt evtl. Feintuning

## Anpassung / Customization

Parameter können jederzeit über **Geräte & Dienste** → **Konfigurieren** angepasst werden.

## Vergleich zur Original-Lösung

### Original (fussboden_heizung.yaml)
```
Temperatursensor → Generic Thermostat → Dummy Switch → 
Input Boolean → Automation → Ventil Number Entity
```

### Diese Integration
```
Temperatursensor → Climate Entity → Ventil Number Entity
```

**Vorteile:**
- ✅ Keine Dummy-Switches
- ✅ Keine Input-Helpers
- ✅ Keine komplexen Automationen
- ✅ Keine Sync-Probleme
- ✅ UI-Konfiguration
- ✅ Proportionale Regelung möglich
- ✅ Einfachere Wartung

## Fehlerbehebung / Troubleshooting

### Ventil reagiert nicht

1. Prüfe ob die Ventil-Entity korrekt ist
2. Überprüfe die Logs: **Einstellungen** → **System** → **Protokolle**
3. Stelle sicher dass das Ventil `number` domain ist

### Temperatur wird nicht aktualisiert

1. Prüfe ob der Sensor-Entity korrekt ist
2. Stelle sicher dass der Sensor `device_class: temperature` hat
3. Überprüfe die Sensor-Verfügbarkeit

### Zu viele Ventilbewegungen

1. Erhöhe `min_cycle_duration` (z.B. auf 600 Sekunden)
2. Erhöhe `hysteresis` (z.B. auf 1.5°C)
3. Im Proportional-Modus: Reduziere `proportional_gain`

## Migration von der Original-Lösung

1. **Sichere deine Home Assistant Konfiguration**
2. Installiere diese Integration
3. Konfiguriere für jeden Raum eine neue Climate Entity
4. Teste die Funktion
5. Deaktiviere die alten Automationen
6. Entferne die alten Generic Thermostats, Dummy Switches und Input Helpers

## Debugging

Aktiviere Debug-Logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.underfloor_heating_control: debug
```

## Unterstützung / Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/yourusername/underfloor-heating-control/issues)
- 💡 **Feature Requests**: [GitHub Discussions](https://github.com/yourusername/underfloor-heating-control/discussions)
- 📖 **Dokumentation**: [Wiki](https://github.com/yourusername/underfloor-heating-control/wiki)

## Lizenz / License

MIT License - siehe [LICENSE](LICENSE) Datei

## Danksagungen / Credits

Basierend auf der Original-Analyse des [homeassistant-heating-analysis](https://github.com/yourusername/homeassistant-heating-analysis) Projekts.

---

**Hinweis**: Ersetze `yourusername` mit deinem GitHub-Benutzernamen vor der Veröffentlichung.
