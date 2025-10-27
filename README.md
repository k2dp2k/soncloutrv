# SonTRV - Smart Thermostat Control

<p align="center">
  <img src="custom_components/soncloutrv/icon.png" alt="SonTRV Logo" width="200"/>
</p>

## Projektbeschreibung

SonTRV ist eine Home Assistant Custom Integration **speziell für Flächenheizungen (Fußbodenheizung)** mit SONOFF TRVZB Thermostaten. Die Integration berücksichtigt die Trägheit von Flächenheizungssystemen und bietet erweiterte Funktionen wie externe Temperatursensoren, 5-Stufen-Ventilsteuerung, intelligente Hysterese und automatischen Verkalkungsschutz.

## 🌟 Features

- ✅ **Externe Temperatursensoren** - Präzise Raumtemperaturmessung statt TRV-interner Sensoren
- 🎯 **Intelligente Hysterese** - Verhindert ständiges Schalten (konfigurierbar: 0,1-2,0°C)
- ⏱️ **Trägheitssteuerung** - Speziell für träge Flächenheizungssysteme optimiert (1-60 Min einstellbar)
- 🔄 **Umschaltbarer Steuermodus** - Binär (An/Aus) oder Proportional (stufenlos)
- 📊 **5 Ventilöffnungsstufen** - Präzise Kontrolle: 0%, 20%, 40%, 60%, 80%, 100%
- 🛡️ **Verkalkungsschutz** - Automatisches Ventil-Durchbewegen alle 7 Tage
- 📈 **Umfangreiche Sensoren** - Ventilposition, Batterie, Temperaturdifferenz, Durchschnitt
- 🔧 **Live-Konfiguration** - Alle Parameter über die UI anpassbar
- 🇩🇪 **Vollständige deutsche Übersetzung**

## Projektstruktur

```
homeassistant-heating-analysis/
├── README.md                           # Diese Datei
├── LICENSE                             # MIT Lizenz
├── hacs.json                           # HACS Manifest
├── custom_components/
│   └── soncloutrv/                    # SonTRV Integration
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── climate.py                 # Hauptthermostat
│       ├── sensor.py                  # 5 Sensoren pro Thermostat
│       ├── number.py                  # Hysterese & Trägheit
│       ├── switch.py                  # Verkalkungsschutz
│       ├── button.py                  # Manuelles Durchbewegen
│       ├── select.py                  # Steuermodus-Auswahl
│       ├── translations/              # DE & EN Übersetzungen
│       ├── icon.png                   # Integration Icon
│       └── README.md                  # Detaillierte Dokumentation
├── README_PLUGIN.md                   # Plugin-Architektur Dokumentation
├── README_WRAPPER.md                  # Wrapper-Konzept Dokumentation
├── README_SONOFF_TRVZB.md            # SONOFF TRVZB spezifische Infos
├── TESTING.md                         # Test-Dokumentation
└── WARP.md                            # Warp AI Kontext
```

## 📦 Installation

### Über HACS (empfohlen)

1. Öffne HACS in Home Assistant
2. Gehe zu "Integrationen"
3. Klicke auf die drei Punkte → "Benutzerdefinierte Repositories"
4. Füge hinzu: `https://github.com/k2dp2k/soncloutrv` (Kategorie: Integration)
5. Suche nach "SonTRV" und installiere es
6. **Starte Home Assistant neu**
7. Gehe zu Einstellungen → Geräte & Dienste → Integration hinzufügen → "SonTRV"

### Manuell

1. Kopiere den Ordner `custom_components/soncloutrv` in dein `config/custom_components/` Verzeichnis
2. Starte Home Assistant neu
3. Füge die Integration über die UI hinzu

## ⚙️ Einrichtung

1. Gehe zu **Einstellungen** → **Geräte & Dienste** → **Integration hinzufügen**
2. Suche nach **"SonTRV"**
3. Folge dem Setup-Assistenten:
   - **Name:** Beliebiger Name (z.B. "TRV_Bad", "TRV_Wohnzimmer")
   - **SONOFF TRVZB Entity:** Wähle dein `climate.heizung_*_fussboden` Entity
   - **Temperatursensor:** Wähle deinen externen Sensor (z.B. `sensor.temperatur_badezimmer`)
   - **Temperaturbereich:** Min/Max Temperatur festlegen
   - **Zieltemperatur:** Standard-Solltemperatur
   - **Ventilöffnungsstufe:** Wähle zwischen * (0%), 1-5 (20%-100%)

