# Underfloor Heating Control für SONOFF TRVZB

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Eine Home Assistant Custom Component speziell für **SONOFF TRVZB** Zigbee Thermostatventile über **Zigbee2MQTT**.

A Home Assistant Custom Component specifically for **SONOFF TRVZB** Zigbee thermostatic radiator valves via **Zigbee2MQTT**.

## ⚠️ Wichtig / Important

Diese Integration ist **speziell für SONOFF TRVZB** Thermostatventile entwickelt, die über **Zigbee2MQTT** verbunden sind.

## Features / Funktionen

- 🎯 **Direkte TRV-Steuerung** - Steuert SONOFF TRVZB climate entities direkt
- 🔄 **Zwei Steuerungsmodi**:
  - **Binär**: Ein/Aus Steuerung mit Hysterese
  - **Proportional**: Stufenlose Regelung basierend auf Temperaturdifferenz
- ⏰ **Zeitsteuerung** - Optional mit Start- und Endzeit
- 🌡️ **Externer Temperatursensor** - Nutze einen präziseren Sensor statt des TRV-internen Sensors
- 🔧 **UI-Konfiguration** - Alle Parameter über Home Assistant UI einstellbar
- 📊 **Valve Position Monitoring** - Zeigt aktuelle Ventilposition an

## Voraussetzungen / Requirements

1. **Home Assistant** (2024.1.0 oder neuer)
2. **Zigbee2MQTT** Integration installiert und konfiguriert
3. **SONOFF TRVZB** Thermostatventile über Zigbee2MQTT verbunden
4. **Temperatursensor** pro Raum (optional, aber empfohlen)

## Warum diese Integration?

### Problem mit SONOFF TRVZB

SONOFF TRVZB haben einen **internen Temperatursensor**, der jedoch:
- ❌ Direkt am Heizkörper sitzt und dadurch zu hohe Temperaturen misst
- ❌ Nicht die echte Raumtemperatur erfasst
- ❌ Zu frühem Abschalten führt

### Lösung

Diese Integration:
- ✅ Nutzt einen **externen Temperatursensor** für präzise Raumtemperatur
- ✅ Steuert die TRVs basierend auf echter Raumtemperatur
- ✅ Bietet proportionale Regelung für bessere Temperaturstabilität
- ✅ Unterstützt Zeitsteuerung und Hysterese

## Installation

### HACS (Empfohlen)

1. Öffne HACS in Home Assistant
2. Klicke auf "Integrations"
3. Klicke auf das Menü (⋮) und wähle "Custom repositories"
4. Füge die URL hinzu: `https://github.com/yourusername/underfloor-heating-control`
5. Kategorie: "Integration"
6. Installiere "Underfloor Heating Control"
7. Starte Home Assistant neu

### Manuelle Installation

1. Kopiere `custom_components/underfloor_heating_control` nach `config/custom_components/`
2. Starte Home Assistant neu

## Konfiguration

### 1. Integration hinzufügen

**Einstellungen** → **Geräte & Dienste** → **+ Integration hinzufügen** → "Underfloor Heating Control"

### 2. Raum konfigurieren

Für jeden Raum mit SONOFF TRVZB:

#### Erforderlich:

- **Name**: z.B. "Wohnzimmer Heizung"
- **SONOFF TRVZB Thermostat**: Wähle die climate entity des TRV
  - Format: `climate.0xXXXXXXXXXXXXXXXX` oder `climate.wohnzimmer_trv`
- **Temperatursensor**: Externer Sensor für echte Raumtemperatur
  - z.B. `sensor.wohnzimmer_temperature`

#### Optional:

- **Min/Max Temperatur**: Temperaturbereich (6-28°C)
- **Zieltemperatur**: Anfangswert (Standard: 20°C)
- **Hysterese**: Schaltschwelle (Standard: 1.0°C)
- **Max Ventilöffnung**: Begrenzung (Standard: 83%)
- **Steuerungsmodus**: 
  - `binary` - Einfach, bewährt
  - `proportional` - Besser für stabile Temperatur (empfohlen)
- **Zeitsteuerung**: Heizzeiten festlegen

## Verwendung

### Über die UI

Die erstellte Climate Entity verhält sich wie ein normaler Thermostat:
- Zieltemperatur einstellen
- Ein-/Ausschalten
- Ventilposition überwachen

### In Automationen

```yaml
automation:
  - alias: "Morgens aufheizen"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.wohnzimmer_heizung
        data:
          temperature: 22

  - alias: "Nachts reduzieren"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.wohnzimmer_heizung
        data:
          temperature: 18
```

### Szenen

