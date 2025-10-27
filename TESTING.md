# Lokales Testen der Underfloor Heating Control Integration

## Vorbereitung

### 1. Home Assistant Installation finden

Finde dein Home Assistant `config` Verzeichnis:
- **Home Assistant OS / Supervised**: `/config`
- **Home Assistant Container**: Der gemountete config Ordner
- **Home Assistant Core (venv)**: Meistens `~/.homeassistant`

### 2. Komponente installieren

```bash
# Von diesem Verzeichnis aus:
cd /Users/daniel/homeassistant-heating-analysis

# Kopiere die Komponente in dein Home Assistant config Verzeichnis
# Ersetze /PATH/TO/CONFIG mit deinem tatsächlichen Pfad
cp -r custom_components/underfloor_heating_control /PATH/TO/CONFIG/custom_components/

# Beispiel für Home Assistant Core:
# cp -r custom_components/underfloor_heating_control ~/.homeassistant/custom_components/

# Beispiel für Docker mit gemounteter Config:
# cp -r custom_components/underfloor_heating_control /Users/daniel/homeassistant/config/custom_components/
```

### 3. Home Assistant neu starten

- **UI**: Einstellungen → System → Neu starten
- **CLI**: `ha core restart`
- **Docker**: `docker restart homeassistant`
- **Core**: `sudo systemctl restart home-assistant@homeassistant`

### 4. Logs überprüfen

Aktiviere Debug-Logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.underfloor_heating_control: debug
```

Starte erneut neu und überprüfe die Logs auf Fehler.

## Integration hinzufügen

### Via UI (empfohlen)

1. Gehe zu **Einstellungen** → **Geräte & Dienste**
2. Klicke **+ Integration hinzufügen**
3. Suche nach "Underfloor Heating Control"
4. Wenn nicht gefunden: Neustart vergessen? Cache leeren (Browser neu laden mit Shift+F5)

### Test-Konfiguration

Für deinen ersten Test, z.B. **Bad**:

**Erforderlich:**
- Name: `Fußboden Bad`
- Ventil Entity: `number.heizung_bad_fussboden_valve_closing_degree`
- Temperatursensor: `sensor.temperatur_badezimmer_temperature`

**Optional (Standardwerte sind gut für ersten Test):**
- Min Temp: `6`
- Max Temp: `28`
- Zieltemperatur: `20`
- Hysterese: `1.0`
- Max Ventilöffnung: `83`
- Steuerungsmodus: `binary` (oder `proportional` zum Testen)

## Test-Szenarien

### Test 1: Basis-Funktionalität

1. Stelle die Zieltemperatur **höher** als die aktuelle Temperatur
2. Warte 30 Sekunden (SCAN_INTERVAL)
3. Prüfe im **Developer Tools** → **States**:
   - `climate.fussboden_bad` sollte `state: heat` zeigen
   - Attribut `valve_position` sollte > 0 sein
   - `hvac_action` sollte `heating` sein
4. Prüfe das Ventil:
   - `number.heizung_bad_fussboden_valve_closing_degree` sollte < 100 sein

### Test 2: Ventil schließt

1. Stelle die Zieltemperatur **niedriger** als die aktuelle Temperatur
2. Warte 30 Sekunden
3. Ventil sollte schließen (`valve_closing_degree` → 100)

### Test 3: Ein/Aus

1. Schalte den Thermostat aus (über UI)
2. Ventil sollte sofort schließen
3. Schalte wieder ein
4. Ventil sollte sich nach Temperatur verhalten

### Test 4: Proportionale Regelung (Optional)

1. Gehe zu **Geräte & Dienste** → Klicke auf die Integration → **Konfigurieren**
2. Ändere `control_mode` zu `proportional`
3. Teste verschiedene Temperaturdifferenzen
4. Ventilposition sollte stufenlos zwischen 0% und Max% liegen

### Test 5: Zeitsteuerung (Optional)

1. Aktiviere Zeitsteuerung in den Optionen
2. Setze Start-/Endzeit
3. Außerhalb des Zeitfensters sollte das Ventil geschlossen bleiben

## Fehlerbehebung

### Integration erscheint nicht

```bash
# Prüfe, ob die Dateien korrekt kopiert wurden
ls -la /PATH/TO/CONFIG/custom_components/underfloor_heating_control/