4. **Wiederhole** für jeden Raum/Thermostat

## 🎛️ Erstellte Entities pro Thermostat

Nach der Einrichtung werden automatisch erstellt:

### Haupt-Thermostat
- `climate.sontrv_[name]` - Steuerung mit Preset-Modi

### Sensoren (automatisch)
- `sensor.[name]_ventilposition` - Aktuelle Öffnung (0-100%)
- `sensor.[name]_trv_temperatur` - TRV interne Temperatur
- `sensor.[name]_trv_batterie` - Batteriestand
- `sensor.[name]_temperaturdifferenz` - Soll/Ist Differenz
- `sensor.[name]_o_ventilposition` - Durchschnitt
- `sensor.[name]_aktuelle_stufe` - Gewählte Stufe (*, 1-5)

### Einstellungen (Live konfigurierbar)
- `select.[name]_steuermodus` - Binär oder Proportional (Standard: **Proportional**)
- `number.[name]_hysterese` - 0,1-2,0°C (Standard: 0,5°C)
- `number.[name]_tragheit_min_update_intervall` - 1-60 Min (Standard: 10 Min)

### Verkalkungsschutz
- `switch.[name]_verkalkungsschutz` - Auto-Durchbewegen alle 7 Tage
- `button.[name]_ventil_durchbewegen` - Manuelles Durchbewegen

## 🔧 Konfiguration

### Steuermodus

Die Integration unterstützt zwei Steuermodi, die über `select.[name]_steuermodus` umgeschaltet werden können:

**Proportional (stufenlos)** - ✅ **Standard**
- Ventil öffnet graduell basierend auf Temperaturdifferenz
- Bei kleiner Differenz: geringe Öffnung
- Bei großer Differenz (>3°C): maximale Öffnung (gewählte Stufe)
- **Optimal für Fußbodenheizung** - präzisere Temperaturregelung

**Binär (An/Aus):**
- Ventil wird entweder voll geöffnet (auf gewählte Stufe) oder komplett geschlossen
- Einfache Steuerung, gut für sehr träge Systeme
- Keine Zwischenwerte

**Beispiel Proportional-Modus:**
```
Zieltemperatur: 22°C
Aktuelle Temperatur: 20,5°C
Differenz: 1,5°C
Gewählte Stufe: 2 (40% max)

→ Ventilöffnung: ~19% (proportional zur Differenz)
```

### Preset-Modi (Ventilöffnungsstufen)

| Preset | Öffnung | Verwendung |
|--------|---------|------------|
| **\*** | 0% | Ventil geschlossen / Aus |
| **1** | 20% | Minimale Heizleistung |
| **2** | 40% | Niedrige Heizleistung |
| **3** | 60% | Mittlere Heizleistung |
| **4** | 80% | Standard für Fußbodenheizung |
| **5** | 100% | Maximale Heizleistung |

### Empfohlene Einstellungen

**Fußbodenheizung:**
- Steuermodus: **Proportional**
- Hysterese: 0,5-0,7°C
- Trägheit: 15-20 Minuten
- Max. Stufe: 4 (80%)

**Heizkörper:**
- Steuermodus: **Proportional** oder Binär
- Hysterese: 0,3-0,5°C
- Trägheit: 5-10 Minuten
- Max. Stufe: 5 (100%)

## 🤝 Unterstützte Hardware
- **SONOFF TRVZB** (via Zigbee2MQTT oder ZHA)
- Jeder Zigbee/MQTT-fähige TRV mit:
  - `valve_opening_degree` Unterstützung
  - `external_temperature_input` Unterstützung

## 📚 Dokumentation

- **[Integration README](custom_components/soncloutrv/README.md)** - Ausführliche Dokumentation
- **[Validation Summary](VALIDATION.md)** - ✅ Kompatibilitätsprüfung & Validierung
- **[Plugin-Architektur](README_PLUGIN.md)** - Technische Details zur Plugin-Struktur
- **[Wrapper-Konzept](README_WRAPPER.md)** - Wrapper-Pattern Erklärung
- **[SONOFF TRVZB Details](README_SONOFF_TRVZB.md)** - Hardware-spezifische Informationen
- **[Testing](TESTING.md)** - Test-Setup und -Strategie

## 🔧 Services

### `soncloutrv.calibrate_valve`

