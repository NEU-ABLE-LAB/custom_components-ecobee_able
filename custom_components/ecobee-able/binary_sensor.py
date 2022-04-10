"""Support for Ecobee binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    DEVICE_CLASS_OCCUPANCY,
    # DEVICE_CLASS_DRYCONTACT,
    DEVICE_CLASS_WINDOW,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    ECOBEE_MODEL_TO_NAME,
    MANUFACTURER,
)

import json

# from pyecobee import Ecobee
from datetime import datetime, timedelta
import pytz

# from homeassistant.helpers.entity import Entity


async def async_get_runtime_report(hass, thermostat_id):
    """Get dryContact sensors from Ecobee runtimeReport API"""
    data = hass.data[DOMAIN]
    log_msg_action = "get runtimeReport"
    today = datetime.utcnow().date()
    # Get 5 intervals 288-5=283 ahead of today to prevent index out of range
    yesterday = today - timedelta(days=1)

    param_string = {
        "startDate": yesterday.strftime("%Y-%m-%d"),
        "startInterval": 283,
        "endDate": today.strftime("%Y-%m-%d"),
        "includeSensors": "true",
        "columns": "zoneAveTemp,zoneClimate,zoneOccupancy",
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id,
        },
    }

    params = {"json": json.dumps(param_string)}

    response = await hass.async_add_executor_job(
        lambda: data.ecobee._request_with_refresh(
            "GET", "runtimeReport", log_msg_action, params=params
        )
    )

    return response


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up ecobee binary (occupancy) sensors."""
    data = hass.data[DOMAIN]
    dev = []
    for index in range(len(data.ecobee.thermostats)):
        for sensor in data.ecobee.get_remote_sensors(index):
            for item in sensor["capability"]:
                if item["type"] != "occupancy" and item["type"] != "dryContact":
                    continue

                dev.append(
                    EcobeeBinarySensor(data, sensor["name"], index, item["type"])
                )

    for index in range(len(data.ecobee.thermostats)):
        thermostat_id = data.ecobee.thermostats[index]["identifier"]
        response = await async_get_runtime_report(hass, thermostat_id)

        for sensor in response["sensorList"][0]["sensors"]:
            if sensor["sensorType"] == "dryContact":
                dev.append(
                    EcobeeBinarySensorDryContact(
                        hass,
                        response,
                        sensor["sensorName"],
                        thermostat_id,
                        "dryContact",
                    )
                )

    async_add_entities(dev, True)


class EcobeeBinarySensor(BinarySensorEntity):
    """Representation of an Ecobee sensor."""

    def __init__(self, data, sensor_name, sensor_index, sensor_type):
        """Initialize the Ecobee sensor."""
        self.data = data
        if sensor_type == "occupancy":
            self._name = f"{sensor_name} Occupancy"
        else:
            self._name = f"{sensor_name} DryContact"
        self.sensor_name = sensor_name
        self.index = sensor_index
        self._state = None

    @property
    def name(self):
        """Return the name of the Ecobee sensor."""
        return self._name.rstrip()

    @property
    def unique_id(self):
        """Return a unique identifier for this sensor."""
        for sensor in self.data.ecobee.get_remote_sensors(self.index):
            if sensor["name"] == self.sensor_name:
                if "code" in sensor:
                    return f"{sensor['code']}-{self.device_class}"
                thermostat = self.data.ecobee.get_thermostat(self.index)
                return f"{thermostat['identifier']}-{sensor['id']}-{self.device_class}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for this sensor."""
        identifier = None
        model = None
        for sensor in self.data.ecobee.get_remote_sensors(self.index):
            if sensor["name"] != self.sensor_name:
                continue
            if "code" in sensor:
                identifier = sensor["code"]
                model = "ecobee Room Sensor"
            else:
                thermostat = self.data.ecobee.get_thermostat(self.index)
                identifier = thermostat["identifier"]
                try:
                    model = (
                        f"{ECOBEE_MODEL_TO_NAME[thermostat['modelNumber']]} Thermostat"
                    )
                except KeyError:
                    # Ecobee model is not in our list
                    model = None
            break

        if identifier is not None:
            return DeviceInfo(
                identifiers={(DOMAIN, identifier)},
                manufacturer=MANUFACTURER,
                model=model,
                name=self.sensor_name,
            )
        return None

    @property
    def available(self):
        """Return true if device is available."""
        thermostat = self.data.ecobee.get_thermostat(self.index)
        return thermostat["runtime"]["connected"]

    @property
    def is_on(self):
        """Return the status of the sensor."""
        return self._state == "true"

    @property
    def device_class(self):
        """Return the class of this sensor, from DEVICE_CLASSES."""
        if "Occupancy" in self._name or "occupancy" in self._name:
            return DEVICE_CLASS_OCCUPANCY
        # return DEVICE_CLASS_DRYCONTACT
        return DEVICE_CLASS_WINDOW

    async def async_update(self):
        """Get the latest state of the sensor."""
        await self.data.update()
        for sensor in self.data.ecobee.get_remote_sensors(self.index):
            if sensor["name"] != self.sensor_name:
                continue
            for item in sensor["capability"]:
                if item["type"] != "occupancy" and item["type"] != "dryContact":
                    continue
                self._state = item["value"]
                break


