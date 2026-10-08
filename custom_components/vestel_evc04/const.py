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