Führt eine manuelle Ventil-Kalibrierung durch.

```yaml
service: soncloutrv.calibrate_valve
target:
  entity_id: climate.sontrv_bad
```

## ⚡ Startup-Verhalten

**Die Integration wartet automatisch auf Zigbee2MQTT/MQTT:**
- Bis zu **30 Sekunden** Wartezeit auf TRV-Verfügbarkeit
- Liest beim Start alle Sensorwerte (Batterie, Temperatur, Ventilposition)
- Berechnet initiale Ventilöffnung basierend auf Temperaturdifferenz
- Synchronisiert externe Temperatur und Sollwert sofort

**Das bedeutet:**
- Keine fehlenden Sensorwerte nach Neustart
- Ventil startet nicht mehr mit 100%
- Im Proportional-Modus: Direkt der richtige Wert!

## 🐛 Troubleshooting

**Ventil öffnet nur wenig trotz großer Temperaturdifferenz:**
- Prüfe den **Steuermodus**: `select.[name]_steuermodus`
- Setze auf **"proportional"** für stufenlose Regelung
- Im **Binär-Modus** öffnet das Ventil nur voll oder gar nicht

**Ventil reagiert nicht:**
- Prüfe, ob die TRV-Entity korrekt ausgewählt wurde
- Stelle sicher, dass `number.*_valve_opening_degree` existiert

**Temperatur wird nicht übernommen:**
- Prüfe, ob der externe Sensor funktioniert
- Schaue im Log nach "Set external temperature" Meldungen

**Verkalkungsschutz funktioniert nicht:**
- Aktiviere den Switch `switch.*_verkalkungsschutz`
- Der erste Durchlauf erfolgt 7 Tage nach Aktivierung

## 📄 Changelog

### v1.1.0 (2025-10-27) - Production Ready 🚀

**Hauptfeatures:**
- ✨ **Umschaltbarer Steuermodus** - Binär oder Proportional über Select-Entity (mit Auto-Reload)
- ✅ **Proportional als Standard** - Optimiert für Fußbodenheizung mit stufenloser Regelung
- 🎯 **Verkalkungsschutz Standard AN** - Automatischer Schutz ab Installation

**Verbesserungen:**
- ⏳ **MQTT Startup Wait** - Bis zu 30 Sekunden Wartezeit auf TRV-Verfügbarkeit
- 🔋 **Sensor Auto-Detection** - Fallback für verschiedene Sensor-Namensschemas (Z2M/ZHA)
- 🔋 **Batterie-Fix** - Unterstützt `_battery`, `battery`, `_battery_level`
- 🎯 **Intelligente Init** - Berechnet initiale Ventilöffnung basierend auf Temperaturdifferenz
- 📊 **Proxy-Sensoren** - Lesen direkt vom originalen TRV (universell kompatibel)
- 🔧 **Threshold entfernt** - Jede Ventil-Änderung wird angewendet (Trägheit schützt)

**Bugfixes:**
- 🐛 Duplikat DEFAULT_HYSTERESIS entfernt
- 🐛 Sensor Entity-ID Lookup korrigiert
- 🐛 `_battery` Attribut priorisiert

**Kompatibilität:**
- ✅ Home Assistant 2023.1.0+
- ✅ Zigbee2MQTT & ZHA Support
- ✅ Umfassende Error Handling
- ✅ Vollständige Validierung (siehe VALIDATION.md)

### v1.0.0 (2025-10-27)
- ✅ Initial Release
- ✅ Externe Temperatursensoren
- ✅ 5-Stufen Ventilsteuerung
- ✅ Verkalkungsschutz
- ✅ Live-Konfiguration (Hysterese, Trägheit)
- ✅ Umfangreiche Sensoren
- ✅ Vollständige DE/EN Übersetzungen

## 👤 Autor

**k2dp2k**
- GitHub: [@k2dp2k](https://github.com/k2dp2k)
- Repository: [soncloutrv](https://github.com/k2dp2k/soncloutrv)

## 💬 Support

Bei Fragen oder Problemen:
- 🐛 [Issues auf GitHub](https://github.com/k2dp2k/soncloutrv/issues)
- 📝 [Discussions auf GitHub](https://github.com/k2dp2k/soncloutrv/discussions)

## 📝 Lizenz

MIT License - siehe LICENSE Datei

---

<p align="center">
  Made with ❤️ for Home Assistant
</p>