# Sollte zeigen:
# __init__.py
# climate.py
# config_flow.py
# const.py
# manifest.json
# translations/
```

### Fehler in den Logs

Öffne **Einstellungen** → **System** → **Protokolle** und suche nach:
- `underfloor_heating_control`
- Fehlermeldungen mit Traceback

Häufige Fehler:
- **Entity nicht gefunden**: Prüfe, ob die Ventil-Entity existiert
- **Sensor nicht gefunden**: Prüfe den Temperatursensor
- **Import Error**: Neustart vergessen oder Datei fehlt

### Ventil reagiert nicht

1. Prüfe manuell im Developer Tools:
   ```yaml
   service: number.set_value
   target:
     entity_id: number.heizung_bad_fussboden_valve_closing_degree
   data:
     value: 50
   ```
2. Funktioniert das? → Ventil OK, Problem in der Integration
3. Funktioniert nicht? → Problem mit dem Ventil selbst

### Debug-Informationen sammeln

Aktiviere Debug-Logging und mache einen vollständigen Test:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.underfloor_heating_control: debug
    homeassistant.components.climate: debug
```

Nach Neustart:
1. Führe einen Test durch
2. Exportiere die Logs
3. Suche nach relevanten Meldungen

## Live-Monitoring

### Developer Tools → States

Überwache während des Tests:
```
climate.fussboden_bad
  state: heat / off
  attributes:
    current_temperature: 21.5
    temperature: 22.0
    valve_position: 83
    control_mode: binary
    hvac_action: heating
```

### Developer Tools → Events

Abonniere Events:
```
state_changed
```

Filter: `climate.fussboden_bad` oder dein Ventil

## Vergleich mit Original-Lösung

Wenn du parallel testen willst:

1. **Lass die Original-Konfiguration aktiv** für einen anderen Raum
2. Teste die neue Integration für einen Raum (z.B. Bad)
3. Vergleiche das Verhalten:
   - Reaktionszeit
   - Ventilbewegungen
   - Temperaturstabilität
4. Wenn zufrieden, migriere weitere Räume

## Checkliste vor Migration

- [ ] Komponente läuft stabil für 24-48 Stunden
- [ ] Ventil öffnet/schließt wie erwartet
- [ ] Temperaturregelung funktioniert
- [ ] Keine Fehler in den Logs
- [ ] (Optional) Proportional-Modus getestet
- [ ] (Optional) Zeitsteuerung getestet
- [ ] State Restoration nach Neustart funktioniert

## Nächste Schritte nach erfolgreichem Test

Wenn alles funktioniert:

1. Füge weitere Räume hinzu über UI
2. Deaktiviere alte Automationen (nicht löschen, als Backup)
3. Entferne nach 1-2 Wochen:
   - Generic Thermostat Konfigurationen
   - Dummy Switches
   - Input Helpers (fussboden_*)
   - Alte Automationen

## Notfall-Rollback

Falls Probleme auftreten:

1. Lösche die Integration über UI
2. Entferne den Ordner:
   ```bash
   rm -rf /PATH/TO/CONFIG/custom_components/underfloor_heating_control
   ```
3. Starte Home Assistant neu
4. Alte Konfiguration ist noch aktiv

## Support

Bei Problemen:
1. Prüfe die Logs
2. Teste manuell mit Developer Tools
3. Dokumentiere das Problem mit Screenshots/Logs
4. Öffne ein Issue (später, wenn veröffentlicht)
