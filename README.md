# Vestel EVC04 Wallbox für Home Assistant

Rein lesende Integration für die Vestel EVC04 über Modbus TCP – mit **Ereignisprotokoll** und **RFID-Anzeige**. Kommt ohne pymodbus aus und bringt einen eigenen, minimalen Modbus-Client mit.

[![Open HACS Repository on My Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fumagallis4ever&repository=vestel-evc04&category=integration)
[![Add Integration to My Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=vestel_evc04)

## Installation über HACS

1. Oben auf **„Open HACS Repository on My“** tippen (oder HACS → Benutzerdefinierte Repositories → `https://github.com/fumagallis4ever/vestel-evc04`, Typ „Integration“)
2. „Vestel EVC04 Wallbox“ herunterladen und Home Assistant neu starten
3. Auf **„Add Integration to My“** tippen (oder Einstellungen → Geräte & Dienste → Integration hinzufügen → „Vestel EVC04 Wallbox“)

Voreinstellung: Port 502, Unit-ID 255. Modbus TCP muss in der Weboberfläche der Wallbox aktiviert sein.

## Wichtig: nur ein Modbus-Master – zusammen mit evcc über den Proxy

Die EVC04 akzeptiert laut Vestel-Spezifikation **nur eine aktive Modbus-Verbindung**. Läuft evcc, bitte nicht direkt auf Port 502 der Wallbox verbinden, sondern über den Modbus-Proxy von evcc (`evcc.yaml`):

```yaml
modbusproxy:
  - port: 5021              # freier Port auf dem evcc-Host
    uri: 192.168.30.166:502 # IP der Wallbox
    readonly: true          # Home Assistant darf nur lesen
```

In der Integration dann als Host die IP des evcc-Hosts und Port `5021` eintragen.

## Entities

- Ladepunkt-, Kabel- und Gerätestatus
- Ladeleistung gesamt und je Phase, Strom und Spannung je Phase
- Zählerstand, Energie und Dauer des aktuellen Ladevorgangs
- Ladestromvorgabe, Fehlercode, Strom-Grenzwerte, Failsafe-Einstellungen (Diagnose)
- Binärsensoren „Ladevorgang aktiv“ und „Fahrzeug verbunden“
- **Letzte RFID-Karte** – UID aus Input-Register 1516 (15 Register, UTF-16), Attribute mit Rohdaten (Hex) und Zeitpunkt. Benötigt Wallbox-Firmware ≥ 3.156
- **Ereignisprotokoll** – letzte 50 Einträge im Attribut `eintraege` (gespeichert werden 200, auch über Neustarts)
- **Modbus-Register** (Diagnose) – Rohwerte aller gelesenen Register (Attribut `register`) und die letzten 100 Änderungen mit Zeit, alt/neu (Attribut `aenderungen`); Zustand = Anzahl Änderungen bei der letzten Abfrage
- **Modbus-Kommunikation** (Diagnose) – Abfragedauer, Anzahl Abfragen/Fehler, letzter Fehler
- Button **Protokoll leeren**

## RFID über die Weboberfläche (optional)

Per Modbus gibt die Wallbox die Karten-ID nur während eines Ladevorgangs heraus (Register 1516). Jede Kartennutzung – auch ohne angestecktes Fahrzeug, inkl. „abgelehnt“ – steht aber in den Geräte-Logs der Weboberfläche. Die Integration kann diese abrufen:

Einstellungen → Geräte & Dienste → Vestel EVC04 Wallbox → **Konfigurieren**

- IP-Adresse der Wallbox (nicht die des evcc-Proxys)
- Benutzername/Passwort der Weboberfläche
- Abrufintervall in Minuten (Standard 5, 0 = aus). Die Box packt die Logs bei jedem Abruf neu, daher nicht zu kurz wählen.
- Kartennamen, z. B. `FCF70F46=Michael, DCA1461E=Bea`

Zusätzlich gibt es dann den Sensor **Letzter Ladevorgang** (kWh, Karte, Start/Ende; Liste der letzten 20 im Attribut `ladevorgaenge`) und den Button **Wallbox-Logs abrufen**.

### Was protokolliert wird

| Typ | Ereignis |
|---|---|
| `rfid` | Kartennutzung mit Ergebnis (angenommen, abgelehnt, Freigabe abgelaufen) über die Weboberfläche; Karte im Ladevorgang über Modbus |
| `ladevorgang` | Start (mit RFID), Ende (mit Energie und Dauer), abgeschlossene Ladevorgänge aus der Weboberfläche |
| `status` | Wechsel von Ladepunkt-, Kabel-, Gerätestatus, Ladestromvorgabe |
| `fehler` | Änderung des Fehlercodes |
| `verbindung` | Verbindung hergestellt, verloren, wiederhergestellt |

Jeder Eintrag wird zusätzlich als Event `vestel_evc04_ereignis` gefeuert (für Automationen) und erscheint im Logbuch.

## Dashboard-Karte für das Protokoll

```yaml
type: markdown
title: Wallbox-Protokoll
content: >-
  {% set e = state_attr('sensor.vestel_wallbox_ereignisprotokoll', 'eintraege') or [] %}
  | Zeit | Typ | Ereignis |
  |:--|:--|:--|
  {% for x in e[:30] -%}
  | {{ as_timestamp(x.zeit) | timestamp_custom('%d.%m. %H:%M:%S') }} | {{ x.typ }} | {{ x.text }} |
  {% endfor %}
```

Die Integration schreibt keine Register und ändert keine Einstellungen der Wallbox.
