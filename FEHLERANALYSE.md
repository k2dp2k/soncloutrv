# Fehleranalyse: Fußbodenheizung Home Assistant Konfiguration

## Zusammenfassung
Analyse der Dateien `fussboden_dashboard_neu.yaml` und `fussboden_heizung.yaml` für eine Fußbodenheizungssteuerung in Home Assistant.

## Gefundene Fehler

### 1. KRITISCH: YAML Syntax-Fehler im Dashboard (fussboden_dashboard_neu.yaml)

#### Zeile 7: Falsche Einrückung
```yaml
    icon: mdi:view-dashboard
        cards:  # ← FEHLER: 'cards' hat falsche Einrückung (8 Spaces statt 4)
```
**Problem:** Die `cards`-Liste ist zu weit eingerückt. Sie sollte auf derselben Ebene wie `icon` stehen.

**Lösung:**
```yaml
    icon: mdi:view-dashboard
    cards:
```

#### Zeile 10 & 17-18: Falsche Einrückung bei Cards
```yaml
          - type: markdown
        content: |  # ← FEHLER: Sollte 10 Spaces haben, hat aber 8
```
**Problem:** Die `content`-Eigenschaft und andere Card-Eigenschaften sind inkonsistent eingerückt.

**Betroffen:** Zeilen 10, 17-18, 21, 38, 58, 64, 72, 84, 93, 105, 114, 126, 135, 147, 156, 168, 177, 189, 194

**Lösung:** Alle Card-Eigenschaften müssen einheitlich 10 Spaces Einrückung haben:
```yaml
      - type: markdown
        content: |
```

### 2. WARNUNG: Fehlende Entity-Definition im Package (fussboden_heizung.yaml)

#### Zeile 1100: Referenzierte Entity existiert nicht
```yaml
- platform: numeric_state
  entity_id: input_number.fussbodenheizung_druck  # ← FEHLER: Nicht definiert
  above: 50
```
**Problem:** Die Entity `input_number.fussbodenheizung_druck` wird in der Automation `fussboden_druck_warnung` verwendet, aber nirgends in der Konfiguration definiert.

**Lösung:** Entweder die Entity definieren oder die Automation entfernen/deaktivieren.

### 3. POTENTIELLES PROBLEM: Doppelte Temperatursensor-Verwendung

#### Küche und Wohnzimmer teilen sich denselben Sensor
**Zeilen 139 & 180 (Dashboard):**
```yaml
entity: sensor.temp_wohnzimmer_sb  # Für Küche
entity: sensor.temp_wohnzimmer_sb  # Für Wohnzimmer
```

**Zeilen 279 & 309 (Package):**
```yaml
target_sensor: sensor.temp_wohnzimmer_sb  # Küche Thermostat
target_sensor: sensor.temp_wohnzimmer_sb  # Wohnzimmer Thermostat
```

**Problem:** Beide Räume verwenden denselben Temperatursensor. Dies führt dazu, dass beide Thermostate identische Temperaturwerte messen und möglicherweise gleichzeitig reagieren.

**Empfehlung:** Separate Sensoren für Küche und Wohnzimmer verwenden.

### 4. HINWEIS: Ungenutzte Input Select Helper

#### Input Select für Temperatursensoren werden nicht verwendet
**Zeilen 138-184 (fussboden_heizung.yaml):**
```yaml
fussboden_bad_temp_sensor:
  name: Bad Temperatursensor
  options:
    - "Externer Sensor"
    - "Thermostat Sensor"
```

**Problem:** Diese Input Select Helper für alle Räume sind definiert, werden aber nirgends in den Automationen oder Thermostaten verwendet. Die Thermostate haben fest codierte `target_sensor` Werte.

**Empfehlung:** Entweder die Helper entfernen oder Template-Sensoren implementieren, die basierend auf der Auswahl zwischen externem und Thermostat-Sensor wechseln.

### 5. LOGIC-FEHLER: Ventil-Steuerung hat keine Zwischenwerte

#### Binäres On/Off statt proportionaler Steuerung
**Zeilen 476-484 (alle Raum-Automationen):**
```yaml
finale_oeffnung: >
  {% if not heater_on %}
    0
  {% elif isttemperatur >= solltemperatur %}
    0
  {% elif isttemperatur < (solltemperatur - hysterese) %}
    {{ max_stufe }}
  {% else %}
    0
  {% endif %}
```

**Problem:** Die Ventile werden nur voll geöffnet (max_stufe) oder geschlossen (0), es gibt keine Zwischenpositionen. Dies führt zu starken Schwankungen statt sanfter Regelung.

**Empfehlung:** Proportionale Steuerung implementieren basierend auf der Temperaturdifferenz.

### 6. POTENTIAL ISSUE: Anti-Verkalkung ohne Rückstellung

#### Fehlende Rückstellung auf vorherige Ventilposition
**Zeilen 1130-1171 (fussboden_heizung.yaml):**

**Problem:** Nach der Anti-Verkalkung werden die Ventile auf 100% geschlossen gesetzt, aber es gibt keine Logik, die sie wieder auf die vorherigen, von der Steuerung berechneten Positionen zurücksetzt. Die normale Automation wird erst beim nächsten Trigger wieder aktiv.

**Empfehlung:** Nach der Anti-Verkalkung sollten die Automationen manuell getriggert werden oder die Ventilpositionen gespeichert und wiederhergestellt werden.

## YAML-Validierung

### Syntax-Fehler die Home Assistant am Laden hindern werden:
- ✗ Dashboard: Falsche Einrückung bei `cards` (Zeile 7)
- ✗ Dashboard: Inkonsistente Einrückung bei allen Card-Definitionen

### Fehler die zu Runtime-Problemen führen:
- ✗ Package: Fehlende Entity `input_number.fussbodenheizung_druck`

### Logik-Probleme die die Funktion beeinträchtigen:
- ⚠ Doppelter Temperatursensor für Küche/Wohnzimmer
- ⚠ Binäre Ventilsteuerung ohne Proportionalität
- ⚠ Ungenutzte Input Select Helper

## Empfohlene Reihenfolge der Behebung

1. **SOFORT:** YAML-Einrückungsfehler im Dashboard korrigieren
2. **WICHTIG:** Fehlende Entity definieren oder Automation deaktivieren
3. **WICHTIG:** Separate Temperatursensoren für Küche und Wohnzimmer
4. **VERBESSERUNG:** Proportionale Ventilsteuerung implementieren
5. **OPTIONAL:** Ungenutzte Input Select Helper entfernen oder implementieren
6. **OPTIONAL:** Anti-Verkalkung-Rückstellung verbessern

## Validierung

Die Dateien können mit folgenden Tools validiert werden:
```bash
# YAML Syntax
python3 validate_config.py

# Home Assistant Config Check
ha core check

# Oder im Container:
docker exec homeassistant python -m homeassistant --script check_config -c /config
```
