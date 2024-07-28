#
# Copyright Tristen Georgiou 2024
#
import datetime
import json
import logging
import pathlib
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, model_validator, PositiveFloat, PositiveInt

log = logging.getLogger(__name__)


CONF_DIR = pathlib.Path("conf")
DEFAULT_CONFIG_FILE = CONF_DIR / "satellite-tracker.json"


class LocationConfig(BaseModel):
    latitude: float
    longitude: float

    @model_validator(mode="after")
    def check_latitude(self) -> Self:
        if not -90 <= self.latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        return self

    @model_validator(mode="after")
    def check_longitude(self) -> Self:
        if not -180 <= self.longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        return self


class DateTimeConfig(BaseModel):
    timezone: str  # suitable for ZoneInfo, e.g. "America/Vancouver"

    @model_validator(mode="after")
    def check_timezone(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Invalid timezone: {self.timezone}")
        return self


class TelescopeConfig(BaseModel):
    comport: str
    max_slew_rate: PositiveFloat  # arcseconds per second


class Config(BaseModel):
    location: LocationConfig
    datetime: DateTimeConfig
    telescope: TelescopeConfig


class TrajectoryConfig(BaseModel):
    step: PositiveInt  # seconds - the time between each point for trajectory generation
    pad: PositiveFloat  # number of seconds to pad the start and end of the trajectory
    offset_multiplier: PositiveFloat  # a multiplier applied to create a start and end alt/az points with velocity 0


class TrackingConfig(BaseModel):
    satellite: str
    start: datetime.datetime
    end: datetime.datetime
    trajectory: TrajectoryConfig

    @model_validator(mode="after")
    def check_start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self

    @property
    def get_duration_seconds(self) -> int:
        return round((self.end - self.start).total_seconds())


def load_config(path: pathlib.Path = DEFAULT_CONFIG_FILE) -> Config:
    """
    Load the configuration file.

    :param path: The path to the configuration file.
    :return: A Config object.
    """
    log.info(f"Loading configuration from {path}")
    with path.open() as f:
        return Config.model_validate(json.load(f))


def load_tracking_config(path: pathlib.Path) -> TrackingConfig:
    """
    Load the tracking configuration file.

    :param path: The path to the tracking configuration file.
    :return: A TrackingConfig object.
    """
    log.info(f"Loading tracking configuration from {path}")
    with path.open() as f:
        return TrackingConfig.model_validate(json.load(f))
