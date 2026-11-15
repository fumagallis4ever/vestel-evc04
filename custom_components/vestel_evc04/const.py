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
