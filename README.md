# Mijn Interrand for Home Assistant

Custom integration that reads your DifTar balance (*huidig saldo*) and related
data from the [Mijn Interrand](https://www.mijninterrand.be/) customer portal.

Interrand has no public API. The integration logs in to the portal with your
username and password and reads the *Saldo en verrichtingen* page, the same
way your browser does. It polls every 6 hours.

## Sensors

| Entity | Description |
|---|---|
| `sensor.interrand_balance` | Current balance in EUR. Attributes: customer number, OGM payment reference, residents, address, and the 10 most recent transactions. |
| `sensor.interrand_last_transaction` | Amount of the most recent transaction, with its date, type and description as attributes. |
| `sensor.interrand_last_weighed_amount` | Weight in kg of the most recent *Gewicht* transaction. |
| `sensor.interrand_next_collection_<fraction>` | Next collection date for each fraction listed on the portal (e.g. `restafval`, `gft`). |

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add the URL of this repository with category **Integration**.
3. Install **Mijn Interrand** and restart Home Assistant.

### Manual

Copy `custom_components/mijn_interrand` into the `custom_components` folder of
your Home Assistant configuration and restart.

## Configuration

**Settings → Devices & services → Add integration → Mijn Interrand**, then
enter the username and password you use on www.mijninterrand.be.

If the password changes, Home Assistant will ask you to re-authenticate.

## Example: low balance notification

```yaml
automation:
  - alias: Interrand balance low
    triggers:
      - trigger: numeric_state
        entity_id: sensor.interrand_balance
        below: 5
    actions:
      - action: notify.notify
        data:
          message: >
            Interrand saldo is {{ states('sensor.interrand_balance') }} EUR.
            Pay with OGM {{ state_attr('sensor.interrand_balance', 'ogm') }}.
```

## Limitations

- The integration scrapes the portal's HTML, so a redesign of the site can break it.
- Accounts with more than one *aansluitpunt* (address) have not been tested;
  the integration reads whichever one the portal shows after login.
- The *last weighed amount* only looks at the 10 most recent transactions.
