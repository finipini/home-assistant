"""
Component to track electricity tariff.

For more details about this component, please refer to the documentation
at http://github.com/dgomes/home-assistant-custom-components/electricity/
"""
import logging

from electricity.tariffs import Operators
import voluptuous as vol

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import CONF_OPERATOR, CONF_PLAN, COUNTRY

_LOGGER = logging.getLogger(__name__)

ATTR_TARIFFS = "tariffs"

DOMAIN = "electricity"

ICON = "mdi:transmission-tower"

UTILITY_METER_NAME_FORMAT = "{} {}"

PLATFORM_SCHEMA = vol.Schema(
    {
        vol.Required("operator"): vol.In(Operators[COUNTRY].keys()),
        vol.Required("plan"): vol.In(
            list(
                {
                    str(p)
                    for plans in Operators[COUNTRY].values()
                    for p in plans.tariff_periods()
                }
            )
        ),
    }
)


async def async_setup(hass, config, async_add_entities):
    """Set up an electricity monitor."""
    entities = []

    for name, cfg in config[DOMAIN].items():
        _LOGGER.debug(name, cfg)
        entities.append(EletricityEntity(name, cfg))

    async_add_entities(entities)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up an electricity monitor from a Config Entry."""

    async_add_entities([EletricityEntity(config_entry.title, config_entry.data)])


class EletricityEntity(Entity):
    """Representation of an Electricity Contract."""

    def __init__(self, name, config):
        """Initialize an Electricity Contract."""
        self._name = name
        self.operator = config[CONF_OPERATOR]
        self.plan = config[CONF_PLAN]
        self._tariffs = []
        self._state = None

    async def async_added_to_hass(self):
        """Setups all required entities and automations."""

        self.my_plan = Operators[COUNTRY][self.operator](plan=self.plan)
        self._state = self.my_plan.current_tariff(dt_util.now())
        self._tariffs = self.my_plan.tariffs()

        async_track_time_change(self.hass, self.timer_update, minute=range(0, 60, 15))

    @callback
    def timer_update(self, now):
        """Change tariff based on timer."""

        new_state = self.my_plan.current_tariff(now)

        if new_state != self._state:
            _LOGGER.debug("Changing from %s to %s", self._state, new_state)
            self._state = new_state
            self.schedule_update_ha_state()

    @property
    def should_poll(self):
        """If entity should be polled."""
        return False

    @property
    def name(self):
        """Return the name of the Electricity contract."""
        return self._name

    @property
    def state(self):
        """Return the state as the current tariff."""
        return self._state

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return ICON

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        if self._tariffs:
            return {
                ATTR_TARIFFS: self._tariffs,
            }
