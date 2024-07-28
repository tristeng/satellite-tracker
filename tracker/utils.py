#
# Copyright Tristen Georgiou 2024
#
import datetime
import logging
import pathlib
from zoneinfo import ZoneInfo

import numpy as np
from nexstar_control.device import NexStarHandControl, LatitudeDMS, LongitudeDMS
from skyfield.api import load
from skyfield.iokit import parse_tle_file
from skyfield.sgp4lib import EarthSatellite
from skyfield.timelib import Timescale
from skyfield.toposlib import GeographicPosition

import matplotlib.pyplot as plt

from tracker.model import Config, TrackingConfig
from tracker.trajgen import MininumTrajectory, TrajectoryType

log = logging.getLogger(__name__)

DATA_DIR = pathlib.Path("data")
STATIONS_FILE = DATA_DIR / "stations.tle"
CELESTRAK_STATIONS_URL = (
    "https://celestrak.com/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"
)
MAX_DATA_AGE = 7.0  # days


def load_stations_data(timescale: Timescale) -> dict[str, EarthSatellite]:
    """
    Load stations data from Celestrak.

    :param timescale: A Timescale object.
    :return: A dictionary of EarthSatellite objects keyed by their name.
    """

    log.info("Loading stations data...")

    name = str(STATIONS_FILE)
    url = CELESTRAK_STATIONS_URL
    if not load.exists(name) or load.days_old(name) >= MAX_DATA_AGE:
        log.info("Downloading stations data...")
        load.download(url, filename=name)
        log.info("Stations data downloaded successfully.")
    else:
        log.info("Data cache is up to date - no downloads required.")

    with load.open(name) as f:
        stations = list(parse_tle_file(f, timescale))

    log.info(f"Stations data loaded successfully. Found {len(stations)} station(s).")
    return {sat.name: sat for sat in stations}


def init_telescope(
    conf: Config, set_location=True, set_time=True
) -> NexStarHandControl:
    """
    Initialize the telescope and optionally set the location and time.

    :param conf: The configuration object.
    :param set_location: Whether to set the location.
    :param set_time: Whether to set the time.
    :return: A NexStarHandControl object.
    :raises RuntimeError: If the telescope fails to connect.
    """
    log.info(f"Initializing telescope on COM port {conf.telescope.comport}...")
    hc = NexStarHandControl(conf.telescope.comport)
    if not hc.is_connected():
        raise RuntimeError(
            f"Failed to connect to telescope on com port {conf.telescope.comport}."
        )
    log.info("Telescope initialized successfully.")

    # set the location
    if set_location:
        lat, lng = (
            LatitudeDMS.from_decimal(conf.location.latitude),
            LongitudeDMS.from_decimal(conf.location.longitude),
        )
        log.info(f"Setting location to {lat} {lng}")
        hc.set_location(lat, lng)

    # set the time
    if set_time:
        dt = datetime.datetime.now(tz=ZoneInfo(conf.datetime.timezone))
        log.info(f"Setting time to {dt}")
        hc.set_time(dt)

    return hc


