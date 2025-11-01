# Fehleranalyse: SonTRV Custom Integration für Home Assistant

## Kritische Fehler (Blocker)

### 1. **KRITISCH: Falscher Config Key in sensor.py (Line 45)**
```python
valve_entity = config_entry.data.get('valve_entity')  # ❌ FALSCH
```
**Problem:** Der Config Key ist `valve_entity`, aber in `const.py` und `config_flow.py` ist es definiert als `CONF_VALVE_ENTITY` (Standard: `"valve_entity"`). Dies sollte konsistent sein.

**Auswirkung:** Sensor Platform wird nicht korrekt initialisiert, alle Sensoren fallen aus.

**Fix:**
```python
valve_entity = config_entry.data.get(CONF_VALVE_ENTITY)  # ✅ RICHTIG
```

---

### 2. **KRITISCH: Falsche Entity ID Konstruktion in climate.py (Line 119)**
```python
climate_entity_id = f"climate.{self._config_entry.data['name'].lower().replace(' ', '_')}"
```

**Problem:** 
- Der `name` aus `config_entry.data` wird verwendet, um die climate entity ID zu generieren
- Aber die echte Entity ID wird mit `entry_id` generiert (Line 126: `unique_id = f"{DOMAIN}_{entry_id}"`)
- Diese stimmen nicht überein → Entity Lookups fehlschlag

**Auswirkung:** 
- Number entities können die climate entity nicht finden (number.py Line 122)
- Switch und Button entities können die climate entity nicht finden

**Beispiel Fehler:**
- Name: `"Wohnzimmer Heizung"`
- Erwartete Entity ID: `climate.wohnzimmer_heizung`
- Eindeutige ID: `soncloutrv_<entry_id>`
- → Mismatch!

**Fix:**
```python
# Konsistente Entity ID Konstruktion überall
entity_id = f"climate.{DOMAIN}_{self._entry_id}"
```

---

### 3. **KRITISCH: Async Fehler in switch.py & button.py - asyncio.sleep() in nicht-async Context**

**Problem:** In `switch.py` (Line 149, 154) und `button.py` (Line 78, 83):
```python
async def _async_exercise_valve(self) -> None:
    ...
    await asyncio.sleep(300)  # ❌ Blockiert den Event Loop für 5 Minuten!
```

**Auswirkung:**
- Blockiert den gesamten Home Assistant Event Loop für 10 Minuten
- Home Assistant wird komplett eingefroren
- Andere Automationen/Dienste können nicht laufen
- Timeout-Fehler bei anderen Komponenten

**Fix:**
```python
from homeassistant.helpers.event import async_call_later

async def _async_exercise_valve(self) -> None:
    ...
    # Step 1: Open
    await entity._async_set_valve_opening(100)
    _LOGGER.info("%s: Valve opened, scheduled close in 5 minutes", entity.name)
    
    # Schedule close nach 5 Min (nicht blockierend!)
    async_call_later(self.hass, 300, self._async_step_2, entity)
    
async def _async_step_2(self, entity):
    await entity._async_set_valve_opening(0)
    async_call_later(self.hass, 300, self._async_step_3, entity)
```

---

## Schwerwiegende Fehler

### 4. **SCHWER: Falscher DateTime.now() in switch.py (Line 111)**
```python
current_time = datetime.now()  # ❌ Nicht Home Assistant aware
```

**Problem:**
- Keine Timezone Information
- Home Assistant kann in verschiedenen Zeitzonen laufen
- Vergleich mit `weekday()` und `hour` ist unreliabel

**Fix:**
```python
from homeassistant.util import dt as dt_util

current_time = dt_util.now()  # ✅ Home Assistant aware
```

---

### 5. **SCHWER: Unhandled Exception in number.py (Line 122-134)**
```python
for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
    if entity.entity_id == climate_entity_id:  # ❌ climate_entity_id ist falsch konstruiert!
        ...
```

