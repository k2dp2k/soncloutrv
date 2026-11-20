# Vorfall Bad 17.–20.11.2026: Fußboden heiß, Handtuchheizkörper dauerhaft an

## Symptom
Der Fußboden im Bad war sehr heiß. Am 20.11. um 13:33 wurden Schlafzimmer, Flur, Bad und Handtuchheizkörper von Hand ausgeschaltet.

## Ablauf (aus den Daten in Home Assistant)

| Zeit | Ereignis |
|---|---|
| 17.11. 14:51 | `sensor.temp_bad_battery` = 0 % |
| 17.11. 14:59 | letzte Meldung von `sensor.temp_bad_temperature` (22,7 °C). Home Assistant zeigt den Wert weiter an, nicht „nicht verfügbar“ |
| 18.11. 18:18–19:11 | Badfenster offen, Bosch-Fühler fällt von 22,7 auf 20,8 °C |
| 18.11. 19:11 | Fenster zu, Handtuchheizkörper (Rolle „Zusatzheizung“) geht auf 100 %, korrekt bei 20,9 °C |
| 18.11. ~20:15 | Bosch-Fühler wieder ≥ 21,6 °C, Quelle springt zurück auf den toten Raumsensor (Abstand < 1 K) |
| 18.11. bis 20.11. 13:34 | Handtuchheizkörper durchgehend 100 %. Der Regler rechnet weiter mit 21,7 °C (letzter Bosch-Wert), also 0,8 K unter Soll |

## Ursache (Fehler in SonTRV ≤ 2.7.0)
- Der Regler-Trend bekommt Raumsensor-Werte nur über Zustandsereignisse. Ein toter Sensor sendet keine Ereignisse mehr. Nach dem Wechsel zurück auf „sensor“ blieb deshalb der letzte TRV-Wert im Trend stehen.
- Die Plausibilitätsprüfung (TRV-Fühler stimmt auf 1 K zu) ist zirkulär: TRVZB und Bosch zeigen oft nur den Wert an, den SonTRV ihnen schickt.
- Die Zusatzheizung hatte keine Zeitgrenze.
- Der Rücklauf des Handtuchheizkörpers geht durch den Fußbodenkreis, deshalb wurde auch der Boden heiß.

## Behoben in v2.7.1 (installiert am 20.11.)
- Ein stummer Sensor wird in jedem Regelzyklus in den Trend übernommen.
- Ohne jede Meldung für 3× „Sensor-Ausfall nach“ (mindestens 12 h) gilt der Sensor als ausgefallen. Folge: gelernter Grundbedarf, Zusatzheizkörper aus, Benachrichtigung in Home Assistant, Attribut `sensor_failed`.
- Der Zusatzheizkörper läuft höchstens 3 h am Stück, danach 1 h Sperre.

## Zu tun
- Batterie von „Temp_Bad“ wechseln (CR2032 bzw. Typ laut Sensor).
- Danach Bad und Handtuchheizkörper wieder auf „Heizen“ stellen, ebenso Flur und Schlafzimmer, falls die nur vorsorglich aus sind.
- Optional: In Home Assistant eine Batterie-Warnung einrichten. Battery Notes ist schon installiert.
