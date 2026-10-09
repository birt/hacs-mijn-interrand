"""Constants for the Mijn Interrand integration."""
from datetime import timedelta

DOMAIN = "mijn_interrand"

# The balance only changes after a collection or a payment.
UPDATE_INTERVAL = timedelta(hours=6)
RECYCLE_UPDATE_INTERVAL = timedelta(hours=12)

# When a fetch fails, keep showing the last data and retry sooner. Give up
# (sensors become unavailable) once the data is older than the max age.
RETRY_INTERVAL = timedelta(minutes=30)
PORTAL_MAX_STALE = timedelta(days=1)
RECYCLE_MAX_STALE = timedelta(days=3)

# How far ahead to fetch the collection calendar.
RECYCLE_LOOKAHEAD = timedelta(days=365)

# Number of recent transactions exposed as attributes.
TRANSACTION_COUNT = 10

CONF_ZIPCODE = "zipcode"
CONF_STREET = "street"
CONF_HOUSE_NUMBER = "house_number"
CONF_ZIPCODE_ID = "zipcode_id"
CONF_STREET_ID = "street_id"
CONF_RECYCLING_PARK = "recycling_park"