**Problem:**
- Die Entity ID Konstruktion ist falsch (siehe Fehler #2)
- Die Schleife findet die Entity nie
- Wert wird gespeichert, aber nicht auf die Climate Entity angewendet
- Alle Number Entities sind wirkungslos

**Auswirkung:** Hysterese, min_valve_update_interval und proportional_gain Änderungen haben keine Wirkung

---

### 6. **SCHWER: Config Entry Data wird nicht in Options übernommen**

In `config_flow.py` (Line 189):
```python
async def async_step_init(self, user_input: dict[str, Any] | None = None):
    if user_input is not None:
        return self.async_create_entry(title="", data=user_input)  # ❌ Nur neue Daten!
```

**Problem:**
- Bei Änderung der Options werden nur die neuen Daten gespeichert
- Die ursprünglichen Config Einträge (valve_entity, temp_sensor) gehen verloren
- Integration wird nach Options-Update unbrauchbar

**Fix:**
```python
async def async_step_init(self, user_input: dict[str, Any] | None = None):
    if user_input is not None:
        # Merge mit bestehenden Config Daten
        return self.async_create_entry(
            title="",
            data={**self.config_entry.data, **user_input}
        )
```

---

### 7. **SCHWER: Keine Exception Handling in async Setup**

In `__init__.py` (Line 27):
```python
await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
```

**Problem:**
- Wenn eine Platform fehlschlägt, crasht die ganze Integration
- Keine Exception Handling
- Keine Fehlermeldung in Logs

**Fix:**
```python
try:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
except Exception as err:
    _LOGGER.error("Failed to set up SonClouTRV platform: %s", err)
    return False
```

---

## Mittelschwere Fehler

### 8. **MITTEL: Zugriff auf nicht-vorhandene Daten in config_entry.data**

In `sensor.py` (Line 108):
```python
climate_name = config_entry.data.get('name', '').lower().replace(' ', '_')
```

**Problem:**
- Der Key ist `CONF_NAME`, nicht `'name'`
- Sollte konsistent sein mit const.py

**Fix:**
```python
from .const import CONF_NAME
climate_name = config_entry.data.get(CONF_NAME, '').lower().replace(' ', '_')
```

---

### 9. **MITTEL: Keine Exception Handling bei Entity Lookups**

Überall in `sensor.py` (z.B. Line 84-92):
```python
if hass.states.get(valve_pos_entity):
    sensors.append(...)
else:
    _LOGGER.error("Valve opening degree entity not found: %s", valve_pos_entity)
```

**Problem:**
- Wenn TRV Entities nicht vorhanden sind, logs warnen aber keine kritischen Fehler
- Setup setzt sich fort, aber ohne Daten
- Führt zu inkonsistentem Verhalten

**Verbesserung:** Sollte klarer sein, ob das normal oder kritisch ist

---

### 10. **MITTEL: Keine Timeout für Entity Verfügbarkeit in climate.py (Line 232-243)**

```python
for i in range(max_wait):
    trv_state = self.hass.states.get(self._valve_entity)
    if trv_state and trv_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        break
    if i < max_wait - 1:
        await asyncio.sleep(wait_interval)
```

**Problem:**
- 30 Sekunden `asyncio.sleep()` blockiert den Event Loop
- Sollte `async_call_later()` verwenden

**Fix:** Verwende `async_call_later()` statt `asyncio.sleep()`

---

### 11. **MITTEL: Fehlende Validierung in climate.py**

**Problem:**
- Keine Überprüfung, ob `CONF_VALVE_ENTITY` und `CONF_TEMP_SENSOR` tatsächlich existieren
- Keine Überprüfung, ob `CONF_VALVE_ENTITY` eine Climate Entity ist
- Keine Überprüfung, ob `CONF_TEMP_SENSOR` ein Sensor ist

---

### 12. **MITTEL: Temperature Sensor Selection Entity ist optional**

In `climate.py` (Line 457-470):
```python
sensor_select_entity = self._valve_entity.replace("climate.", "select.") + "_temperature_sensor_select"

if self.hass.states.get(sensor_select_entity):
    # Via entity
else:
    # Via MQTT
```

**Problem:**
- Nicht alle SONOFF TRVZB haben ein `temperature_sensor_select`
- Code fällt auf MQTT zurück, aber das könnte nicht verfügbar sein
- Keine Fehlerbehandlung wenn beide fehlschlagen

---

## Leichte Fehler

### 13. **LEICHT: Ungenaue Proportional Gain Berechnung**

In `climate.py` (Line 558):
```python
proportion = (temp_diff - self._hysteresis) * self._proportional_gain / 100.0
```

**Problem:**
- Die Einheit ist `%/°C`, aber die Berechnung teilt durch 100.0
- Mit Standardwert 20: `(1°C - 0.5) * 20 / 100 = 0.1` → 10% Ventilöffnung ✓
- Aber wenn User auf 200 stellt: wird zu 2.0 → capped auf max → unklar

**Verbesserung:** Bessere Dokumentation oder Anpassung der Berechnung

---

### 14. **LEICHT: Keine Prüfung auf None Values in sensor.py**

In vielen Sensoren (z.B. `SonClouTRVEfficiencySensor.py` Line 389):
```python
temp_change = self._temp_history[-1] - self._temp_history[0]
avg_valve = sum(self._valve_history) / len(self._valve_history)
if avg_valve > 5:
    ...
```

**Problem:**
- Wenn `self._valve_history` leer ist → Division by Zero
- Keine Prüfung auf NaN oder Inf

**Fix:**
```python
if self._valve_history and len(self._valve_history) > 0:
    avg_valve = sum(self._valve_history) / len(self._valve_history)
```

---

### 15. **LEICHT: Bare except Clauses**

Überall in sensor.py (z.B. Line 267, 289, 320):
```python
try:
    ...
except:  # ❌ Zu breit!
    pass
```

**Problem:**
- Fängt alle Exceptions ab, auch `KeyboardInterrupt` und `SystemExit`
- Schwer zu debuggen
- Masked echte Fehler

**Fix:**
```python
try:
    ...
except (ValueError, TypeError, KeyError) as err:
    _LOGGER.error("Error: %s", err)
```

---

### 16. **LEICHT: Inkonsequente Entity ID Konstruktion**

In verschiedenen Dateien:
- `climate.py` Line 592: `valve_opening_entity = self._valve_entity.replace("climate.", "number.") + "_valve_opening_degree"`
- `sensor.py` Line 83: `valve_pos_entity = f"number.{base_entity_id}_valve_opening_degree"`

**Problem:** Zwei unterschiedliche Wege, die Entity ID zu konstruieren

**Fix:** Konsistente Konstruktion verwenden

---

### 17. **LEICHT: Keine Handling des "unavailable" States**

In vielen Callbacks (z.B. climate.py Line 296):
```python
if new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
```

**Problem:**
- Wird korrekt gepräft, aber dann werden Exceptions bei Fehler weiterhin nicht gehandhabt
- `int(attributes["position"])` kann fehlschlagen

---

## Zusammenfassung der Fehler

| Schwere | Fehler | Auswirkung |
|---------|--------|-----------|
| 🔴 KRITISCH | #1: Config Key Fehler | Sensoren funktionieren nicht |
| 🔴 KRITISCH | #2: Entity ID Mismatch | Number/Switch/Button funktionieren nicht |
| 🔴 KRITISCH | #3: asyncio.sleep() blockiert | HA komplett eingefroren |
| 🟠 SCHWER | #4: datetime.now() falsch | Nachteilige Timezone Fehler |
| 🟠 SCHWER | #5: Entity Lookup fehlgeschlagen | Number Entities wirkungslos |
| 🟠 SCHWER | #6: Config Options überschreiben | Integration kaputt nach Options-Update |
| 🟠 SCHWER | #7: Keine Exception Handling Setup | Integration crasht bei Platform Fehler |
| 🟡 MITTEL | #8-12 | Verschiedene kleinere Fehler |
| 🟢 LEICHT | #13-17 | Code Quality Probleme |

---

## Empfohlene Fix-Reihenfolge

1. **Fehler #3** - asyncio.sleep() Blockierung → SOFORT FIX
2. **Fehler #2** - Entity ID Konstruktion → HOCH PRIORITÄT
3. **Fehler #1** - Config Keys → HOCH PRIORITÄT
4. **Fehler #4** - datetime.now() → HOCH PRIORITÄT
5. **Fehler #6** - Config Entry Update → MITTEL PRIORITÄT
6. **Fehler #5, #7** - Exception Handling → MITTEL PRIORITÄT
7. **Fehler #8-17** - Code Quality → NIEDRIG PRIORITÄT

