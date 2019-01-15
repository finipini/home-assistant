"""
Utility meter from sensors providing raw data.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.utility_meter/
"""
import logging

from decimal import Decimal, DecimalException
import voluptuous as vol

import homeassistant.util.dt as dt_util
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (DOMAIN, PLATFORM_SCHEMA)
from homeassistant.const import (
    CONF_NAME, ATTR_UNIT_OF_MEASUREMENT, ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_START, STATE_UNKNOWN, STATE_UNAVAILABLE)
from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change, async_track_time_change)
from homeassistant.helpers.dispatcher import (
    dispatcher_send, async_dispatcher_connect)
from homeassistant.helpers.restore_state import RestoreEntity
from .const import (SIGNAL_START_PAUSE_METER, SIGNAL_RESET_METER,
    HOURLY, WEEKLY, MONTHLY, YEARLY, METER_TYPES)

_LOGGER = logging.getLogger(__name__)

ATTR_SOURCE_ID = 'source'
ATTR_STATUS = 'status'
ATTR_PERIOD = 'meter_period'
ATTR_LAST_PERIOD = 'last_period'
ATTR_LAST_RESET = 'last_reset'

CONF_SOURCE_SENSOR = 'source'
CONF_METER_TYPE = 'cycle'
CONF_METER_OFFSET = 'offset'
CONF_PAUSED = 'paused'

ICON = 'mdi:counter'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SOURCE_SENSOR): cv.entity_id,
    vol.Optional(CONF_NAME): cv.string,
    vol.Optional(CONF_METER_TYPE): vol.In(METER_TYPES),
    vol.Optional(CONF_METER_OFFSET, default=0): cv.positive_int,
    vol.Optional(CONF_PAUSED, default=False): cv.boolean,
})

PRECISION = 3
PAUSED = "paused"
COLLECTING = "collecting"

async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the utility meter sensor."""
    conf = discovery_info if discovery_info else config

    meter = UtilityMeterSensor(conf[CONF_SOURCE_SENSOR],
                               conf.get(CONF_NAME),
                               conf.get(CONF_METER_TYPE),
                               conf.get(CONF_METER_OFFSET),
                               conf.get(CONF_PAUSED))

    async_add_entities([meter])


class UtilityMeterSensor(RestoreEntity):
    """Representation of an utility meter sensor."""

    def __init__(self, source_entity, name, meter_type, meter_offset=0,
                 paused=False):
        """Initialize the Utility Meter sensor."""
        self._sensor_source_id = source_entity
        self._state = 0
        self._last_period = 0
        self._last_reset = dt_util.now()
        # _collecting initializes in inverted logic
        self._collecting = None if not paused else lambda: None
        if name:
            self._name = name
        else:
            self._name = '{} meter'.format(source_entity)
        self._unit_of_measurement = None
        self._period = meter_type
        self._period_offset = meter_offset

    @callback
    def async_reading(self, entity, old_state, new_state):
        """Handle the sensor state changes."""
        if any([old_state is None,
                old_state.state in [STATE_UNKNOWN, STATE_UNAVAILABLE],
                new_state.state in [STATE_UNKNOWN, STATE_UNAVAILABLE]]):
            return

        if self._unit_of_measurement is None and\
           new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) is not None:
            self._unit_of_measurement = new_state.attributes.get(
                ATTR_UNIT_OF_MEASUREMENT)

        try:
            diff = Decimal(new_state.state) - Decimal(old_state.state)

            if diff < 0:
                # Source sensor just rolled over for unknow reasons,
                return
            self._state += diff

        except ValueError as err:
            _LOGGER.warning("While processing state changes: %s", err)
        except DecimalException as err:
            _LOGGER.warning("Invalid state (%s > %s): %s",
                            old_state.state, new_state.state, err)
        self.async_schedule_update_ha_state()

    async def async_start_pause_meter(self, entity_id):
        """Start/Pause meter."""
        if self.entity_id != entity_id:
            return
        if self._collecting is None:
            # Start collecting
            self._collecting = async_track_state_change(
                self.hass, self._sensor_source_id, self.async_reading)
        else:
            # Pause collecting by cancel of async_track_state_change
            self._collecting()
            self._collecting = None

        _LOGGER.debug("%s - %s - source <%s>", self._name,
                      COLLECTING if self._collecting is not None
                      else PAUSED, self._sensor_source_id)

        await self.async_update_ha_state()

    async def _async_reset_meter(self, event):
        """Determine cycle - Helper function for larger then daily cycles."""
        now = dt_util.now()
        if self._period == WEEKLY and now.weekday() != self._period_offset:
            return
        if self._period == MONTHLY and\
                now.day != (1 + self._period_offset):
            return
        if self._period == YEARLY and\
                (now.month != (1 + self._period_offset) or now.day != 1):
            return
        await self.async_reset_meter(self.entity_id)

    async def async_reset_meter(self, entity_id):
        """Reset meter."""
        if self.entity_id != entity_id:
            return
        _LOGGER.debug("Reset utility meter <%s>", self.entity_id)
        self._last_reset = dt_util.now()
        self._last_period = str(self._state)
        self._state = 0
        await self.async_update_ha_state()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if self._period == HOURLY:
            async_track_time_change(self.hass, self._async_reset_meter,
                                    minute=self._period_offset, second=0)
        elif self._period == DAILY:
            async_track_time_change(self.hass, self._async_reset_meter,
                                    hour=self._period_offset, minute=0,
                                    second=0)
        elif self._period in [WEEKLY, MONTHLY, YEARLY]:
            async_track_time_change(self.hass, self._async_reset_meter,
                                    hour=0, minute=0, second=0)

        async_dispatcher_connect(
            self.hass, SIGNAL_START_PAUSE_METER, self.async_start_pause_meter)

        async_dispatcher_connect(
            self.hass, SIGNAL_RESET_METER, self.async_reset_meter)

        state = await self.async_get_last_state()
        if state:
            self._state = Decimal(state.state)
            self._unit_of_measurement = state.attributes.get(
                ATTR_UNIT_OF_MEASUREMENT)
            self._last_period = state.attributes.get(ATTR_LAST_PERIOD)
            self._last_reset = state.attributes.get(ATTR_LAST_RESET)
            await self.async_update_ha_state()
            if state.attributes.get(ATTR_STATUS) == PAUSED:
                # Fake cancelation function to init the meter paused
                self._collecting = lambda: None
            else:
                # necessary to assure full restoration
                self._collecting = None

        @callback
        def async_source_tracking(event):
            """Wait for source to be ready, then start meter."""
            dispatcher_send(self.hass, SIGNAL_START_PAUSE_METER,
                            self.entity_id)

        self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_START, async_source_tracking)

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return self._unit_of_measurement

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def device_state_attributes(self):
        """Return the state attributes of the sensor."""
        state_attr = {
            ATTR_SOURCE_ID: self._sensor_source_id,
            ATTR_STATUS: PAUSED if self._collecting is None else COLLECTING,
            ATTR_LAST_PERIOD: self._last_period,
            ATTR_LAST_RESET: self._last_reset,
        }
        if self._period is not None:
            state_attr[ATTR_PERIOD] = self._period
        return state_attr

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return ICON
