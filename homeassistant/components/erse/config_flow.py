"""Config flow for Entidade Reguladora dos Serviços Energéticos integration."""
import logging

from electricity.tariffs import Operators
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.util import slugify

from .const import (  # pylint:disable=unused-import
    CONF_OPERATOR,
    CONF_PLAN,
    COUNTRY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OPERATOR): vol.In(Operators[COUNTRY].keys()),
        vol.Required(CONF_PLAN): vol.In(
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


async def validate_input(hass: core.HomeAssistant, data):
    """Test if operator and plan are valid."""

    if data[CONF_OPERATOR] not in Operators[COUNTRY]:
        raise InvalidOperator

    if data[CONF_PLAN] not in Operators[COUNTRY][data[CONF_OPERATOR]].tariff_periods():
        raise InvalidPlan

    return {CONF_OPERATOR: data[CONF_OPERATOR], CONF_PLAN: data[CONF_PLAN]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Entidade Reguladora dos Serviços Energéticos."""

    VERSION = 1
    # TODO pick one of the available connection classes in homeassistant/config_entries.py
    CONNECTION_CLASS = config_entries.CONN_CLASS_UNKNOWN

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(
                    title=slugify(f"{info[CONF_OPERATOR]} - {info[CONF_PLAN]}"),
                    data=user_input,
                )
            except InvalidOperator:
                errors["base"] = "invalid_operator"
            except InvalidPlan:
                errors["base"] = "invalid_plan"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class InvalidOperator(exceptions.HomeAssistantError):
    """Error to indicate there is invalid operator."""


class InvalidPlan(exceptions.HomeAssistantError):
    """Error to indicate there is invalid plan."""
