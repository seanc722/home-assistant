"""
Support for Twilio.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/twilio/
"""
import asyncio
import voluptuous as vol
import logging
import homeassistant.helpers.config_validation as cv
from typing import Any, Dict, Tuple  # NOQA
from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES, ATTR_ENTITY_ID,
    CONF_FRIENDLY_NAME, STATE_OFF,
    SERVICE_TURN_OFF, SERVICE_TURN_ON,
    TEMP_FAHRENHEIT, TEMP_CELSIUS, HTTP_BAD_REQUEST, 
    HTTP_UNAUTHORIZED)
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.loader import bind_hass
from homeassistant.components.http import HomeAssistantView
from homeassistant.components import (
    automation, switch, light, cover, media_player, group, fan, scene, script, climate
)

_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ['twilio==5.7.0']

DOMAIN = 'twilio'

API_PATH = '/api/{}'.format(DOMAIN)

CONF_ACCOUNT_SID = 'account_sid'
CONF_AUTH_TOKEN = 'auth_token'

DATA_TWILIO = DOMAIN
DEPENDENCIES = ['http']

RECEIVED_DATA = '{}_data_received'.format(DOMAIN)
DEFAULT_EXPOSED_DOMAINS = [
    'switch', 'light', 'group', 'input_boolean', 'media_player', 'fan'
]

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_ACCOUNT_SID): cv.string,
        vol.Required(CONF_AUTH_TOKEN): cv.string
    }),
}, extra=vol.ALLOW_EXTRA)

@asyncio.coroutine
def async_setup(hass, config):
    """Set up the Twilio component."""
    from twilio.rest import TwilioRestClient
    conf = config[DOMAIN]
    hass.data[DATA_TWILIO] = TwilioRestClient(
        conf.get(CONF_ACCOUNT_SID), conf.get(CONF_AUTH_TOKEN))
    hass.http.register_view(TwilioReceiveDataView(hass, conf))
    return True

class TwilioReceiveDataView(HomeAssistantView):
    """Handle data from Twilio inbound messages and calls."""
    url = API_PATH
    name = 'api:{}'.format(DOMAIN)
    requires_auth = False

    def __init__(self, hass: HomeAssistant, cfg: Dict[str, Any]) -> None:
        """Initialize Google Assistant view."""
        super().__init__()
        self.account_sid = cfg.get(CONF_ACCOUNT_SID)
        self.hass = hass

    @asyncio.coroutine
    def post(self, request):  # pylint: disable=no-self-use
        """Handle Twilio data post."""
        
        from twilio.twiml import Response
        hass = request.app['hass']
        data = yield from request.post()

        if data.get('AccountSid') != self.account_sid:
            return self.json_message(
                "missing authorization", status_code=HTTP_UNAUTHORIZED)
        
        body = data.get('Body')
        resp = yield from self.handleIncoming(hass, body)
        
        hass.bus.async_fire(RECEIVED_DATA, dict(data))
        return Response().toxml()

    @asyncio.coroutine
    def getEntity(self, entity):
        entities = self.hass.states.async_entity_ids()
        exposed = [x for x in entities if x.split('.')[0] in DEFAULT_EXPOSED_DOMAINS]
        for x in exposed:
            if x.split('.')[1] == entity:
                return x
        return None

    def findDomainService(self, domain, action) ->  Tuple[str, str]:
        if domain == switch.DOMAIN:
            if action == SERVICE_TURN_ON:
                return (switch.DOMAIN, SERVICE_TURN_ON)
            else:
                return (switch.DOMAIN, SERVICE_TURN_OFF)
        return (None, None)

    @asyncio.coroutine
    def handleIncoming(self, hass: HomeAssistant, body: str):
        (action, entity) = [x.strip().replace(' ', '_') for x in body.split(':')]

        matching_entity = yield from self.getEntity(entity)
        domain = matching_entity.split('.')[0]

        (domain, service) = self.findDomainService(domain, action)
        
        if matching_entity and domain and service:
            _LOGGER.warn("Found matching entitiy {}. Calling {}..{}".format(matching_entity, domain, service))
            service_data = {ATTR_ENTITY_ID: matching_entity}
        
            success = yield from self.hass.services.async_call(
                domain, service, service_data, blocking=True) 
            _LOGGER.warn(success)
        return