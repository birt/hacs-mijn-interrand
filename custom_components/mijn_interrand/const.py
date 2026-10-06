"""Constants for the Mijn Interrand integration."""
from datetime import timedelta

DOMAIN = "mijn_interrand"

# The balance only changes after a collection or a payment.
UPDATE_INTERVAL = timedelta(hours=6)

# Number of recent transactions exposed as attributes.
TRANSACTION_COUNT = 10
