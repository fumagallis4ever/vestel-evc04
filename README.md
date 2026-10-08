# Vestel EVC04 Wallbox für Home Assistant

Rein lesende Integration für die Vestel EVC04 über Modbus TCP. Kommt ohne pymodbus aus und bringt einen eigenen, minimalen Modbus-Client mit.

## Installation über HACS

1. HACS → Benutzerdefinierte Repositories → `https://github.com/fumagallis4ever/vestel-evc04`, Typ „Integration“
2. „Vestel EVC04 Wallbox“ installieren und Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Vestel EVC04 Wallbox“

Voreinstellung: Port 502, Unit-ID 255. Modbus TCP muss in der Weboberfläche der Wallbox aktiviert sein.

## Entities

- Ladepunkt-, Kabel- und Gerätestatus
- Ladeleistung gesamt und je Phase, Strom und Spannung je Phase
- Zählerstand, Energie und Dauer des aktuellen Ladevorgangs
- Ladestromvorgabe, Fehlercode, Strom-Grenzwerte, Failsafe-Einstellungen (Diagnose)
- Binärsensoren „Ladevorgang aktiv“ und „Fahrzeug verbunden“

Die Integration schreibt keine Register und verträgt sich daher mit evcc.
