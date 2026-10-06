# Mijn Interrand for Home Assistant

Custom integration for Interrand customers (Overijse, Hoeilaart, Tervuren). It combines:

- the [Mijn Interrand](https://www.mijninterrand.be/) customer portal: your DifTar balance (*huidig saldo*) and transactions;
- the [Recycle!](https://www.recycleapp.be/) app: the collection calendar for your address and the opening hours of your recycling park.

Interrand has no public API. The integration logs in to the portal with your
username and password and reads the *Saldo en verrichtingen* page, the same
way your browser does. The collection calendar comes from the public API
behind recycleapp.be.

## Entities

| Entity | Description |
|---|---|
| `sensor.interrand_balance` | Current balance in EUR. Attributes: customer number, OGM payment reference, residents, address, and the 10 most recent transactions. |
| `sensor.interrand_last_transaction` | Amount of the most recent transaction, with its date, type and description as attributes. |
| `sensor.interrand_last_weighed_amount` | Weight in kg of the most recent *Gewicht* transaction. |
| `sensor.interrand_next_collection_<fraction>` | Next collection date per fraction (`restafval`, `gft`, `pmd`, `papier_karton`, ...). Attributes: `days_until`, the next 5 dates, full fraction name and its color. |
| `calendar.interrand_waste_collection` | All collections as all-day events, for the calendar dashboard and calendar triggers. |
| `binary_sensor.interrand_recycling_park_<park>` | On while the recycling park is open. Attributes: today's hours, next opening/closing time, weekly opening hours and address. |

The balance is refreshed every 6 hours, the collection calendar every 12
hours. Collection dates move on to the next date right after midnight.

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add the URL of this repository with category **Integration**.
3. Install **Mijn Interrand** and restart Home Assistant.

### Manual

Copy `custom_components/mijn_interrand` into the `custom_components` folder of
your Home Assistant configuration and restart.

## Configuration

**Settings → Devices & services → Add integration → Mijn Interrand**:

1. Enter the username and password you use on www.mijninterrand.be.
2. Check your address. It is filled in from the portal.
3. Pick your recycling park.

To change the address or recycling park later, open the integration's menu and
choose **Reconfigure**. If the password changes, Home Assistant asks you to
re-authenticate.

### Upgrading from 0.1.x

Version 0.1 only knew the portal and showed the next restafval/gft date from
it. After upgrading, a repair notice asks you to add your address via
**Reconfigure**. The existing `sensor.interrand_next_collection_restafval`
and `..._gft` keep their entity IDs and switch to the Recycle! calendar, and
sensors for the other fractions are added.

## Examples

Reminder the evening before a collection:

```yaml
automation:
  - alias: Put the bins out
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.interrand_waste_collection
        offset: "-5:00:00"
    actions:
      - action: notify.notify
        data:
          message: "Tomorrow: {{ trigger.calendar_event.summary }}"
```

Low balance notification:

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

- The portal part scrapes HTML, so a redesign of the site can break it.
- Accounts with more than one *aansluitpunt* (address) have not been tested;
  the integration reads whichever one the portal shows after login.
- The *last weighed amount* only looks at the 10 most recent transactions.
- Recycle! usually publishes the calendar until the end of the current year;
  next year's dates appear once they are published.
