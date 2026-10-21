"""Constants for the Aareon Mieterportal integration."""

from datetime import timedelta

DOMAIN = "aareon_crm"
DEFAULT_PORTAL_URL = "https://example-town-crm.aareon.com"
UPDATE_INTERVAL = timedelta(hours=6)
HISTORY_START = "2019-01-01"

CONF_PORTAL_URL = "portal_url"
CONF_CONTRACTS = "contracts"

SERVICE_HEATING = "HEATING"
SERVICE_HOT_WATER = "HOT_WATER"
# Portal service name -> key used in statistic ids, sensors and translations.
SERVICE_KEYS = {SERVICE_HEATING: "heating", SERVICE_HOT_WATER: "hot_water"}
CONF_PREFIX = "prefix"
CONF_NAMES = "names"
