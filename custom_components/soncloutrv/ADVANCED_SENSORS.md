# Advanced Sensors - SonClouTRV v1.2.0

## Übersicht

Version 1.2.0 fügt **17 neue intelligente Sensoren** hinzu, die detaillierte Einblicke in Energieverbrauch, Ventilgesundheit, Temperaturverhalten, Komfort und Systemstatus bieten.

Zusätzlich stellt SonTRV eigene Basis-Sensoren für Ventilöffnung und Ventilschließgrad bereit
(sowohl als Proxy direkt vom TRV als auch als native SonTRV-Sensoren). Die hier beschriebenen
Advanced-Sensoren bauen in vielen Fällen auf diesen Basiswerten auf.

---

## 📊 1. Energieverbrauch & Effizienz (4 Sensoren)

### `sensor.{name}_heizdauer_today`
- **Typ:** Duration (Hours)
- **Beschreibung:** Zeigt, wie viele Stunden heute geheizt wurde (Ventil offen)
- **Reset:** Täglich um Mitternacht
- **Verwendung:** Tages-Heizstatistik, Energieüberwachung

### `sensor.{name}_heizdauer_week`
- **Typ:** Duration (Hours)
- **Beschreibung:** Wöchentliche Heizdauer
- **Reset:** Jeden Montag um Mitternacht
- **Verwendung:** Wochen-Heizstatistik, Trendanalyse

### `sensor.{name}_geschätzte_heizenergie`
- **Typ:** Energy (kWh)
- **Beschreibung:** Geschätzter Energieverbrauch basierend auf Ventilöffnung × Zeit
- **Formel:** `kWh = (Ventil% / 100) × 0.05 kW × Zeit`
- **Attributes:**
  - `power_per_percent_kw`: Einstellung (0.05 kW pro %)
  - `current_power_kw`: Aktuelle Leistung
- **Hinweis:** Der Wert 0.05 kW/% ist ein Schätzwert und sollte an Ihr System angepasst werden

### `sensor.{name}_heizeffizienz`
- **Typ:** Measurement (°C/%)
- **Beschreibung:** Verhältnis zwischen Temperaturänderung und durchschnittlicher Ventilöffnung
- **Interpretation:**
  - Höhere Werte = Effizientere Heizung
  - Niedrige Werte = Schlechte Isolierung oder zu schwache Heizung
- **Attributes:**
  - `temp_change`: Temperaturänderung
  - `avg_valve_opening`: Durchschnittliche Ventilöffnung

---

## 🔧 2. Ventil-Gesundheit & Wartung (3 Sensoren)

### `sensor.{name}_letzte_ventilbewegung`
- **Typ:** Timestamp
- **Beschreibung:** Zeitpunkt der letzten Ventilbewegung (>1% Änderung)
- **Attributes:**
  - `days_since_movement`: Tage seit letzter Bewegung
- **Verwendung:** Verkalkungsschutz-Überwachung

### `sensor.{name}_ventilbewegungen`
- **Typ:** Counter
- **Beschreibung:** Gesamtanzahl der Ventilbewegungen (Lifetime)
- **Verwendung:** Wartungsplanung, Verschleißüberwachung

### `sensor.{name}_ventil_gesamtlaufzeit`
- **Typ:** Duration (Hours)
- **Beschreibung:** Gewichtete Gesamtlaufzeit des Ventils
- **Berechnung:** Zeit × (Ventilöffnung / 100)
- **Verwendung:** Lebensdauer-Tracking, Wartungsintervalle

---

## 🌡️ 3. Temperatur-Analyse (4 Sensoren)

### `sensor.{name}_temperatur_trend`
- **Typ:** State (rising/falling/stable)
- **Beschreibung:** Analysiert Temperaturtrend der letzten 30 Messwerte
- **Icons:**
  - 📈 `rising`: Temperatur steigt (>0.1°C/h)
  - 📉 `falling`: Temperatur fällt (<-0.1°C/h)
  - ➡️ `stable`: Temperatur stabil
- **Attributes:**
  - `change_per_hour`: Änderungsrate in °C/h

### `sensor.{name}_durchschnittstemperatur`
- **Typ:** Temperature (°C)
- **Beschreibung:** Durchschnittstemperatur des aktuellen Tages
- **Reset:** Täglich um Mitternacht
- **Verwendung:** Tages-Temperaturprofil

