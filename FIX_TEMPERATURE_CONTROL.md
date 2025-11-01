# Fix: Thermostat bleibt im Leerlauf nach Temperatur-Änderung

## 🔴 Das Problem

Wenn du eine höhere Zieltemperatur eingibst, bleibt das Thermostat im **Leerlauf** (IDLE), obwohl:
- Zieltemperatur > aktuelle Temperatur
- Der Stufe genug Öffnung erlaubt

**Erst nach Stufen-Änderung** lädt das Ventil auf (weil `async_set_preset_mode()` `_async_control_heating()` aufruft).

---

## ✅ Die Ursache

In `async_set_temperature()` (Zeile 785-813) wird die Zieltemperatur geändert und zum TRV synchronisiert, **aber die Kontrolllogik wird NICHT neu ausgeführt**!

```python
# VORHER (FALSCH):
async def async_set_temperature(self, **kwargs) -> None:
    self._attr_target_temperature = temperature  # Nur speichern
    
    # TRV synchronisieren
    await self.hass.services.async_call(...)
    
    # ❌ FEHLT: await self._async_control_heating()
    
    self._update_extra_attributes()
    self.async_write_ha_state()
```

**Resultat:**
- Temperatur wird gespeichert
- Aber Ventil-Kontrolllogik ist nicht aktiv
- Erst beim nächsten Timer-Event (5 Min Interval) wird neu berechnet

---

## ✅ Die Lösung

**Zwei Fixes:**

### Fix 1: Kontrolllogik nach Temperatur-Änderung

```python
# NACHHER (RICHTIG):
async def async_set_temperature(self, **kwargs) -> None:
    self._attr_target_temperature = temperature
    
    # TRV synchronisieren
    await self.hass.services.async_call(...)
    
    # ✅ Kontrolllogik SOFORT ausführen mit neuer Zieltemperatur
    await self._async_control_heating()
    
    self._update_extra_attributes()
    self.async_write_ha_state()
```

**Was passiert:**
1. Zieltemperatur wird aktualisiert
2. TRV wird synchronisiert
3. ✅ Ventil-Kontrolllogik wird sofort ausgeführt
4. Gewünschte Ventilöffnung wird berechnet und gesetzt
5. Heizung startet **SOFORT**

### Fix 2: datetime.now() Fehler

Auch in `_async_limit_valve_position()` gab es noch `datetime.now()`:
```python
# VORHER:
self._last_valve_update = datetime.now()  # ❌ Keine Timezone

# NACHHER:
self._last_valve_update = dt_util.now()  # ✅ Home Assistant aware
```

---

## 📋 Status

### ✅ Behoben:
- **1. async_set_temperature()** - Ruft jetzt `_async_control_heating()` auf
- **2. datetime.now()** - In _async_limit_valve_position() konvertiert

### Verhaltensänderung nach Fix:
```
VORHER:
1. Nutzer setzt Temp auf 22°C (vorher 20°C)
2. Thermostat bleibt 5+ Min im IDLE
3. Nach Preset-Änderung: Ventil öffnet sich

NACHHER:
1. Nutzer setzt Temp auf 22°C
2. Thermostat öffnet Ventil SOFORT (< 1 Sekunde)
3. Normal responsive Heizungssteuerung
```

---

## 🧪 Test

Nach Home Assistant Neustart:

1. Stelle Zieltemperatur höher ein
2. Beobachte die Climate Entity `hvac_action`:
   - ✅ Sollte jetzt zu "heating" wechseln (statt "idle")
   - ✅ Ventilposition sollte sofort ansteigen

3. Checke Logs für:
   ```
   "Temp diff: X.XDC, ... Desired: Y%, Max: Z%"
   ```
   Sollte sofort nach Temperatur-Änderung erscheinen, nicht erst nach 5 Min.