class EcobeeBinarySensorDryContact(BinarySensorEntity):
    """Representation of an Ecobee drycontact sensor."""

    last_update_time = None
    local_timezone = pytz.timezone("America/New_York")
    delay_run_time = 25
    offset_from_utc = 0

    def __init__(self, data, response, sensor_name, thermostat_id, sensor_type):
        """Initialize the Ecobee drycontact sensor."""
        self.data = data
        self.response = response
        if sensor_type == "dryContact":
            self._name = f"{sensor_name} DryContact"
        self.sensor_name = sensor_name
        # self.index = sensor_index
        self.thermostat_id = thermostat_id
        self._state = None
        self.offset_from_utc = (
            datetime.strptime("23:35:00", "%H:%M:%S")
            - datetime.strptime(
                response["sensorList"][0]["data"][0].split(",")[1], "%H:%M:%S"
            )
        ).total_seconds() / 60

    @property
    def name(self):
        """Return the name of the Ecobee drycontact sensor."""
        return self._name.rstrip()

    @property
    def unique_id(self):
        """Return a unique identifier for this drycontact sensor."""
        for sensor in self.response["sensorList"][0]["sensors"]:
            if sensor["sensorName"] == self.sensor_name:
                return f"{self.thermostat_id}-{sensor['sensorId']}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for this drycontact sensor."""
        identifier = None
        model = None
        for sensor in self.response["sensorList"][0]["sensors"]:
            if sensor["sensorName"] != self.sensor_name:
                continue
            identifier = sensor["sensorId"]
            model = "ecobee dryContact Sensor"
            break

        if identifier is not None:
            return DeviceInfo(
                identifiers={(DOMAIN, identifier)},
                manufacturer=MANUFACTURER,
                model=model,
                name=self.sensor_name,
            )
        return None

    @property
    def available(self):
        """Return true if device is available."""
        # thermostat = self.data.ecobee.get_thermostat(self.index)
        # return thermostat["runtime"]["connected"]
        return True

    @property
    def is_on(self):
        """Return the status of the drycontact sensor."""
        return self._state == "0"

    @property
    def is_close(self):
        """Return the status of the drycontact sensor."""
        return self._state == "1"

    @property
    def device_class(self):
        """Return the class of this sensor, from DEVICE_CLASSES."""
        # return DEVICE_CLASS_DRYCONTACT
        return DEVICE_CLASS_WINDOW

    async def async_update(self):
        """Get the latest state of the drycontact sensor."""
        # ecobee runtimeReport API records binary sensor every 5 minutes or 15 minutes with 5 minutes delay
        # check if current_time - last_update_time > delay_run_time
        if self.last_update_time is not None:
            time_diff = (datetime.now(pytz.timezone("UTC"))) - datetime.strptime(
                self.last_update_time, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=pytz.timezone("UTC"))

            # skip update if less than delay_run_time
            if (
                time_diff.total_seconds() / 60
                < self.delay_run_time + self.offset_from_utc
            ):
                return

            # if current_time - last_update_time > delay_run_time+10, reset last_update_time
            if (
                time_diff.total_seconds() / 60
                > self.delay_run_time + self.offset_from_utc + 10
            ):
                self.last_update_time = None

        response = await async_get_runtime_report(self.data, self.thermostat_id)

        sensor_id = None
        for sensor in response["sensorList"][0]["sensors"]:
            if sensor["sensorName"] == self.sensor_name:
                sensor_id = sensor["sensorId"]
                for index in range(len(response["sensorList"][0]["columns"])):
                    if response["sensorList"][0]["columns"][index] == sensor_id:
                        sensor_index = 1
                        # try:
                        while (
                            response["sensorList"][0]["data"][-sensor_index].split(",")[
                                index
                            ]
                            == ""
                        ):
                            sensor_index += 1

                        sensor_data = response["sensorList"][0]["data"][
                            -sensor_index
                        ].split(",")

                        top_sensor_index = sensor_index

                        if self.last_update_time is None:
                            self._state = sensor_data[index]

                            self._attr_extra_state_attributes = {
                                "date": sensor_data[0],
                                "time": sensor_data[1],
                                "utc_offset_hour": str(self.offset_from_utc / 60),
                                "custom_components": "ecobee",
                            }

                            self.last_update_time = (
                                sensor_data[0] + " " + sensor_data[1]
                            )
                        else:
                            while datetime.strptime(
                                (sensor_data[0] + " " + sensor_data[1]),
                                "%Y-%m-%d %H:%M:%S",
                            ) != datetime.strptime(
                                self.last_update_time, "%Y-%m-%d %H:%M:%S"
                            ):
                                sensor_index += 1
                                sensor_data = response["sensorList"][0]["data"][
                                    -sensor_index
                                ].split(",")

                            while top_sensor_index <= sensor_index:
                                sensor_data = response["sensorList"][0]["data"][
                                    -sensor_index
                                ].split(",")

                                if self._state != sensor_data[index]:
                                    self._state = sensor_data[index]

                                    self._attr_extra_state_attributes = {
                                        "date": sensor_data[0],
                                        "time": sensor_data[1],
                                        "utc_offset_hour": str(
                                            self.offset_from_utc / 60
                                        ),
                                        "custom_components": "ecobee",
                                    }

                                if datetime.strptime(
                                    (sensor_data[0] + " " + sensor_data[1]),
                                    "%Y-%m-%d %H:%M:%S",
                                ) > datetime.strptime(
                                    self.last_update_time, "%Y-%m-%d %H:%M:%S"
                                ):
                                    self.last_update_time = (
                                        sensor_data[0] + " " + sensor_data[1]
                                    )

                                sensor_index -= 1

                        # except:
                        #     print("+++++ IndexError: list index out of range")

                        break