### `sensor.{name}_minimale_temperatur`
- **Typ:** Temperature (°C)
- **Beschreibung:** Niedrigste Temperatur des Tages
- **Reset:** Täglich um Mitternacht
- **Attributes:**
  - `time`: Zeitpunkt des Minimums
  - `since`: Letzte Zurücksetzung

### `sensor.{name}_maximale_temperatur`
- **Typ:** Temperature (°C)
- **Beschreibung:** Höchste Temperatur des Tages
- **Reset:** Täglich um Mitternacht
- **Attributes:**
  - `time`: Zeitpunkt des Maximums
  - `since`: Letzte Zurücksetzung

---

## 🎯 4. Komfort & Optimierung (3 Sensoren)

### `sensor.{name}_zeit_bis_zieltemperatur`
- **Typ:** Duration (Minutes)
- **Beschreibung:** Geschätzte Zeit bis zum Erreichen der Zieltemperatur
- **Berechnung:** Basierend auf aktueller Aufheiz-/Abkühlrate
- **Werte:**
  - `0`: Zieltemperatur erreicht
  - `1-999`: Geschätzte Minuten
- **Attributes:**
  - `status`: "target_reached", "heating", "cooling"
  - `temp_diff`: Differenz zur Zieltemperatur

### `sensor.{name}_überhitzungswarnung`
- **Typ:** State (ok/warning)
- **Beschreibung:** Warnt, wenn Raumtemperatur >2°C über Zieltemperatur
- **Icons:**
  - ✅ `ok`: Temperatur normal
  - 🔥 `warning`: Überhitzung erkannt
- **Attributes:**
  - `temp_difference`: Differenz zur Zieltemperatur
  - `threshold`: Warnschwelle (2.0°C)

### `sensor.{name}_unterheizungswarnung`
- **Typ:** State (ok/warning)
- **Beschreibung:** Warnt, wenn Ventil >80% offen, aber Temperatur nicht steigt
- **Mögliche Ursachen:**
  - Fenster offen
  - Heizung zu schwach dimensioniert
  - Defekt im System
- **Icons:**
  - ✅ `ok`: System funktioniert
  - ⚠️ `warning`: Problem erkannt

---

## 📡 5. System-Status (3 Sensoren)

### `sensor.{name}_verbindungsstatus`
- **Typ:** State (online/offline)
- **Beschreibung:** MQTT/Zigbee Verbindungsstatus
- **Icons:**
  - 📶 `online`: Verbunden
  - 📵 `offline`: Keine Verbindung
- **Prüfintervall:** Alle 5 Minuten

### `sensor.{name}_letztes_update`
- **Typ:** Timestamp
- **Beschreibung:** Zeitpunkt des letzten empfangenen Updates
- **Attributes:**
  - `minutes_ago`: Minuten seit letztem Update
- **Verwendung:** Verbindungsqualität-Überwachung

### `sensor.{name}_batteriestatus`
- **Typ:** State (Gut/Mittel/Schwach)
- **Beschreibung:** Batteriestatus als Text statt Prozent
- **Werte:**
  - 🔋 **Gut:** >70%
  - 🔋 **Mittel:** 30-70%
  - 🪫 **Schwach:** <30%
- **Attributes:**
  - `battery_level`: Batterie-Prozent
  - `warning`: Warnung bei <15%

---

## 🔧 Anpassung & Konfiguration

### Energieschätzung anpassen

Die Energieberechnung verwendet standardmäßig **0.05 kW pro 1% Ventilöffnung**.

Zur Anpassung an Ihr System bearbeiten Sie in `sensor.py`:

```python
HEATING_POWER_PER_PERCENT = 0.05  # Anpassen an Ihre Heizleistung
```

**Berechnung für Ihr System:**
```
Max. Heizleistung (kW) / 100 = kW pro %

Beispiel: 5 kW Heizleistung
5 / 100 = 0.05 kW pro %
```

---

## 📈 Dashboard-Verwendung

### Energie-Dashboard
```yaml
type: energy-distribution
title: Heizenergie pro Raum
entities:
  - sensor.wohnzimmer_geschätzte_heizenergie
  - sensor.schlafzimmer_geschätzte_heizenergie
  - sensor.bad_geschätzte_heizenergie
```

### Wartungs-Dashboard
```yaml
type: entities
title: Ventil-Wartung
entities:
  - sensor.wohnzimmer_letzte_ventilbewegung
  - sensor.wohnzimmer_ventilbewegungen
  - sensor.wohnzimmer_ventil_gesamtlaufzeit
```

