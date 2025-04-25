from __future__ import annotations
import logging
from .tcp_client import tcp_client
from datetime import timedelta
import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_time_interval

from typing import Any
from .const import (
   DOMAIN,
   SWITCH_TYPE_CODE,
)

SCAN_INTERVAL = timedelta(seconds=0.7)


_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
   hass: HomeAssistant,
   config: ConfigType,
   async_add_devices: AddEntitiesCallback,
   discovery_info: DiscoveryInfoType | None = None
) -> None:
   """Set up the sensor platform."""
   _LOGGER.info('setup_platform')

   switches = []
   for item in config.get('switches') or []:
       client = tcp_client(item.get('ip'))
       client._device_id = item.get('did')
       client._pid = item.get('pid')
       client._dpid = item.get('dpid')
       client._device_model_name = item.get('dmn')
       switches.append(CozyLifeSwitch(client, hass, 'wippe1'))

   for item in config.get('switches2') or []:
       client = tcp_client(item.get('ip'))
       client._device_id = item.get('did')
       client._pid = item.get('pid')
       client._dpid = item.get('dpid')
       client._device_model_name = item.get('dmn')
       switches.append(CozyLifeSwitch(client, hass, 'wippe1'))
       switches.append(CozyLifeSwitch(client, hass, 'wippe2'))

   async_add_devices(switches)

   for switch in switches:
       await hass.async_add_executor_job(switch._tcp_client._initSocket)
       await asyncio.sleep(0.01)

   async def async_update(now=None):
       for switch in switches:
           await switch.async_update()
           await asyncio.sleep(0.01)

   async_track_time_interval(hass, async_update, SCAN_INTERVAL)


class CozyLifeSwitch(SwitchEntity):
   def __init__(self, tcp_client: tcp_client, hass: HomeAssistant, wippe: str) -> None:
       """Initialize the sensor."""
       self.hass = hass
       self._tcp_client = tcp_client
       self._unique_id = f"{tcp_client.device_id}_{wippe}"
       self._name = f"cozylife:{tcp_client.device_id[-4:]}_{wippe}"
       self._wippe = wippe
       self._attr_is_on = False
       self._state = {}
       self._available = True
       self._reconnect_delay = 0.5  # Initial reconnect delay

       # Event listener setup
       self._event_listener_task: asyncio.Task | None = None
       self.async_on_remove(self.stop_event_listener)

   async def async_added_to_hass(self) -> None:
       """Run when entity about to be added to hass."""
       await super().async_added_to_hass()
       self.start_event_listener()

   def start_event_listener(self) -> None:
       """Start the event listener."""
       if self._event_listener_task is None:
           self._event_listener_task = self.hass.loop.create_task(self._listen_for_events())

   async def stop_event_listener(self) -> None:
       """Stop the event listener."""
       if self._event_listener_task:
           self._event_listener_task.cancel()
           try:
               await self._event_listener_task
           except asyncio.CancelledError:
               pass
           self._event_listener_task = None

   async def _listen_for_events(self) -> None:
       """Listen for events from the CozyLife device."""
       while True:
           try:
               event = await self.hass.async_add_executor_job(self._tcp_client.query)
               if event:
                   self._state = event
                   self._update_state()
                   self.async_write_ha_state()
               await asyncio.sleep(0.1)
           except Exception as e:
               _LOGGER.error(f"Error listening for events: {e}")
               self._available = False
               self.async_write_ha_state()
               await self._tcp_client._initSocket()  # Reinitialize socket

   def _update_state(self) -> None:
       """Update the switch state based on the received event."""
       if self._wippe == 'wippe1':
           self._attr_is_on = (self._state.get('1', 0) & 0x01) == 0x01
       elif self._wippe == 'wippe2':
           self._attr_is_on = (self._state.get('1', 0) & 0x02) == 0x02

   async def async_update(self) -> None:
       """Fetch new state data for the sensor."""
       await self.hass.async_add_executor_job(self._refresh_state)

   async def _refresh_state(self) -> None:
       """Refresh the switch state."""
       try:
           self._state = self._tcp_client.query()
           _LOGGER.info(f'_name={self._name}, _state={self._state}')
           if self._state:
               self._update_state()
               self._available = True
           else:
               self._available = False
               await self._tcp_client._initSocket()  # Reinitialize socket
       except Exception as e:
           _LOGGER.error(f"Error refreshing state: {e}")
           self._available = False
           await self._tcp_client._initSocket()  # Reinitialize socket


   @property
   def unique_id(self) -> str:
       """Return a unique ID."""
       return self._unique_id

   @property
   def name(self) -> str:
       """Return the name of the entity."""
       return self._name

   @property
   def available(self) -> bool:
       """Return if the device is available."""
       return self._available

   @property
   def is_on(self) -> bool:
       """Return True if entity is on."""
       return self._attr_is_on

   async def async_turn_on(self, **kwargs: Any) -> None:
       """Turn the entity on."""
       new_state = self._state.get('1', 0)
       if self._wippe == 'wippe1':
           new_state |= 0x01
       elif self._wippe == 'wippe2':
           new_state |= 0x02
       await self.hass.async_add_executor_job(self._tcp_client.control, {'1': new_state})
       await self.async_update()

   async def async_turn_off(self, **kwargs: Any) -> None:
       """Turn the entity off."""
       new_state = self._state.get('1', 0)
       if self._wippe == 'wippe1':
           new_state &= ~0x01
       elif self._wippe == 'wippe2':
           new_state &= ~0x02
       await self.hass.async_add_executor_job(self._tcp_client.control, {'1': new_state})
       await self.async_update()
