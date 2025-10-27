# SONOFF TRVZB Valve Limiter

Eine Home Assistant Custom Component, die die **maximale Ventilöffnung** von SONOFF TRVZB Zigbee Thermostatventilen begrenzt.

A Home Assistant Custom Component that **limits the maximum valve opening** of SONOFF TRVZB Zigbee thermostatic radiator valves.

## 🎯 Was macht diese Integration?

Diese Integration ist ein **Wrapper** um dein SONOFF TRVZB Thermostat:

### ✅ Was sie tut:
1. **Begrenzt die Ventilöffnung** auf eine der 6 Stufen (0%, 20%, 40%, 60%, 80%, 100%)
2. **Synchronisiert die Temperatur** - Deine eingestellte Temperatur wird ins Original-Thermostat geschrieben
3. **Überwacht das Ventil** - Wenn das TRV mehr als erlaubt öffnet, wird es begrenzt

### ❌ Was sie NICHT tut:
- Ersetzt NICHT das Original-Thermostat
- Ändert NICHT die Regelungslogik des TRV
- Nutzt KEINEN externen Temperatursensor

## Warum?

### Problem: Voller Heizkreis-Durchfluss

Wenn alle TRVs gleichzeitig voll (100%) öffnen:
- ⚠️ Zu viel Durchfluss im Heizkreis
- ⚠️ Pumpe läuft unter Last
- ⚠️ Ungleichmäßige Verteilung
- ⚠️ Geräusche in den Leitungen

### Lösung: Begrenzung auf Stufen

Mit dieser Integration:
- ✅ Jedes Ventil öffnet maximal bis zur eingestellten Stufe
- ✅ Kontrollierter Durchfluss
- ✅ System läuft ruhiger
- ✅ Bessere Wärmeverteilung

## Installation

### Via HACS (Empfohlen)

1. HACS → Integrations → ⋮ → Custom repositories
2. URL: `https://github.com/yourusername/underfloor-heating-control`
3. Kategorie: Integration
4. Installation → Home Assistant neu starten

### Manuell

```bash
cp -r custom_components/underfloor_heating_control <HA_CONFIG>/custom_components/
```

## Konfiguration

### 1. Integration hinzufügen

**Einstellungen** → **Geräte & Dienste** → **+ Integration hinzufügen** → "Underfloor Heating Control"

### 2. Raum konfigurieren

#### Erforderlich:
- **Name**: z.B. "Wohnzimmer Heizung (Limiter)"
- **SONOFF TRVZB**: Wähle dein TRV (`climate.0xXXXX` oder `climate.wohnzimmer_trv`)
- **Temperatursensor**: Wähle **denselben** Sensor wie das TRV nutzt (oder dummy sensor)

#### Optional:
- **Maximale Ventilöffnung (Stufe)**: 
  - Stufe 0 (0%) - Komplett geschlossen
  - Stufe 1 (20%)
  - Stufe 2 (40%)
  - Stufe 3 (60%)
  - Stufe 4 (80%) ← **Standard**
  - Stufe 5 (100%) - Keine Begrenzung

## Wie es funktioniert

### Architektur

```
Benutzer stellt Temperatur ein (z.B. 22°C)
         ↓
    Wrapper Climate Entity
         ↓
    Schreibt 22°C ins Original TRV
         ↓
    Original TRV regelt selbst
         ↓
    TRV öffnet Ventil (z.B. 95%)
         ↓
    Wrapper erkennt: 95% > 80% (Stufe 4)
         ↓
    Wrapper begrenzt auf 80%
```

### Beispiel-Szenario

**Ohne Limiter:**
```
Raum: 18°C
Ziel: 22°C
TRV denkt: "4°C Differenz! Ventil voll auf 100%!"
```

**Mit Limiter (Stufe 4 = 80%):**
```
Raum: 18°C
Ziel: 22°C
TRV öffnet auf 100%
Limiter: "Stop! Maximum ist 80%!"
Ventil wird auf 80% begrenzt
```

## Verwendung

### Über die UI

**Original-Thermostat (`climate.wohnzimmer_trv`):**
- Zeigt interne TRV-Temperatur
- Zeigt tatsächliche Ventilposition

