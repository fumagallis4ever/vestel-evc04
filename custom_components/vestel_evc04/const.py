"""Konstanten für die Vestel EVC04 Integration."""

DOMAIN = "vestel_evc04"

CONF_UNIT_ID = "unit_id"

DEFAULT_HOST = "192.168.30.166"
DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 255
DEFAULT_SCAN_INTERVAL = 10

# Register 1000
CHARGEPOINT_STATE = {
    0: "Verfügbar",
    1: "Vorbereitung",
    2: "Lädt",
    3: "Pausiert (Wallbox)",
    4: "Pausiert (Fahrzeug)",
    5: "Beendet",
    6: "Reserviert",
    7: "Nicht verfügbar",
    8: "Störung",
}

# Register 1002
EQUIPMENT_STATE = {
    0: "Initialisierung",
    1: "Betrieb",
    2: "Störung",
    3: "Deaktiviert",
    4: "Update",
}

# Register 1004
CABLE_STATE = {
    0: "Kein Kabel",
    1: "Kabel steckt, kein Fahrzeug",
    2: "Fahrzeug verbunden",
    3: "Fahrzeug verbunden, Kabel verriegelt",
}

# RFID (ab Firmware 3.156): Input-Register 1516, 15 Register, UTF-16BE
REG_RFID = 1516
REG_RFID_COUNT = 15

# Ereignisprotokoll
EVENT_NAME = f"{DOMAIN}_ereignis"
LOG_MAX_ENTRIES = 200
LOG_ATTR_ENTRIES = 50
STORAGE_VERSION = 1

# Weboberfläche (Optionen)
CONF_WEB_HOST = "web_host"
CONF_WEB_USER = "web_benutzer"
CONF_WEB_PASSWORD = "web_passwort"
CONF_WEB_INTERVAL = "web_intervall"
CONF_CARD_NAMES = "kartennamen"
DEFAULT_WEB_USER = "admin"
DEFAULT_WEB_INTERVAL = 5  # Minuten, 0 = aus
WEB_SEEN_MAX = 1000

RFID_RESULT = {
    "Accepted": "angenommen",
    "Invalid": "abgelehnt (unbekannte Karte)",
    "Blocked": "abgelehnt (gesperrt)",
    "Expired": "abgelehnt (abgelaufen)",
    "ConcurrentTx": "abgelehnt (bereits in Verwendung)",
    "Timeout": "Freigabe abgelaufen (kein Fahrzeug angesteckt)",
}

# Bezeichnungen der gelesenen Register (IR = Input, HR = Holding)
REG_NAMES: dict[int, str] = {
    1000: "Ladepunktstatus",
    1001: "Ladestatus",
    1002: "Gerätestatus",
    1004: "Kabelstatus",
    1006: "Fehlercode (hi)",
    1007: "Fehlercode (lo)",
    1008: "Strom L1 (mA)",
    1010: "Strom L2 (mA)",
    1012: "Strom L3 (mA)",
    1014: "Spannung L1 (V)",
    1016: "Spannung L2 (V)",
    1018: "Spannung L3 (V)",
    1020: "Leistung gesamt (hi)",
    1021: "Leistung gesamt (lo, W)",
    1024: "Leistung L1 (hi)",
    1025: "Leistung L1 (lo, W)",
    1028: "Leistung L2 (hi)",
    1029: "Leistung L2 (lo, W)",
    1032: "Leistung L3 (hi)",
    1033: "Leistung L3 (lo, W)",
    1036: "Zählerstand (hi)",
    1037: "Zählerstand (lo, 0,1 kWh)",
    1100: "Max. Ladestrom Wallbox (A)",
    1102: "Min. Ladestrom Wallbox (A)",
    1104: "Max. Ladestrom Kabel (A)",
    1502: "Energie Ladevorgang (hi)",
    1503: "Energie Ladevorgang (lo, Wh)",
    1504: "Startzeit Ladevorgang (hi)",
    1505: "Startzeit Ladevorgang (lo)",
    1508: "Dauer Ladevorgang (hi)",
    1509: "Dauer Ladevorgang (lo, s)",
    2000: "Failsafe-Strom (A)",
    2002: "Failsafe-Timeout (s)",
    5004: "Ladestromvorgabe (A)",
}
for _i in range(15):
    REG_NAMES[1516 + _i] = f"RFID Zeichen {_i + 1}"
REG_LOG_MAX = 200
