# SonTRV - Smart Thermostat Control

<p align="center">
  <img src="icon.png" alt="SonTRV Logo" width="200"/>
</p>

<p align="center">
  <strong>Intelligente Thermostatsteuerung speziell für Flächenheizungen (Fußbodenheizung)</strong><br/>
  <em>Optimiert für träge Heizsysteme mit SONOFF TRVZB und externen Temperatursensoren</em>
</p>

---

## 🌟 Features

- ✅ **Externe Temperatursensoren** - Nutze präzise Raumtemperatursensoren statt der eingebauten TRV-Sensoren
- 🎯 **Intelligente Hysterese** - Verhindert ständiges Ein-/Ausschalten durch konfigurierbare Hysterese
- ⏱️ **Trägheitssteuerung** - Speziell für träge Flächenheizungssysteme (Fußbodenheizung) mit langen Reaktionszeiten
- 🔄 **Umschaltbarer Steuermodus** - Binär (An/Aus) oder Proportional (stufenlos) über Select-Entity
- 📊 **5 Ventilöffnungsstufen** - Präzise Kontrolle der Heizleistung (0%, 20%, 40%, 60%, 80%, 100%)
- 🛡️ **Verkalkungsschutz** - Automatisches Ventil-Durchbewegen alle 7 Tage
- 📈 **Umfangreiche Sensoren** - Ventilposition, Batteriestand, Temperaturdifferenz, und mehr
- 🔧 **Live-Konfiguration** - Hysterese, Trägheit und Steuermodus über die UI anpassbar

## 📦 Installation

### HACS (empfohlen)

1. Öffne HACS in Home Assistant
2. Gehe zu "Integrationen"
3. Klicke auf die drei Punkte oben rechts und wähle "Benutzerdefinierte Repositories"
4. Füge `https://github.com/k2dp2k/soncloutrv` hinzu (Kategorie: Integration)
5. Suche nach "SonTRV" und installiere es
6. Starte Home Assistant neu

### Manuell

1. Kopiere den Ordner `custom_components/soncloutrv` in dein Home Assistant `config/custom_components/` Verzeichnis
2. Starte Home Assistant neu

## ⚙️ Einrichtung

1. Gehe zu **Einstellungen** → **Geräte & Dienste**
2. Klicke auf **Integration hinzufügen**
3. Suche nach **SonTRV**
4. Folge dem Setup-Assistenten:
   - Name für den Thermostat
   - SONOFF TRVZB Climate-Entity auswählen
   - Externen Temperatursensor auswählen
   - Temperaturbereich und Zieltemperatur festlegen
   - Maximale Ventilöffnung wählen (Stufe 1-5 oder *)

## 🎛️ Entities

Nach der Einrichtung werden pro Thermostat folgende Entities erstellt:

### Climate Entity
- `climate.trv_[name]` - Haupt-Thermostat mit Temperatursteuerung

### Sensoren
- `sensor.trv_[name]_ventilposition` - Aktuelle Ventilöffnung (%)
- `sensor.trv_[name]_trv_temperatur` - TRV interne Temperatur
- `sensor.trv_[name]_trv_batterie` - Batteriestand des TRV
- `sensor.trv_[name]_temperaturdifferenz` - Differenz Soll/Ist
- `sensor.trv_[name]_o_ventilposition` - Durchschnittliche Ventilposition
- `sensor.trv_[name]_aktuelle_stufe` - Gewählte Stufe (*, 1-5)

### Einstellungen
- `select.trv_[name]_steuermodus` - Steuermodus (Standard: **proportional**)
- `number.trv_[name]_hysterese` - Hysterese einstellen (0,1 - 2,0°C)
- `number.trv_[name]_tragheit_min_update_intervall` - Update-Intervall (1-60 Min)

### Verkalkungsschutz
- `switch.trv_[name]_verkalkungsschutz` - Automatischer Verkalkungsschutz (alle 7 Tage)
- `button.trv_[name]_ventil_durchbewegen` - Manuelles Durchbewegen

## 🔧 Konfiguration

### Steuermodus

**Proportional (stufenlos)** - ✅ **Standard**
- Ventil öffnet graduell basierend auf Temperaturdifferenz
- Bei 1,5°C Differenz und Stufe 2: ~19% Öffnung
- Bei >3°C Differenz: Maximale Öffnung (gewählte Stufe)
- **Optimal für Fußbodenheizung**