**Wrapper-Thermostat (`climate.wohnzimmer_heizung`):**
- Benutze DIESES zum Einstellen der Temperatur
- Zeigt begrenzte Ventilposition (max. eingestellte Stufe)

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
          entity_id: climate.wohnzimmer_heizung  # Wrapper nutzen!
        data:
          temperature: 22
```

### Wichtig

⚠️ **Nutze den Wrapper-Thermostat** für alle Temperatureinstellungen!
⚠️ **Nicht** das Original-TRV direkt steuern (würde Begrenzung umgehen)

## Stufenempfehlung

| Raum | Empfohlene Stufe | Grund |
|------|------------------|-------|
| Wohnzimmer | 4 (80%) | Hauptraum, viel Nutzung |
| Schlafzimmer | 3 (60%) | Nachts kühler |
| Küche | 3 (60%) | Eigene Wärmequellen (Herd, etc.) |
| Bad | 5 (100%) | Schnell aufheizen |
| Flur | 2 (40%) | Durchgangsraum |

## Technische Details

### Ventilbegrenzung via Zigbee2MQTT

Die Integration versucht zwei Methoden:

1. **Via number.entity** (bevorzugt):
   ```yaml
   service: number.set_value
   entity_id: number.wohnzimmer_trv_position
   value: 80
   ```

2. **Via MQTT** (fallback):
   ```yaml
   service: mqtt.publish
   topic: zigbee2mqtt/wohnzimmer_trv/set/position
   payload: 80
   ```

### Monitoring-Intervall

- Überprüft Ventilposition alle **30 Sekunden**
- Bei Überschreitung: Sofortige Begrenzung
- Minimale Wartezeit zwischen Korrekturen: 5 Minuten

## Fehlerbehebung

### Ventil wird nicht begrenzt

1. **Prüfe in Developer Tools → States:**
   ```
   climate.wohnzimmer_trv
   attributes:
     position: 95  # Sollte vom Original TRV kommen
   ```

2. **Prüfe ob number entity existiert:**
   ```
   number.wohnzimmer_trv_position
   ```

3. **Aktiviere Debug-Logging:**
   ```yaml
   logger:
     logs:
       custom_components.underfloor_heating_control: debug
   ```

### Temperatur wird nicht synchronisiert

1. Prüfe ob du den Wrapper nutzt (nicht das Original-TRV)
2. Prüfe Logs auf Fehler beim Setzen der Temperatur
3. Test manuell im Developer Tools

### Position-Entity nicht gefunden

Die Integration nutzt automatisch MQTT als Fallback.
Prüfe in Zigbee2MQTT ob das Gerät das `position` Attribut unterstützt.

## Beispiel-Dashboard

```yaml
type: vertical-stack
cards:
  - type: thermostat
    entity: climate.wohnzimmer_heizung
    name: Wohnzimmer (begrenzt)
  
  - type: entities
    entities:
      - entity: climate.wohnzimmer_trv
        name: "Original TRV (nur Info)"
        secondary_info: last-changed
      - type: attribute
        entity: climate.wohnzimmer_trv
        attribute: position
        name: "Aktuelle Ventilöffnung"
      - type: attribute
        entity: climate.wohnzimmer_heizung
        attribute: valve_position
        name: "Begrenzte Öffnung"
```

## Häufige Fragen

**Q: Brauche ich noch das Original-TRV-Entity?**
A: Ja! Das Wrapper-Entity ist nur eine Steuerungsschicht darüber.

**Q: Kann ich verschiedene Stufen für verschiedene Zeiten?**
A: Ja, über Automationen die `valve_opening_step` ändern (Options-Menü).

**Q: Was passiert bei Home Assistant Neustart?**
A: Wrapper stellt sich wieder her, TRV regelt weiter selbst.

**Q: Funktioniert das mit ZHA?**
A: Nein, nur mit Zigbee2MQTT.

## Lizenz

MIT License

---

**Hinweis**: Ersetze `yourusername` mit deinem GitHub-Namen vor Veröffentlichung.
