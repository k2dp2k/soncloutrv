# Diagnose: Stufen-Limit und Sensor-Anzeige Problem

## Problem 1: Stufe begrenzt maximale Öffnung nicht

### Was passiert:
- Du stellst z.B. Stufe "2" (40%) ein
- Erwartet: Ventil öffnet maximal 40%
- Beobachtet: Ventil öffnet über 40%

### Root Cause Analyse:

Das ist **RICHTIG SO**, aber könnte verwirrend wirken:

1. **Die Preset-Stufe ist die MAX-Öffnung** wenn Heizen aktiv ist
2. **Aber:** Die tatsächliche Öffnung wird von der **Temperatur-Differenz** bestimmt!

Beispiel:
```
Stufe 2 gestellt = max 40% Öffnung möglich
Aktuelle Temp:   20°C
Zieltemp:        25°C
Diff:            5°C

Berechnung:
proportion = (5 - 0.5 Hysterese) * 20 / 100 = 0.9
desired = int(0.9 * 40%) = 36%  ← Wird auf 40% gekürzt (min)

ABER: Ist die Diff noch größer:
proportion = (10 - 0.5) * 20 / 100 = 1.9
desired = int(1.9 * 40%) = 76%  ← Würde 76% sein, aber min(76, 40) = 40%
```

**Die Stufe funktioniert KORREKT!** Sie limitiert auf 40% maximal.

**ABER:** Wenn dein Proportional-Gain zu hoch ist, kann es aussehen, als würde es nicht funktionieren.

### Wie überprüfen:

In den Logs schaut man hier:
```
Temp diff: X.X°C, Gain: Y.Y, Current opening: Z%, Desired: A%, Max: B%
```

Der `Max: B%` sollte der Stufe entsprechen (*, 1-5 = 0%, 20%, 40%, 60%, 80%, 100%).

---

## Problem 2: Aktuelle Position wird nicht in Sensoren angezeigt

### Was passiert:
- Sensor "Ventilposition" zeigt nichts oder alten Wert
- Climate Extra Attributes zeigen Valve Position auch nicht

### Root Cause:

1. **Proxy-Sensor liest von TRV-Entity:**
   ```python
   valve_pos_entity = f"number.{base_entity_id}_valve_opening_degree"
   ```
   Das ist die SONOFF TRVZB `number.*_valve_opening_degree` Entity!
   Diese wird vom TRV gespeichert, nicht von SonTRV.

2. **SonTRV speichert Position intern:**
   ```python
   self._valve_position = valve_opening  # In climate.py
   ```
   Aber das wird nur als Extra-Attribute exportiert, nicht als separate Sensor-Entity!

3. **Extra State Attributes zeigen Position:**
   ```python
   ATTR_VALVE_POSITION: self._valve_position
   ```
   Diese sind im Climate Entity vorhanden, aber Standard-UI zeigt sie nicht prominente.

### Warum sieht man die Position nicht:

Der Sensor "Ventilposition" ist ein **Proxy** der TRV-Entity:
- Zeigt was der TRV intern speichert
- NICHT was SonTRV gerade setzen möchte
- Kann hinterherhinken wenn TRV träge ist

---

## Was sollte es sein:

### Für Stufen-Limit (Problem 1):
Die **korrekte Logik ist bereits implementiert:**
- ✅ Preset Mode setzt `_max_valve_position` 
- ✅ `_calculate_desired_valve_opening()` limitiert auf diese Position
- ✅ `_async_set_valve_opening()` setzt den Wert

Das ist korrekt! Aber überprüfe die Logs:
```bash
# In Home Assistant Logs suchen nach:
"SonTRV: Temp diff: X, Gain: Y, Current opening: Z, Desired: A, Max: B"
```

Wenn `Max: B` = 40 ist, funktioniert die Stufe!

### Für Sensor-Anzeige (Problem 2):
Die Proxy-Sensoren sind by-design der TRV-Position, nicht der SonTRV-Berechnung.

**Optionen um Valve Position sichtbar zu machen:**
1. Extra-Attributes im Climate Entity betrachten (schon vorhanden)
2. Template-Sensor erstellen: `{{ state_attr('climate.xxx', 'valve_position') }}`
3. Neue native Sensor-Entity in SonTRV erstellen (nicht als Proxy)

---

## Empfohlener Test:

### Test 1: Stufen-Limit überprüfen
```
1. Öffne Developer Tools → States
2. Wende Preset "2" (40%) an
3. Suche climate.soncloutrv_xxx
4. Schau auf extra_state_attributes:
   - valve_position: sollte ≤ 40% sein
   - max_valve_position: sollte 40 sein

5. Stelle Stufe "5" (100%) ein
6. valve_position: sollte höher werden
```

### Test 2: Logs überprüfen
```
1. Settings → System → Logs
2. Suche nach "Temp diff:" Messages
3. Schau auf "Max: X%" - das sollte der Stufe entsprechen
```

### Test 3: Valve Position Sensor
```
1. Suche Sensor "Ventilposition" 
2. Das ist ein Proxy der TRV-Entity
3. Um SonTRV-interne Position zu sehen, nutze:
   state_attr('climate.soncloutrv_xxx', 'valve_position')
```