**Binär (An/Aus):**
- Ventil wird voll geöffnet oder komplett geschlossen
- Keine Zwischenwerte

### Preset-Modi (Ventilöffnungsstufen)

- **\*** - Ventil geschlossen (0%)
- **1** - 20% Öffnung
- **2** - 40% Öffnung  
- **3** - 60% Öffnung
- **4** - 80% Öffnung (Standard für Fußbodenheizung)
- **5** - 100% Öffnung (Vollgas)

### Hysterese

Die Hysterese verhindert ständiges Schalten bei kleinen Temperaturschwankungen:
- **Standard:** 0,5°C
- **Empfehlung:** 0,3 - 0,7°C für Fußbodenheizung

### Trägheit (Min. Update-Intervall)

Minimale Zeit zwischen Ventil-Anpassungen:
- **Standard:** 10 Minuten
- **Empfehlung:** 10-20 Minuten für Fußbodenheizung, 5 Minuten für Heizkörper

### Empfohlene Kombination für Fußbodenheizung

- **Steuermodus:** Proportional
- **Hysterese:** 0,5-0,7°C
- **Trägheit:** 15-20 Minuten
- **Max. Stufe:** 4 (80%)

## 🛠️ Services

### `soncloutrv.calibrate_valve`

Führt eine manuelle Ventil-Kalibrierung durch.

```yaml
service: soncloutrv.calibrate_valve
target:
  entity_id: climate.trv_bad
```

## 📊 Beispiel-Dashboard

```yaml
type: vertical-stack
cards:
  - type: thermostat
    entity: climate.trv_bad
  - type: entities
    entities:
      - sensor.trv_bad_ventilposition
      - sensor.trv_bad_trv_batterie
      - sensor.trv_bad_temperaturdifferenz
      - select.trv_bad_steuermodus
      - number.trv_bad_hysterese
      - number.trv_bad_tragheit_min_update_intervall
      - switch.trv_bad_verkalkungsschutz
      - button.trv_bad_ventil_durchbewegen
```

## 🤝 Unterstützte Hardware

- **SONOFF TRVZB** (via Zigbee2MQTT oder ZHA)
- Jeder Zigbee/MQTT-fähige TRV mit:
  - `valve_opening_degree` Unterstützung
  - `external_temperature_input` Unterstützung

## 🐛 Troubleshooting

### Ventil reagiert nicht
- Prüfe, ob die TRV-Entity korrekt ist: `climate.heizung_[raum]_fussboden`
- Prüfe, ob die number-Entity existiert: `number.heizung_[raum]_fussboden_valve_opening_degree`

### Temperatur wird nicht übernommen
- Stelle sicher, dass der externe Sensor-Entity existiert
- Prüfe im Log nach "Set external temperature" Meldungen

### Verkalkungsschutz funktioniert nicht
- Aktiviere den Switch `switch.trv_[name]_verkalkungsschutz`
- Der erste Durchlauf erfolgt 7 Tage nach Aktivierung

## 📝 Changelog

### v1.1.0 - Production Ready 🚀
- ✨ Umschaltbarer Steuermodus (binär/proportional) mit Auto-Reload
- ✅ **Proportional als Standard** - Optimiert für Fußbodenheizung
- 🎯 **Verkalkungsschutz default AN**
- ⏳ MQTT Startup Wait (30s) für zuverlässige Initialisierung
- 🔋 Sensor Auto-Detection (Z2M/ZHA kompatibel)
- 🔋 Batterie-Fix: `_battery`, `battery`, `_battery_level`
- 📊 Proxy-Sensoren - lesen vom originalen TRV
- 🎯 Intelligente Ventil-Init basierend auf Temp-Differenz
- 🐛 Bugfixes: Duplikat entfernt, Entity-ID korrigiert
- 📝 Vollständige Validierung (VALIDATION.md)

### v1.0.0
- Initial Release
- Externe Temperatursensoren
- 5-Stufen Ventilsteuerung
- Verkalkungsschutz
- Live-Konfiguration (Hysterese, Trägheit)
- Umfangreiche Sensoren

## 📄 Lizenz

MIT License - siehe LICENSE Datei

## 💬 Support

Bei Fragen oder Problemen erstelle bitte ein Issue auf GitHub:
https://github.com/k2dp2k/soncloutrv/issues

---

<p align="center">
  Made with ❤️ for Home Assistant
</p>
