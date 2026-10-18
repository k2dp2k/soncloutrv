# SonTRV - Smart Thermostat Control

<p align="center">
  <img src="custom_components/soncloutrv/icon.png" alt="SonTRV Logo" width="200"/>
</p>

## Projektbeschreibung

SonTRV ist eine Home Assistant Custom Integration für **Einzelraum-Flächenheizungen mit SONOFF TRVZB**,
entwickelt für **ClouSet-Anlagen** (Multi SK / Multi HK): jeder Raum hat einen eigenen Heizkreis im
Estrich, das Ventil sitzt im Vorlauf, der maximale Durchfluss ist per Voreinstellung fest vorgegeben
und alle Kreise hängen am gleichen Vorlauf. Das TRVZB ersetzt den selbsttätigen P-Regler-Kopf; SonTRV
übernimmt die Regelung mit einem externen Raumsensor.

Warum eine eigene Regelung? Die Kombination aus Estrich-Speichermasse (Totzeit 1–2 h), stark
nichtlinearem Ventil (Durchfluss steigt am Anfang des Hubs fast vollständig an) und gegenseitiger
Beeinflussung der Räume lässt einen gewöhnlichen PID-Regler pendeln. Ab v2.0.0 arbeitet deshalb ein
**vorausschauender, lernender Raumregler** (siehe [Regelung](#-regelung-ab-v200)).

## 🌟 Features

- 🔮 **Vorausschauende Regelung** – schließt das Ventil, *bevor* der Estrich den Raum überheizt
- 🧠 **Lernt den Wärmebedarf** pro Raum (I-Anteil bleibt erhalten, wird über Neustarts gespeichert)
- 🌤️ **Gelernte Wettervorsteuerung** – Außentemperatur wirkt sofort, ohne manuelles Tuning
- 🏠 **Gemeinsamer Regler pro Raum** – mehrere Kreise im selben Raum (z. B. Wohnen + Küche) regeln zusammen
- 🔥 **Heizungstyp** Flächenheizung oder Heizkörper mit passenden Parametern
- 🎛️ **Steuermodi** PID (Standard), Takt/PWM, Binär, Proportional – alle live umschaltbar
- 🔁 **Robuste Ventilansteuerung** – Öffnungs- und Schließgrad komplementär, Soll/Ist-Abgleich mit dem TRV, Wiederholung bei Funkfehlern, wenige Schreibvorgänge (Batterie)
- 🛟 **Sensor-Ausfall-Fallback** – TRV-Sensor mit gelerntem Offset, sonst gelernter Grundbedarf
- 🚨 **Erkennung fehlender Vorlaufwärme** (Ventil offen, Raum wird nicht wärmer) – stoppt das Hochlaufen des I-Anteils
- 🚪 **Fenster** per Sensor (Raum oder global) oder Temperatursturz; Lernwerte bleiben erhalten, sanfter Wiederanlauf
- 🛡️ **Verkalkungsschutz** jeden Sonntag gegen 11 Uhr (Kreise zeitversetzt), auch im Sommer
- 📑 **CSV-Logging** aller Regler-Interna für Analysen, 🧾 **Diagnose-Download**
- 🇩🇪 Deutsche und englische Übersetzung

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
   - **Temperatursensor:** Wähle deinen externen Sensor (z.B. `sensor.temperatur_badezimmer`) – kann später in den Optionen geändert werden
   - **Temperaturbereich:** Min/Max Temperatur festlegen
   - **Zieltemperatur:** Standard-Solltemperatur
   - **Ventilöffnungsstufe:** Wähle zwischen * (0%), 1-5 (20%-100%)

4. **Wiederhole** für jeden Raum/Thermostat

## 🎛️ Erstellte Entities pro Thermostat

Nach der Einrichtung werden automatisch erstellt:

### Haupt-Thermostat
- `climate.sontrv_[name]` - Steuerung mit Preset-Modi

### Raumzuordnung

Bei der Einrichtung kannst du jedem SonTRV einen einfachen Raum zuordnen:

- Es stehen standardmäßig **6 Räume** zur Verfügung: `Wohnzimmer`, `Schlafzimmer`, `Bad`, `Küche`, `Flur`, `Büro`.
- Alle Thermostate mit demselben Raum teilen sich einen gemeinsamen lernenden PID‑Regler.
- Wenn du keinen Raum explizit auswählst (Bestands-Installationen), wird der Raum automatisch über den verwendeten Temperatursensor gruppiert.

### Sensoren (automatisch)
- `sensor.[name]_ventilposition` - Aktuelle Öffnung (0-100%)
- `sensor.[name]_ventilschliessgrad` - Aktueller Schließgrad (100% - Öffnung)
- `sensor.[name]_trv_temperatur` - TRV interne Temperatur (Proxy)
- `sensor.[name]_trv_batterie` - TRV Batteriestand (Proxy)
- `sensor.[name]_temperaturdifferenz` - Soll/Ist Differenz
- `sensor.[name]_o_ventilposition` - Durchschnitt
- `sensor.[name]_aktuelle_stufe` - Gewählte Stufe (*, 1-5)
- `sensor.[name]_pid_p` - PID Proportional-Anteil
- `sensor.[name]_pid_i` - PID Integral-Anteil (Lernwert)
- `sensor.[name]_pid_d` - PID Derivative-Anteil (Dämpfung)

### Einstellungen (live, ohne Neuladen)
- `select.[name]_heizungstyp` – Flächenheizung / Heizkörper (setzt die Regelparameter auf das Profil)
- `select.[name]_steuermodus` – PID (Standard), PWM, Binär, Proportional
- Option „Rolle im Raum“ (Optionsdialog): Automatisch / Hauptheizung / Zusatzheizung, Attribut `heater_role`
- `number.[name]_hysterese` – Schaltabstand Binär-Modus, Übertemperatur-Abschaltung im PID-Modus
- `number.[name]_tragheit_min_update_intervall` – Regelintervall (Standard 15 min Fußboden / 5 min Heizkörper)
- `number.[name]_vorausschau_totzeit` – Vorausschau (Standard 45 min Fußboden / 12 min Heizkörper)
- `number.[name]_pid_p_gain_kp`, `..._pid_i_gain_ki_lernen`, `..._pid_d_gain_kd_dampfung`
- `number.[name]_feed_forward_aussen_gain_ka` – 0 = automatisch lernen
- `number.[name]_raum_leistungsanteil` – Gewichtung mehrerer Kreise in einem Raum
- `number.[name]_ventil_offnungsbeginn` – Öffnung, ab der Wasser fließt

### Verkalkungsschutz & Wartung
- `switch.[name]_verkalkungsschutz` – Sonntag 11:00–11:50 (je Kreis versetzt)
- `button.[name]_ventil_durchbewegen` – sofort (5 min auf, 5 min zu)
- `button.[name]_lernwerte_zurucksetzen` – gelernten Wärmebedarf des Raums verwerfen

## 🔧 Regelung ab v2.0.0

Pro Raum und Heizungstyp gibt es einen gemeinsamen Regler:

1. **Trend**: lineare Regression über 60 min (Heizkörper 20 min) liefert geglättete Temperatur und Steigung in K/h – robust gegen 0,1-K-Stufen der Sensoren.
2. **P-Anteil auf die Vorhersage**: `Kp × (Soll − (Ist + Steigung × Vorausschau))`. Steigt die Temperatur noch, nimmt der Regler Leistung weg, bevor der Estrich überschwingt.
3. **I-Anteil = gelernter Grundbedarf**: wird nicht mehr in Sollwertnähe abgebaut oder beim Vorzeichenwechsel gelöscht (das war die Ursache des Pendelns in v1.x). Lernt nur nahe am Soll oder wenn der Raum „feststeckt“, mit Anti-Windup und gespeichert über Neustarts.
4. **Wettervorsteuerung**: in ruhigen Phasen lernt der Regler „% Bedarf pro Kelvin innen/außen“; Außentemperaturänderungen wirken sofort, der I-Anteil korrigiert nur den Rest.
5. **Ausgang**: Bedarf 0–100 % wird auf 0 … maximale Ventilöffnung (Stufe) abgebildet. Geschrieben wird nur bei ≥ 3 %-Punkten Änderung, beim Öffnen/Schließen, alle 6 h zur Sicherheit oder wenn das TRV einen anderen Wert meldet.

| Profil | Kp [%/K] | Nachstellzeit | Vorausschau | Intervall |
|---|---|---|---|---|
| Flächenheizung | 25 | 4 h | 45 min | 15 min |
| Heizkörper | 25 | 40 min | 12 min | 5 min |

Die Werte wurden mit einem Raummodell (Estrich + Raum, Totzeit, nichtlineares Ventil, schwankender
Vorlaufdruck, Sonne, Tagesgang außen) ermittelt: `python3 tests/sim_clouset.py`. Gegenüber v1.3.3
sinkt die Regelabweichung dort je nach Ventilkennlinie von 1,0–2,2 K RMS auf ca. 0,3 K RMS bei
4–5× weniger Ventilbewegungen.

### Was der Regler lernt (und ob das Machine Learning ist)

| Gelernt | Verfahren | Wirkt auf die Regelung | Sensor (Lernkurve) |
|---|---|---|---|
| Grundbedarf des Raums | bedingte Integration (I-Anteil mit Anti-Windup) | ja | `PID I-Anteil` |
| Wetterabhängigkeit (% Bedarf je K innen/außen) | exponentiell geglättete Regression in ruhigen Phasen | ja | `Gelernte Wetterabhängigkeit` |
| Versatz und Streuung des TRV-Fühlers | gleitender Mittelwert | nur bei Sensorausfall | – |
| **Raummodell** (ab v2.5) | rekursive kleinste Quadrate mit Vergessensfaktor (Online-Systemidentifikation) | nein, Beobachtungsmodus | `Raummodell Zeitkonstante`, `Heizleistung`, `Fremdwärme`, `Prognose 3h`, `Vorhersage-Vorteil` |

Die ersten drei sind adaptive Regelung. Das Raummodell ist ein lernendes Modell im Sinne von Machine Learning, aber bewusst kein neuronales Netz: Es hat drei physikalisch deutbare Parameter, lernt aus wenigen Tagen Daten, läuft auf jedem Home-Assistant-Gerät und kann sagen, wie sicher es sich ist.

**Raummodell**: `dT/dt = a·(T_außen − T) + b·u_Estrich + c`
- `1/a` – Zeitkonstante des Raums in Stunden (wie schnell er ohne Heizung auskühlt),
- `b` – wie schnell volle Heizleistung den Raum erwärmt (K/h), `u_Estrich` ist der Heizbedarf, verzögert um die Speicherzeit des Estrichs (2 h, Heizkörper 15 min),
- `c` – Wärme, die nicht von dieser Heizung kommt: Nachbarn, Sonne, Personen, Geräte (K/h).

Gelernt wird nur in ungestörten Phasen (kein Fenster, keine Zugluft, keine Erholungsphase). Prognosen erscheinen nach einem Tag Lernzeit (96 Regelzyklen). Bei mildem Wetter ist das Ventil meist zu: Dann kann `b` nicht gelernt werden, und das Modell meldet eine niedrige Sicherheit (`confidence`), statt einen Wert zu erfinden.

Simulation (`tests/sim_model.py`, ClouSet-Raum, drei Wochen):

| Woche | gelernte Zeitkonstante | 3-h-Prognosefehler Modell | 3-h-Prognosefehler „bleibt gleich“ |
|---|---|---|---|
| 1 (10 °C außen) | 27–30 h | 0,07–0,11 K | 0,17–0,22 K |
| 2 (4 °C außen) | 33–37 h | 0,10–0,14 K | 0,24–0,28 K |
| 3 (0 °C, Nachtabsenkung) | 23 h | 0,39–0,45 K | 0,63–0,68 K |

Die physikalische Zeitkonstante des simulierten Raums liegt bei etwa 21 h.

#### Warum das Modell (noch) nicht selbst steuert

Ein lernendes Modell ist nicht automatisch der bessere Regler. Für v2.6 wurden zwei Varianten, in denen das Modell mitsteuert, gegen den bestehenden Regler simuliert (ClouSet-Raum, vier Wochen von mildem Herbst bis Kältewelle, mit/ohne Nachtabsenkung, mit/ohne Zugluft, drei Ventilkennlinien, je drei Läufe):

| Variante | RMS-Abweichung | größte Unterschreitung |
|---|---|---|
| bestehender Regler (Trend-Vorausschau, gelernter Grundbedarf + Wetteranteil) | 0,594 K | −2,58 K |
| Modell rechnet die Vorausschau mit (nur wenn es nachweislich besser vorhersagt) | 0,600 K | −2,61 K |
| Modell liefert den Wetteranteil (Steigung a/b statt Bedarf/ΔT), Einzellauf | schlechter: Tagesschwankung ±0,7 statt ±0,5 K | unverändert |
| zum Vergleich: perfekte Wettervorhersage 4 h im Voraus | 0,583 K | −2,60 K |

Die verbleibenden Abweichungen sind physikalisch: Der Estrich gibt Wärme Stunden später ab, als die Außentemperatur im Tagesverlauf schwankt; in der Kältewelle reicht die Heizleistung bei 36 °C Vorlauf nicht; Zugluft ist nicht vorhersehbar. Das kann auch ein Modell nicht wegrechnen. Der Integral-Anteil gleicht dagegen jeden Modellfehler sicher aus. Das ist der Grund, warum er die Regelung behält.

Seit v2.6 misst die Integration deshalb im echten Raum mit, ob das Modell die Temperatur am Ende der Vorausschau (45 min, Heizkörper 12 min) genauer trifft als der Trend, auf den der Regler wirkt: Sensor `Raummodell Vorhersage-Vorteil` (% weniger Fehler als der Trend, negativ = schlechter), Attribute `model_pred_error` / `trend_pred_error` (K, gleitend über ~12 h). Zeigt sich in der Wohnung über Wochen ein klarer Vorteil, ist das die Grundlage, das Modell mitsteuern zu lassen.

Neue Attribute der Klima-Entität: `model_pred_error`, `trend_pred_error`, `model_skill` (ab v2.6), `model_forecast` (Temperaturverlauf der nächsten 6 h für „Ventil wie jetzt“, „Ventil zu“, „Ventil voll auf“, nicht in der Datenbank), `model_demand` (Bedarf, den das Modell für das Soll erwartet), `model_confidence`, `comfort_in_band_24h` (Anteil der letzten 24 h innerhalb ±0,3 K), `comfort_rms_24h`, `comfort_mean_24h`.

### Steuermodi
- **PID** (Standard) – stetig, vorausschauend, lernend
- **PWM/Takt** – Ventil im Zeitraster ganz auf (auf die Stufe) oder zu; linear unabhängig von der Ventilkennlinie, dafür mehr Motorbewegungen
- **Binär** – Zweipunkt mit Hysterese auf die vorhergesagte Temperatur
- **Proportional** – Legacy (Öffnung proportional zur Abweichung, 3 K = voll)

### Preset-Modi (maximale Ventilöffnung)

| Preset | Öffnung |
|--------|---------|
| **\\*** | 0 % (aus) |
| **1** | 20 % |
| **2** | 40 % (Standard, bei ClouSet sättigt der Durchfluss meist darunter) |
| **3** | 60 % |
| **4** | 80 % |
| **5** | 100 % |

### Fenster
- Sensoren pro Thermostat; Wirkung „nur dieser Raum“ oder „alle SonTRV“. Ohne Sensoren: Temperatursturz-Erkennung.
- Ein Fenster/eine Tür muss mindestens **2 min** offen sein (Option „Fenster/Tür: erst nach (s) offen reagieren“), sonst passiert nichts. Kurzes Öffnen der Wohnungstür und prellende Kontakte bewegen das Ventil nicht mehr.
- Offen: Ventil zu, Lernen pausiert. Alle Kreise eines Raums (z. B. Wohnzimmer + Küche) werden gemeinsam eingefroren und freigegeben.
- Zu (Fußboden): Das Ventil bleibt auf der Stellung von vor dem Lüften, bis sich die Luft vom warmen Estrich selbst erholt hat (bis 0,3 K an die Temperatur vor dem Lüften, höchstens 60 min, früher wenn die Erholung stockt). Erst danach regelt und lernt der Regler wieder. Attribut `post_window_soft_active`.
- Zu (Heizkörper): sofort normale Regelung, der Handtuchheizkörper hilft beim Aufwärmen.

### Raum-CSV-Logging
Optional (Optionen). Enthält Temperatur, Quelle, Vorhersage, Steigung, P/I/D/FF, gelernte Vorsteuerung, Ventil, Fenster. Eine Datei im alten v1-Format wird als `.v1.bak` beiseitegelegt.

## 🤝 Unterstützte Hardware

Der Gerätetyp wird automatisch an den Zigbee2MQTT-Entitäten erkannt (Attribut `trv_type`):

| Gerät | Ventilstellung | Raumtemperatur | Kalibrierung |
|---|---|---|---|
| **SONOFF TRVZB** | `valve_opening_degree` + komplementärer `valve_closing_degree` | `external_temperature_input` (+ `temperature_sensor_select`: `remote_temperature`, bei älterem Zigbee2MQTT `external`) | `valve_calibration` |
| **Bosch Heizkörper-Thermostat II** (BTH-RA, RBSH-TRV0-ZB-EU) | `pi_heating_demand` (direkt, wird vom Gerät gehalten) | `remote_temperature`, alle 20 min (Gerät fällt sonst nach 30 min auf den eigenen Sensor zurück) | `valve_adapt_process` |

Beide über Zigbee2MQTT.

## 📚 Dokumentation

- **[Integration README](custom_components/soncloutrv/README.md)** - Ausführliche Dokumentation
- **[Validation Summary](VALIDATION.md)** - ✅ Kompatibilitätsprüfung & Validierung
- **[Plugin-Architektur](README_PLUGIN.md)** - Technische Details zur Plugin-Struktur
- **[Wrapper-Konzept](README_WRAPPER.md)** - Wrapper-Pattern Erklärung
- **[SONOFF TRVZB Details](README_SONOFF_TRVZB.md)** - Hardware-spezifische Informationen
- **[Testing](TESTING.md)** - Test-Setup und -Strategie

## 🔧 Services

- `soncloutrv.calibrate_valve` – TRV-Kalibrierung, danach wird die Stellung neu gesendet
- `soncloutrv.reset_learning` – gelernten Bedarf des Raums zurücksetzen
- `soncloutrv.exercise_valve` – Ventil durchbewegen

## ⚡ Start & Ausfallsicherheit

- Der Start blockiert Home Assistant nicht mehr (v1 wartete bis zu 30 s pro Thermostat). Die Regelung startet nach dem HA-Start, zeitversetzt pro Kreis.
- Ist das TRV nicht erreichbar, wird nichts geschrieben; sobald es wieder da ist, wird alles neu synchronisiert.
- Das TRV wird im Heizbetrieb aktiv auf `heat` gestellt (v1 ließ es nach „Aus“ dauerhaft aus).
- Die externe Temperatur wird bei Änderung und spätestens alle 30 min gesendet.

## ❄️ Betrieb im Winter (ohne manuelle Eingriffe)

- **Saisonschalter**: Alle Thermostate auf `heat` (z. B. per Automation aus einem `input_select`), im Sommer auf `off`. Mehr ist nicht nötig: Sollwerte, Fenster, Sensorausfälle, TRV-Neustarts und der Verkalkungsschutz werden von der Integration behandelt. Vollautomatisch: Statistik-Helfer „3-Tage-Mittel“ auf die Außentemperatur, Automation mit `numeric_state` unter 15 °C (1 h) → Winter, über 18 °C (24 h) → Sommer.
- **Offener Raum mit mehreren Kreisen** (Wohnzimmer + Küche, ein Thermometer): beiden Thermostaten denselben Raum zuweisen. Sie teilen sich dann einen lernenden Regler, beide Ventile bekommen denselben Bedarf, gewichtet über `number.[name]_raum_leistungsanteil` (z. B. 0,8 für den Kreis im wärmeren Teil des Raums). Kp/Ki/Kd/Ka müssen auf beiden gleich sein; die Integration warnt im Log, wenn sie auseinanderlaufen. Die Ventile bewegen sich zeitversetzt, was den gemeinsamen Vorlauf schont.
- **Mehrere Heizungstypen im Raum** (Fußboden + Handtuchheizkörper): Der Heizkörper wird automatisch zur **Zusatzheizung** (Option „Rolle im Raum“, Standard „Automatisch“): Zweipunkt auf die vorhergesagte Temperatur, ein ab 0,5 K unter Soll, aus ab 0,1 K unter Soll, ohne eigenes Lernen. Der Fußboden trägt die Grundlast und lernt den Bedarf, der Heizkörper fängt nur schnelle Einbrüche (Duschen, Tür) ab. Beide bekommen denselben Sollwert.
- **TRV-Sensor als Notfall-Quelle**: nur, wenn sein Offset zum Raumsensor stabil ist (Attribut `trv_sensor_trusted`). Ein Bosch am Rücklauf oder ein TRVZB in der ClouSet-Box misst Rohrtemperatur, sobald Wasser fließt; das erkennt die Integration selbst und hält dann lieber den gelernten Bedarf.
- **Ventil-Öffnungsbeginn bestimmen**: In der Raum-CSV stehen `trv_local_temp` und `valve_opening_percent`. Steigt die TRV-Temperatur erst ab z. B. 12 % Öffnung deutlich an, ist das der Öffnungsbeginn → `number.[name]_ventil_offnungsbeginn`.
- **Fenster**: Sensoren werden beim Start und in jedem Regelzyklus geprüft. Ein Fenster, das beim HA-Neustart bereits offen war, oder ein verpasstes Zigbee-Ereignis führt nicht zu Heizen bei offenem Fenster.
- **Raumsensor stumm**: Viele Sensoren melden nur bei Änderung (0,1 K). Bleibt der Sensor länger als „Sensor-Ausfall nach“ still, wird er weiter verwendet, solange der TRV-eigene Sensor (offsetkorrigiert) innerhalb von 1 K zustimmt (Attribut `sensor_stale`). Erst bei Abweichung oder `unavailable` übernimmt der TRV-Sensor, ohne Sensor der gelernte Grundbedarf.
- **Außensensor**: Nicht in die Sonne hängen, sonst bricht die Wettervorsteuerung an sonnigen Nachmittagen ein (der Wert wird 2 h tiefpassgefiltert, das fängt kurze Spitzen ab, keine Stunden).
- **Keine Nachtabsenkung bei Estrich**: Das Modell zeigt nach einer Absenkung 22–6 Uhr morgens bis zu 2 K Untertemperatur; konstante Sollwerte sind bei Flächenheizung sparsamer und komfortabler.
- **Lernwerte**: I-Anteil und Wettervorsteuerung werden über Neustarts gespeichert (alle 30 min und beim Beenden). Nach Umbauten `button.[name]_lernwerte_zurucksetzen`.

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

### v2.6.1 (2026-10-18) – Raumsensoren mit festem Besitzer 🏷️

Keine Migration, Thermostate, Lernwerte und alle übrigen Entitäten bleiben unverändert.

- **Raum Heizbedarf** und **Raumtemperatur** gibt es pro Raum nur einmal. Welches Thermostat sie bereitstellt, hing bisher davon ab, welches beim Start zuerst eingerichtet wurde. Das wechselte zwischen Neustarts: Einträge blieben als „nicht verfügbar“ zurück (z. B. `sensor.badezimmer_trv_bad_raumtemperatur_2`), die Historie war auf mehrere Entitäten verteilt.
- Der Besitzer wird jetzt aus allen SonTRV-Einträgen und der Entitätsregistrierung bestimmt, nicht mehr aus der Startreihenfolge: zuerst das Thermostat, dessen Raumsensor bereits registriert ist (Entitäts-ID und Historie bleiben), dann der Hauptheizkreis vor einem Zusatzheizkörper (`assist`), dann die kleinste Eintrags-ID.
- Verwaiste Raumsensoren der anderen Thermostate im Raum (und solche eines früheren Raums) werden aus der Registrierung entfernt. Betroffen sind nur diese beiden Raumsensoren, nie Klima- oder andere Entitäten.
- 67 automatische Tests.

### v2.6.0 (2026-10-18) – Prüfstand für das Raummodell 🔬

Keine Migration, alle Entitäten und Lernwerte bleiben, die Regelung ist unverändert.

- **Mitsteuern des Modells simuliert und verworfen**: weder in der Vorausschau noch im Wetteranteil besser als der bestehende Regler (Tabelle unter „Warum das Modell (noch) nicht selbst steuert“).
- **Vorhersage-Vorteil**: Jeder Regelzyklus speichert die Vorhersage des Modells und die des Trends für das Ende der Vorausschau und vergleicht sie danach mit der Messung. Neuer Sensor `Raummodell Vorhersage-Vorteil` mit Langzeitstatistik.
- 59 automatische Tests.

### v2.5.0 (2026-10-18) – Lernendes Raummodell und Auswertungen 🧠

Keine Migration, alle Entitäten und Lernwerte bleiben, die Regelung selbst ist unverändert (identische Simulationsergebnisse).

- **Raummodell** pro Raum und Heizungstyp, online gelernt (rekursive kleinste Quadrate): Zeitkonstante, Heizleistung, Fremdwärme, Prognose für 6 h in drei Szenarien, erwarteter Bedarf. Beobachtungsmodus, steuert nicht.
- **Regelgüte**: Anteil der letzten 24 h innerhalb ±0,3 K, RMS und mittlere Abweichung.
- **6 neue Sensoren pro Thermostat** mit Langzeitstatistik (Lernkurven): Regelgüte 24h, Gelernte Wetterabhängigkeit, Raummodell Zeitkonstante / Heizleistung / Fremdwärme / Prognose 3h. Modellwerte erscheinen nach einem Tag Lernzeit.
- Modell und Regelgüte werden mit den übrigen Lernwerten gespeichert; „Lernwerte zurücksetzen“ setzt auch das Modell zurück.
- Neue Simulation `tests/sim_model.py`, 56 automatische Tests.

### v2.4.1 (2026-10-18) – Zigbee2MQTT 2.x: Temperaturquelle der TRVZB
- Neuere Zigbee2MQTT-Versionen nennen die Option für den externen Sensor `remote_temperature` statt `external`. SonTRV wählt die Option jetzt aus der Optionsliste des Geräts. Seit dem 8.10. lief der Versuch, `external` zu setzen, alle 15 min ins Leere und erzeugte Warnungen im Log.
- Lehnt das Gerät die Umstellung ab, wird es höchstens einmal pro Stunde erneut versucht.

### v2.4.0 (2026-10-18) – Regelung aus zehn Tagen Heizbetrieb nachgeschärft 📈

Grundlage: Verlauf aller 7 Kreise vom 8. bis 18. Oktober (Bedarf, I-Anteil, Vorhersage, Ventil, Fenster). Keine Migration, alle Entitäten und Lernwerte bleiben.

**Befunde in den Daten**
- Flur: Die Wohnungstür ging 10–19 mal am Tag für wenige Sekunden auf. Jede Öffnung schloss das Ventil und öffnete es danach wieder, bis zu 34 Ventilbewegungen am Tag.
- Büro: Der Türkontakt prellte am 14.10. über eine Stunde lang im Sekundentakt.
- Wohnzimmer + Küche: Nach dem Schließen der Balkontür rechnete der Regler 15 min mit dem Temperatureinbruch weiter (80–90 % Bedarf), weil der zweite Kreis des Raums noch eingefroren war. Danach lernte der I-Anteil aus der Erholung der Luft und der Raum lief abends über das Soll.
- Zugluft ohne Fensterkontakt (Flur, offenes Wohnzimmer): Luftstürze von 2 K in 10 min, die sich nach 30–60 min von selbst erholen, wurden von der Vorhersage auf bis zu 3 K Regelabweichung hochgerechnet.
- Flur und Büro lagen nachts tagelang 1–1,5 K über Soll bei geschlossenem Ventil (Nachbarwärme). Der I-Anteil blieb dabei bei 13 % stehen und öffnete das Ventil, sobald das Soll wieder erreicht war.

**Änderungen**
- **Fenster/Tür-Verzögerung** (neue Option, Standard 120 s) gegen kurze Öffnungen und prellende Kontakte.
- **Raumweise Fensterverarbeitung**: alle Kreise eines Raums werden in einem Schritt eingefroren und freigegeben.
- **Erholungsphase nach dem Lüften** (Fußboden): Ventil hält die Stellung von vorher, kein Lernen, bis die Luft sich erholt hat. Ersetzt die bisherige „weiche Phase“.
- **Zugluft-Unterdrückung** (Fußboden): Die Regeltemperatur folgt der Messung höchstens mit 0,8 K/h, so schnell kann der Estrich die Luft nicht bewegen. Bei größerer Abweichung keine Vorhersage und kein Lernen (Attribut `disturbance`). Heizkörper sind davon ausgenommen.
- **Veralteter I-Anteil wird verlernt**, solange der Raum bei geschlossenem Ventil zu warm bleibt (bis auf 0, nicht darunter).
- **Fehler behoben**: Im Bad konnte der Handtuchheizkörper den Fußbodenregler nach einem Fenster dauerhaft eingefroren lassen (Prüfung jetzt nur auf Kreise mit demselben Regler).
- Tests sind unabhängig vom Wochentag (der sonntägliche Verkalkungsschutz pausierte die Regelung mitten in einem Test).

**Simulation** (`tests/sim_disturbances.py`, alter gegen neuen Regler)

| Szenario | Kennzahl | v2.3 | v2.4 |
|---|---|---|---|
| Zugluft 3×/Tag | Ventilbewegungen in 7 Tagen | 205 | 144 |
| Zugluft 3×/Tag | tiefste Untertemperatur | −1,72 K | −1,51 K |
| Nachbarwärme + Zugluft | höchste Übertemperatur | 2,60 K | 1,36 K |
| Nachbarwärme + Zugluft | Regelabweichung RMS | 0,86 K | 0,51 K |
| Nachbarwärme + Zugluft | Ventilbewegungen | 148 | 100 |
| Oktober ohne Störung | Regelabweichung RMS | 0,32 K | 0,31 K |

`tests/sim_clouset.py` und `tests/sim_bath.py` bleiben im Rahmen (Abweichungen unter 0,03 K RMS). 47 automatische Tests.

### v2.3.1 (2026-10-11) – Verkalkungsschutz tagsüber 🔇
- Wöchentliches Ventil-Durchbewegen von Sonntag 03:00–03:50 auf **Sonntag 11:00–11:50** verlegt – die Stellantriebe sind hörbar und haben nachts geweckt
- `schedule`-Attribut des Verkalkungsschutz-Switch zeigt die tatsächliche Uhrzeit

### v2.3.0 (2026-09-30) – ClouSet + Handtuchheizkörper (Bosch am Rücklauf) 🛁

Keine Migration, alle Entitäten und Lernwerte bleiben.

- **Rolle im Raum** (neue Option, Standard „Automatisch“): Ein Heizkörper im selben Raum wie ein Fußbodenkreis arbeitet als Zusatzheizung (Zweipunkt auf die Vorhersage: ein ab −0,5 K, aus ab −0,1 K, kein eigener I-Anteil). Simulation Bad (`tests/sim_bath.py`): mit gleichem Sollwert übernahm der Handtuchheizkörper 46–71 % der Heizarbeit bei über 100 Ventilbewegungen pro Tag; als Zusatzheizung trägt der Fußboden die Grundlast, der Heizkörper 12–14 %, Regelabweichung 0,28–0,29 K RMS, ca. 20 Bewegungen pro Tag.
- **Offener Raum mit mehreren Kreisen** (Wohnzimmer + Küche): unverändert ein gemeinsamer Regler; neu eine Log-Warnung, wenn die Regelparameter der Kreise eines Raums unterschiedlich sind (es gilt sonst stillschweigend der zuletzt geänderte Kreis).
- **TRV-Sensor nur bei stabilem Offset**: Die Streuung des Offsets Raumsensor ↔ TRV-Sensor wird mitgelernt (Attribut `sensor_fallback_deviation`). Über 0,6 K gilt der TRV-Sensor als Rohrtemperatur (Bosch am Rücklauf, TRVZB in der ClouSet-Box) und wird weder als Ersatz noch zur Plausibilitätsprüfung genutzt.
- **Bosch**: Betriebsart „pause“/„schedule“ wird im Heizbetrieb auf „manual“ gestellt (sonst ignoriert oder überschreibt das Gerät die Ventilvorgabe); die Raumtemperatur wird auch im Hold-Modus alle 20 min nachgesendet, damit das Gerät nicht auf seinen Rohrsensor zurückfällt. Attribut `valve_resend_count` und Warnung im Log, wenn das Gerät die Ventilstellung wiederholt selbst ändert.
- **SONOFF TRVZB**: die geräteeigene Fenstererkennung (`open_window`) wird abgeschaltet, sie würde das Ventil hinter dem Rücken der Regelung schließen. Prüfung einmal pro Stunde und bei Wiederverfügbarkeit.
- **Raum-CSV**: neue Spalten `trv_local_temp`, `valve_reported_percent`, `trv_sensor_trusted` (Öffnungsbeginn der Ventile ablesbar). Eine Datei mit altem Spaltenlayout wird mit Zeitstempel beiseitegelegt.
- 40 automatische Tests, neue Simulation `tests/sim_bath.py`.

### v2.2.0 (2026-09-30) – Winterfest ❄️

Kein Neuanlegen, keine Migration: Config-Version bleibt 4, alle Entity-IDs und Lernwerte bleiben erhalten.

- **Fenster beim Start / verpasste Ereignisse**: Fenstersensoren werden beim Start des Regelbetriebs und in jedem Regelzyklus geprüft, nicht nur bei einem Zustandswechsel. Bisher heizte ein Thermostat nach einem HA-Neustart bei bereits offenem Fenster weiter, bis das Fenster erneut geöffnet wurde.
- **Stumme Raumsensoren**: Ein Sensor, der nur bei Änderung meldet, wurde in stabilen Räumen nach 4 h fälschlich durch den TRV-Sensor ersetzt (der neben der Verteilerbox misst und mit dem Ventilzustand schwankt). Jetzt bleibt er die Quelle, solange der TRV-Sensor innerhalb von 1 K zustimmt. Neues Attribut `sensor_stale`.
- **I-Anteil nach Sommer/Sonne**: Untere Grenze −25 % statt −50 %, und während der Übertemperatur-Abschaltung wird ein I-Anteil ≤ 0 nicht weiter abgesenkt. Ein im Sommer auf „Heizen“ gelassener Raum brauchte sonst im Herbst viele Stunden, bis das Ventil überhaupt öffnete.
- **Zieltemperatur aus dem Optionsdialog** wirkt sofort, ohne Neuladen.
- **Außentemperatur**: Wetter-Entitäten werden im Einrichtungsdialog wieder angeboten.
- **Speicher/SD-Karte**: Lernwerte werden alle 30 min statt alle 2 min gespeichert (Abschluss-Schreiben beim Beenden bleibt). Raum-CSV rotiert bei 20 MB nach `.1`.
- **Zieltemperatur und Neuladen**: Wird die Zieltemperatur im Optionsdialog zusammen mit einer strukturellen Änderung (Neuladen) geändert, gewinnt der neue Wert; ein reines Neuladen behält den vom Nutzer gesetzten Wert (Attribut `configured_target_temperature`).
- **Recorder-Entlastung**: Heizdauer, Heizenergie und Ventil-Gesamtlaufzeit werden alle 5 min statt jede Minute fortgeschrieben (rund 5× weniger Datenbankzeilen im Winter), Ventiländerungen werden weiterhin sofort erfasst.
- Tests: 36 automatische Tests (Fenster beim Start, verpasstes Ereignis, stummer Sensor, Optionen live, Log-Rotation, I-Anteil-Grenze).

### v2.1.0 (2026-09-28) – Bosch Heizkörper-Thermostat II

- Unterstützung für Bosch BTH-RA / RBSH-TRV0-ZB-EU: Ventilstellung über `pi_heating_demand`, Raumtemperatur über `remote_temperature` (alle 20 min), Kalibrierung über Ventiladaption
- Automatische Geräteerkennung (SONOFF TRVZB / Bosch), neues Attribut `trv_type`
- Statistik-Sensoren nutzen beim Bosch `pi_heating_demand` als Quelle

### v2.0.0 (2026-09-28) – Vorausschauender Raumregler für ClouSet 🔮

**Regelung**
- Neuer Regelkern (`controller.py`): Trend + Vorhersage über die Totzeit, I-Anteil ohne Abbau am Sollwert, Anti-Windup, gelernte Wettervorsteuerung, Erkennung fehlender Vorlaufwärme
- Heizungstyp Flächenheizung/Heizkörper mit getesteten Profilen; getrennte Regler pro Raum und Typ
- Steuermodus-Auswahl wirkt jetzt wirklich (war in v1 ohne Funktion), neu: PWM
- Lernwerte werden über Neustarts/Neuladen gespeichert

**Fehlerbehebungen**
- TRV wird nach „Aus“ wieder auf `heat` gestellt (sonst blieb das Ventil im Winter zu)
- Statistik-Sensoren lasen eine Motorspannung statt der Ventilöffnung (1500 kWh „Heizenergie“) – korrigiert und einmalig zurückgesetzt
- Verkalkungsschutz lief praktisch nie (Zeitprüfung) und brach mit Fehler ab – neu geplant, funktioniert auch bei ausgeschalteter Heizung
- Jede Zahl-Änderung lud die ganze Integration neu – jetzt live
- „Trägheit“ und Optionen wie Min/Max-Temperatur wurden von der Regelung ignoriert
- Setup blockierte HA bis zu 30 s pro Thermostat
- Raum-Sensoren verschwanden nach dem Neuladen einer Integration
- Config-Entry-Migration schrieb die Version unzulässig direkt und setzte Tuning zurück

**Update-Sicherheit**
- Migration auf Config-Version 4: Entity-IDs bleiben, eigenes Tuning bleibt (D-Anteil wird in die neue Einheit umgerechnet), unveränderte Alt-Standardwerte werden durch das Profil ersetzt
- 29 automatische Tests (inkl. Migration realer v1.3.3-Optionen), Simulation `tests/sim_clouset.py`


### v1.3.0 (2025-12-17) - PID Evolution & Architecture 🧠

**Hauptfeatures:**
- 🌤️ **Wetter-Vorsteuerung (Feed-Forward)** - Nutzt die Außentemperatur (Wetter-Entität oder Sensor), um Heizbedarf vorherzusehen
- 🔋 **Adaptive Polling (Eco-Modus)** - Spart Batterie durch reduziertes Funk-Intervall (30 Min) bei stabiler Temperatur
- 🚀 **Turbo-Start (Smart Start)** - Überwindet die Trägheit beim Starten durch sofortigen I-Boost
- ⚡ **Dynamischer Gain Boost** - Beschleunigt das Aufheizen bei großen Temperaturdifferenzen (>1,5°C)
- 🔇 **Sensor-Rauschfilter** - Ignoriert mikroskopische Temperaturschwankungen (< 0,1°C) für längere Batterielaufzeit
- 🧠 **Vollständiger PID-Regler** - Ersetzt einfache proportionale Logik
  - **P (Proportional)**: Basis-Reaktion (konfigurierbar)
  - **I (Integral)**: Lernt den stationären Wärmebedarf (Anti-Windup geschützt)
  - **D (Derivative)**: Bremst bei Annäherung ans Ziel (Überschwingschutz)
- 🛡️ **Schutzfunktionen**:
  - "Derivative Kick Protection" verhindert Sprünge bei Sollwert-Änderung
  - Rauschunterdrückung für stabile Berechnung
- 🔧 **Live-Tuning**: Kp, Ki, Kd Parameter direkt über UI anpassbar

**Architektur & Optimierung:**
- 🚦 **Traffic-Optimierung** - Temperatur-Sync zum TRV nur noch bei Änderung > 0.1°C
- 🏗️ **Refactoring** - Ventil-Training ("Exercise") zentralisiert in Climate-Entity
- 🔒 **Konfliktfreiheit** - Regelung pausiert automatisch während Ventil-Training
- 🚀 **Performance** - Caching von Entity-IDs und MQTT-Topics

### v1.2.2 (2025-12-17) - Wartung & Optimierung 🔧

**Verbesserungen:**
- ✅ **Optimierte Sensor-Initialisierung** - Reduzierte API-Aufrufe beim Start durch Wiederverwendung der Entity-IDs
- ✅ **Migration-Framework** - Vorbereitung für zukünftige Updates ohne Neu-Einrichtung (`async_migrate_entry`)
- ✅ **Tooling Fixes** - `validate_config.py` funktioniert nun auch im aktuellen Verzeichnis
- 🧹 **Cleanup** - Entfernung veralteter Analysedateien

### v1.1.1 (2025-11-01) - Critical Bug Fixes 🔧

**Kritische Fixes:**
- 🔴 **Thermostat reagiert sofort auf Temperatur-Änderungen** - `async_set_temperature()` triggert jetzt `_async_control_heating()`
- 🔴 **Config Import Fehler behoben** - `CONF_NAME` wird korrekt von `homeassistant.const` importiert
- 🔴 **Event Loop Blockierung eliminiert** - `asyncio.sleep()` durch `async_call_later()` ersetzt in Valve Exercise
- 🔴 **Entity ID Lookup repariert** - Konsistente Entity-ID Konstruktion zwischen Climate und Number/Switch/Button
- 🔴 **Timezone-Aware DateTime** - Alle `datetime.now()` durch `dt_util.now()` ersetzt

**Verbesserungen:**
- ✅ **Robuste Exception Handling** - Umfassendes Error Handling in Platform Setup und Entity Lookups
- ✅ **Config Entry Merge** - Options Updates überschreiben keine kritischen Einstellungen mehr
- ✅ **Code Quality** - Spezifische Exception Types statt bare `except:` clauses

**Behobene Probleme:**
- ❌ Thermostat bleibt im IDLE nach Temperatur-Eingabe
- ❌ Integration lädt nicht: "cannot import name 'CONF_NAME'"
- ❌ Home Assistant friert ein während Valve Exercise
- ❌ Number Entities haben keine Wirkung
- ❌ Switch/Button finden Climate Entity nicht

**Status:** ✅ Vollständig getestet und produktionsreif

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