### Temperatur-Analyse
```yaml
type: sensor
entity: sensor.wohnzimmer_temperatur_trend
graph: line
```

### Warnsystem
```yaml
type: glance
title: System-Warnungen
entities:
  - sensor.wohnzimmer_überhitzungswarnung
  - sensor.wohnzimmer_unterheizungswarnung
  - sensor.wohnzimmer_verbindungsstatus
  - sensor.wohnzimmer_batteriestatus
```

---

## 📑 Raum-CSV-Logging (`sontrv_room_log.csv`)

Zusätzlich zu den hier beschriebenen Advanced-Sensoren kann SonTRV optional eine
CSV-Datei mit Raum- und Reglerdaten schreiben (Standardpfad: `sontrv_room_log.csv`
im Home-Assistant-Konfigurationsverzeichnis).

Wichtige Spalten sind u.a.:
- `room_temp`, `target_temp`, `error`
- `room_demand_percent`, `valve_opening_percent`, `max_valve_position`
- `outside_temp`, `outside_sensor`
- `kp`, `ki`, `kd`, `ka`, `pid_p`, `pid_i`, `pid_d`, `pid_ff`, `pid_integral_error`
- `window_freeze_active` – ob ein Fenster-/Freeze-Event aktiv ist
- `window_sensor_open` – ob mindestens ein konfigurierter Fenster-/Türsensor "on" meldet
- `window_sensor_scope` – "local", "all" oder "none"
- `window_sensors` – kommaseparierte Liste der Sensor-Entitäten
- `post_window_soft_active` – ob die sanfte Post-Fenster-Phase aktiv ist

Damit lassen sich z.B. Temperaturverlauf, Heizleistung und Fensterverhalten gemeinsam
auswerten und für spätere ML- oder Dashboard-Analysen verwenden.

---

## 🔔 Automatisierungs-Beispiele

### Verkalkungsschutz-Warnung
```yaml
automation:
  - alias: "Warnung: Ventil bewegen"
    trigger:
      - platform: template
        value_template: >
          {{ (now() - states.sensor.wohnzimmer_letzte_ventilbewegung.state | as_datetime).days > 7 }}
    action:
      - service: notify.mobile_app
        data:
          message: "Ventil Wohnzimmer seit 7 Tagen nicht bewegt - Verkalkungsgefahr!"
```

### Batterie-Warnung
```yaml
automation:
  - alias: "Warnung: Batterie schwach"
    trigger:
      - platform: state
        entity_id: sensor.wohnzimmer_batteriestatus
        to: "Schwach"
    action:
      - service: notify.mobile_app
        data:
          message: "Batterie im TRV Wohnzimmer wechseln!"
```

### Fenster-offen-Erkennung
```yaml
automation:
  - alias: "Warnung: Mögliches offenes Fenster"
    trigger:
      - platform: state
        entity_id: sensor.wohnzimmer_unterheizungswarnung
        to: "warning"
        for:
          minutes: 15
    action:
      - service: notify.mobile_app
        data:
          message: "Fenster Wohnzimmer offen? Ventil voll auf aber Temperatur steigt nicht!"
```

---

## 📝 Hinweise

1. **Performance:** Alle Sensoren sind optimiert für minimalen Ressourcenverbrauch
2. **Persistence:** Zähler und Energiewerte werden bei Neustart wiederhergestellt
3. **Genauigkeit:** Energieschätzungen sind Näherungswerte - für genaue Messungen verwenden Sie Stromzähler
4. **Anpassbarkeit:** Schwellwerte (z.B. Überhitzung 2°C) können im Code angepasst werden

---

## 🆕 Changelog v1.2.0

- ✨ **NEU:** 17 erweiterte Sensoren
- ✨ **NEU:** Energie-Tracking mit kWh-Schätzung
- ✨ **NEU:** Intelligente Warn-Sensoren
- ✨ **NEU:** Temperatur-Trend-Analyse
- ✨ **NEU:** Ventil-Wartungsüberwachung
- ✨ **NEU:** System-Status-Sensoren
- 🔧 **Verbessert:** Logo-Unterstützung im manifest.json
- 📚 **Dokumentation:** Umfassende Sensor-Dokumentation

---

## 📞 Support

Bei Fragen oder Problemen:
- GitHub Issues: https://github.com/k2dp2k/soncloutrv/issues
- Diskussionen: https://github.com/k2dp2k/soncloutrv/discussions