```yaml
scene:
  - name: "Heizung Komfort"
    entities:
      climate.wohnzimmer_heizung:
        temperature: 22
        hvac_mode: heat
      climate.schlafzimmer_heizung:
        temperature: 20
        hvac_mode: heat
  
  - name: "Heizung Sparen"
    entities:
      climate.wohnzimmer_heizung:
        temperature: 18
        hvac_mode: heat
      climate.schlafzimmer_heizung:
        temperature: 16
        hvac_mode: heat
```

## Steuerungsmodi

### Binär-Modus

Klassische Thermostat-Steuerung:
- TRV Zieltemperatur = Deine Zieltemperatur → Heizen aktiv
- TRV Zieltemperatur = Minimum → Heizen aus

**Wann aktiv:**
- Raumtemperatur < (Zieltemperatur - Hysterese) → Heizen
- Raumtemperatur ≥ Zieltemperatur → Aus

### Proportional-Modus (Empfohlen)

Stufenlose Regelung mit sanfteren Übergängen:
- Ventilöffnung proportional zur Temperaturdifferenz
- Weniger Ein/Aus-Schaltungen
- Stabilere Raumtemperatur

## SONOFF TRVZB Besonderheiten

### Attribute die ausgelesen werden:

- `position` oder `valve_position` - Aktuelle Ventilöffnung (0-100%)
- `current_temperature` - Interne TRV-Temperatur (wird ignoriert)
- `local_temperature` - Alternative für interne Temperatur

### Steuerung:

Die Integration steuert das TRV über:
```yaml
service: climate.set_temperature
target:
  entity_id: climate.0xXXXX
data:
  temperature: <berechnet>
```

## Zigbee2MQTT Konfiguration

### Empfohlene Einstellungen in Zigbee2MQTT

Für optimale Performance, konfiguriere das TRVZB in Zigbee2MQTT:

```yaml
# configuration.yaml (Zigbee2MQTT)
devices:
  '0xXXXXXXXXXXXXXXXX':
    friendly_name: 'wohnzimmer_trv'
    # Schnellere Updates für bessere Reaktion
    reporting:
      temperature:
        minimum: 30  # 30 Sekunden
        maximum: 300 # 5 Minuten
```

## Fehlerbehebung

### Integration zeigt keine TRVs

1. Prüfe ob Zigbee2MQTT läuft
2. Prüfe ob TRVZB als `climate` Entity existiert
3. Suche in Developer Tools → States nach `climate.0x`
4. Cache leeren (Shift+F5 im Browser)

### TRV reagiert nicht

1. Prüfe manuell im Developer Tools:
   ```yaml
   service: climate.set_temperature
   target:
     entity_id: climate.0xXXXX
   data:
     temperature: 20
   ```
2. Prüfe Zigbee2MQTT Logs
3. Batterie des TRV prüfen

### Temperatur "springt"

1. Erhöhe Hysterese (z.B. auf 1.5°C)
2. Erhöhe min_cycle_duration (z.B. 600 Sekunden)
3. Nutze Proportional-Modus

### Externe Temperatursensor fehlt

Die Integration **benötigt** einen externen Sensor. Wenn keiner vorhanden:
1. Nutze einen Zigbee/WLAN Temperatursensor
2. Platziere ihn zentral im Raum (nicht am Heizkörper!)

## Vergleich: Vorher vs. Nachher

### Vorher (Nur SONOFF TRVZB)
```
TRV interner Sensor → TRV Thermostat
```
❌ Ungenaue Temperatur (zu nah am Heizkörper)

### Nachher (Mit dieser Integration)
```
Externer Sensor → Diese Integration → TRV Thermostat
```
✅ Präzise Raumtemperatur
✅ Bessere Regelung
✅ Proportionale Steuerung möglich

## Bekannte Limitierungen

1. **TRV-Reaktionszeit**: SONOFF TRVZB haben eine natürliche Verzögerung (mechanisch)
2. **Zigbee2MQTT erforderlich**: Funktioniert nicht mit ZHA
3. **Batteriebetrieben**: TRV-Batterie regelmäßig prüfen
4. **Kein direkter Valve Control**: TRV wird über Zieltemperatur gesteuert, nicht über Position

## Debug-Logging

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.underfloor_heating_control: debug
    homeassistant.components.mqtt: debug
```

## Support

- 🐛 Bug Reports: GitHub Issues
- 💡 Feature Requests: GitHub Discussions  
- 📖 Dokumentation: Wiki

## Lizenz

MIT License

---

**Hinweis**: Ersetze `yourusername` mit deinem GitHub-Benutzernamen vor der Veröffentlichung.