def generate_trajectory(
    satellite: EarthSatellite,
    obs_location: GeographicPosition,
    tracking_config: TrackingConfig,
    ts: Timescale,
    tz: ZoneInfo,
    max_slew_rate: float,
) -> MininumTrajectory:
    """
    Generate a minimum trajectory for the satellite.

    :param satellite: the earth satellite object
    :param obs_location: the observers location
    :param tracking_config: the tracking configuration
    :param ts: the timescale object
    :param tz: the timezone object of the observer
    :param max_slew_rate: the maximum slew rate of the telescope
    :return: the minimum trajectory object
    """
    # convert to utc and create a range of times
    start = tracking_config.start.astimezone(ZoneInfo("UTC"))
    step = tracking_config.trajectory.step
    tr = ts.utc(
        start.year,
        start.month,
        start.day,
        start.hour,
        start.minute,
        range(start.second, start.second + tracking_config.get_duration_seconds, step),
    )

    diff = satellite - obs_location
    alt, az, _ = diff.at(tr).altaz()
    lti, lalt, laz = None, None, None

    # to generate a smooth trajectory...
    points = []
    rates = []
    times = []

    traj_start = tr[0].utc_datetime()
    for ti, a, z in zip(tr, alt.degrees, az.degrees):
        # print the event time in local time
        event_time = ti.utc_datetime().astimezone(tz)

        # calculate the rate of change of alt/az in arcseconds per second
        # this is just to see if my telescope can keep up
        if lalt is not None:
            dalt = a - lalt

            # need to detect when the satellite crosses the 0/360° boundary for azimuth - but not for altitude since
            #  we won't be observing any objects below the horizon
            zfp = z  # zfp for printing to the log...but for trajectory generation we may need to adjust for crossing
            if abs(laz - z) > 180:
                if laz > z:
                    zfp = z - laz + 360
                    z += 360  # trajectory generation requires absolute changes
                else:
                    zfp = z - laz - 360
                    z -= 360  # trajectory generation requires absolute changes
            daz = z - laz
            dt = (event_time - lti).seconds
            alt_slew_rate = dalt / dt * 3600
            az_slew_rate = daz / dt * 3600

            # make sure the slew rate is within the limits of the telescope
            assert (
                abs(alt_slew_rate) <= max_slew_rate
            ), f"Calcualted impossible slew rate for altitude! {alt_slew_rate} > {max_slew_rate}"
            assert (
                abs(az_slew_rate) <= max_slew_rate
            ), f"Calcualted impossible slew rate for azimuth! {az_slew_rate} > {max_slew_rate}"

            if log.isEnabledFor(logging.DEBUG):
                log.debug(
                    f"{event_time.strftime('%Y-%m-%d %H:%M:%S %Z')} alt: {a:.5f}°, az: {zfp:.5f}°, "
                    f"alt rate: {dalt / dt * 3600:.5f}″/s, az rate: {daz / dt * 3600:.5f}″/s"
                )
            rates.append((alt_slew_rate, az_slew_rate))
        else:  # first point - no rate of change
            if log.isEnabledFor(logging.DEBUG):
                log.debug(
                    f"{event_time.strftime('%Y-%m-%d %H:%M:%S %Z')} alt: {a:.5f}°, az: {z:.5f}°"
                )

        points.append((a, z))

        # use a relative time offset so we can do dryruns from an arbitrary start time
        times.append(ti.utc_datetime().timestamp() - traj_start.timestamp())

        # cache the points and times for the next loop so we can calculate the rate of change
        lti, lalt, laz = event_time, a, z

    # we want the first and last points to have a non-zero velocity, so we can add one extra point and time at the
    # beginning and end that we can calculate (i.e. the telescope will be stationary at these padded points, but have
    # a velocity closer to the satellites velocity in the sky)
    start_alt_delta = points[1][0] - points[0][0]
    start_az_delta = points[1][1] - points[0][1]
    start_alt_delta *= tracking_config.trajectory.offset_multiplier
    start_az_delta *= tracking_config.trajectory.offset_multiplier

    points.insert(0, (points[0][0] - start_alt_delta, points[0][1] - start_az_delta))

    # insert a negative time that is larger than the step size so that the telescope can smoothly ramp up
    pad = tracking_config.trajectory.pad
    times.insert(0, times[0] - pad)

    # lets do the end point as well - the velocity at the end point should be non-zero
    end_alt_delta = points[-1][0] - points[-2][0]
    end_az_delta = points[-1][1] - points[-2][1]
    end_alt_delta *= tracking_config.trajectory.offset_multiplier
    end_az_delta *= tracking_config.trajectory.offset_multiplier

    points.append((points[-1][0] + end_alt_delta, points[-1][1] + end_az_delta))
    times.append(times[-1] + pad)

    # create a new minimum trajectory
    log.info("Generating minimum trajectory...")
    traj = MininumTrajectory(TrajectoryType.SNAP)
    traj.generate(points, times)
    log.info("Minimum trajectory generated successfully.")

    # use matplotlib to plot the input points and the generated trajectory
    plottimes = np.linspace(times[0], times[-1], len(times) * 10)

    fig, ax = plt.subplots()
    ax.plot([p[1] for p in points], [p[0] for p in points], "rx", label="input points")
    ax.plot(
        [traj.getvalues(t)[1][0] for t in plottimes],
        [traj.getvalues(t)[0][0] for t in plottimes],
        "b-",
        label="trajectory",
    )
    ax.set_xlabel("azimuth (°)")
    ax.set_ylabel("altitude (°)")
    ax.legend()
    plt.show()

    # plot the az/alt rates of change as well for the input points
    fig, ax = plt.subplots()
    ax.plot([p[1] for p in rates], [p[0] for p in rates], "rx", label="input rates")
    ax.plot(
        [traj.getvalues(t)[1][1] * 3600 for t in plottimes],
        [traj.getvalues(t)[0][1] * 3600 for t in plottimes],
        "b-",
        label="trajectory",
    )
    ax.set_xlabel("azimuth rate (\"/s)")
    ax.set_ylabel("altitude rate (\"/s)")
    ax.legend()
    plt.show()

    # double check our work if in debug mode
    if log.isEnabledFor(logging.DEBUG):
        for t in plottimes:
            vals = traj.getvalues(t)
            x = vals[0][0]
            y = vals[1][0]

            dx = vals[0][1] * 3600  # convert to arcseconds per second
            dy = vals[1][1] * 3600

            log.info(
                f"time: {t:.1f}, alt: {x:.5f}°, az: {y:.5f}°, alt rate: {dx:.5f}″/s, az rate: {dy:.5f}″/s"
            )

    return traj
