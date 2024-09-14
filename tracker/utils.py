#
# Copyright Tristen Georgiou 2024
#
import datetime
import enum
import logging
import pathlib
import time
import zoneinfo

import numpy as np
from nexstar_control.device import (
    NexStarHandControl,
    LatitudeDMS,
    LongitudeDMS,
    TrackingMode,
)
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
ACTIVE_FILE = DATA_DIR / "active.tle"
CELESTRAK_URL = "https://celestrak.com/NORAD/elements/gp.php?FORMAT=tle&GROUP="
MAX_DATA_AGE = 7.0  # days


class CelestrakGroup(str, enum.Enum):
    STATIONS = "stations"
    ACTIVE = "active"


def load_celestrak_data(
    timescale: Timescale, cache_path: pathlib.Path, group: CelestrakGroup
) -> dict[str, EarthSatellite]:
    """
    Load data from Celestrak.

    :param timescale: A Timescale object.
    :param cache_path: The path to the local cache file.
    :param group: The Celestrak group to load.
    :return: A dictionary of EarthSatellite objects keyed by their name.
    """

    log.info(f"Loading satellite data for group {group.name}...")

    cache_path = str(cache_path)
    url = CELESTRAK_URL + group.value
    if not load.exists(cache_path) or load.days_old(cache_path) >= MAX_DATA_AGE:
        log.info("Downloading satellite data...")
        load.download(url, filename=cache_path)
        log.info("satellite data downloaded successfully.")
    else:
        log.info("Data cache is up to date - no downloads required.")

    with load.open(cache_path) as f:
        stations = list(parse_tle_file(f, timescale))

    log.info(
        f"Satellite data group {group.name} loaded successfully. Found {len(stations)} satellite(s)."
    )
    return {sat.name: sat for sat in stations}


def load_stations_data(timescale: Timescale) -> dict[str, EarthSatellite]:
    """
    Load stations data from Celestrak.

    :param timescale: A Timescale object.
    :return: A dictionary of EarthSatellite objects keyed by their name.
    """
    return load_celestrak_data(timescale, STATIONS_FILE, CelestrakGroup.STATIONS)


def load_active_data(timescale: Timescale) -> dict[str, EarthSatellite]:
    """
    Load active data from Celestrak.

    :param timescale: A Timescale object.
    :return: A dictionary of EarthSatellite objects keyed by their name.
    """
    return load_celestrak_data(timescale, ACTIVE_FILE, CelestrakGroup.ACTIVE)


def init_telescope(
    conf: Config, set_location=False, set_time=False
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
        dt = datetime.datetime.now(tz=zoneinfo.ZoneInfo(conf.datetime.timezone))
        log.info(f"Setting time to {dt}")
        hc.set_time(dt)

    return hc


def generate_trajectory(
    satellite: EarthSatellite,
    obs_location: GeographicPosition,
    tracking_config: TrackingConfig,
    ts: Timescale,
    tz: zoneinfo.ZoneInfo,
    max_slew_rate: float,
    plot_trajectory: bool,
) -> MininumTrajectory:
    """
    Generate a minimum trajectory for the satellite.

    :param satellite: the earth satellite object
    :param obs_location: the observers location
    :param tracking_config: the tracking configuration
    :param ts: the timescale object
    :param tz: the timezone object of the observer
    :param max_slew_rate: the maximum slew rate of the telescope
    :param plot_trajectory: whether to plot the trajectory
    :return: the minimum trajectory object
    """
    # convert to utc and create a range of times
    start = tracking_config.start.astimezone(zoneinfo.ZoneInfo("UTC"))
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
                    z += 360  # trajectory generation requires a continuous trajectory
                else:
                    zfp = z - laz - 360
                    z -= 360  # trajectory generation requires a continuous trajectory
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

    if plot_trajectory:
        # use matplotlib to plot the input points and the generated trajectory
        plottimes = np.linspace(times[0], times[-1], len(times) * 10)

        fig, ax = plt.subplots()
        ax.plot(
            [p[1] for p in points], [p[0] for p in points], "rx", label="input points"
        )
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
        ax.set_xlabel('azimuth rate ("/s)')
        ax.set_ylabel('altitude rate ("/s)')
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


def track_satellite(
    hc: NexStarHandControl,
    traj: MininumTrajectory,
    tracking_config: TrackingConfig,
    is_dryrun: bool,
) -> None:
    """
    Track the satellite along the trajectory.

    :param hc: an initialized NexStarHandControl object
    :param traj: the minimum trajectory object
    :param tracking_config: the tracking configuration object
    :param is_dryrun: a dry run will move the telescope but won't wait for the start time - useful for debugging
    """

    # move to the start location
    vals = traj.getvalues(traj.times[0])
    az, alt = vals[1][0], vals[0][0]

    log.info(f"Moving to the start location azimuth, altitude {az}, {alt}...")
    hc.goto_azm_alt_precise(az, alt)
    while hc.is_goto_in_progress():
        time.sleep(0.5)

    log.info("Arrived at satellite trajectory start location.")

    pad = tracking_config.trajectory.pad

    # if this isn't a dryrun, we need to wait until the start time
    if not is_dryrun:
        start = tracking_config.start.astimezone(zoneinfo.ZoneInfo("UTC"))
        now = datetime.datetime.now(tz=zoneinfo.ZoneInfo("UTC"))

        delta = start - now
        log.info(f"Satellite tracking starts in {delta.total_seconds()} seconds...")

        # include the pad time in our wait - we start moving the telescope early so it can get up to speed
        delta -= datetime.timedelta(seconds=pad)
        log.info(
            f"Waiting {delta.total_seconds()} seconds before beginning satellite tracking "
            f"(includes pad time of {pad} seconds)"
        )
        time.sleep(delta.total_seconds())
    else:
        log.info("This is a dryrun - telescope will move along trajectory immediately")

    # stamp our start time
    start_time = time.time()

    # start tracking
    log.info("Starting satellite tracking...")

    # set the tracking mode to off but keep the current mode so we can restore it later
    current_tracking_mode = hc.get_tracking_mode()
    hc.set_tracking_mode(TrackingMode.OFF)

    # we'll track the positional error occasionally so we can plot it afterwords
    pos_error: list[tuple[float, tuple[float, float]]] = []
    period = tracking_config.tracking_period
    try:
        # main loop - we exit once the duration is reached - duration is the original trajectory
        # duration and 2x the configurable pad time
        duration = tracking_config.get_duration_seconds + 2 * pad

        # we pad the start time so the telescope can get up to speed
        padded_start_time = start_time + pad
        loop_counter = 0
        lazm, _ = hc.get_position_azm_alt()

        # we'll log a percent complete message every 5 seconds
        num_loops_for_progress = round(5 / period)

        # for error logging - let's limit that to every second since commanding rates
        # is more important and fetching current position adds a round trip to the telescope
        num_loops_for_log = round(1 / period)

        while time.time() - start_time < duration:
            op_start = time.time()

            # get the current relative time - this will be negative at first to account for padding
            rt = op_start - padded_start_time

            # get the azimuth and altitude velocities from the trajectory for the current time
            # and convert to arcseconds per second
            vals = traj.getvalues(rt)
            azm_rate = round(vals[1][1] * 3600)
            alt_rate = round(vals[0][1] * 3600)

            # update the slew rates
            hc.slew_variable(azm_rate, alt_rate)

            # we throttle the error logging because we will get more accuracy with more frequent
            # rate updates
            if loop_counter % num_loops_for_log == 0:
                # determine the error between the expected and actual positions
                azm, alt = hc.get_position_azm_alt()

                # handle case when azimuth crosses 0/360° boundary
                if abs(lazm - azm) > 180:
                    if lazm > azm:
                        azm += 360
                    else:
                        azm -= 360
                pos_error.append((rt, (vals[1][0] - azm, vals[0][0] - alt)))
                lazm = azm

            # log a progress message occasionally
            if loop_counter % num_loops_for_progress == 0:
                log.info(f"Progress: {((rt + pad) / duration) * 100:.1f}%")

            # detect if the operations took longer than the period
            op_end = time.time()
            op_duration = op_end - op_start
            if op_duration > period:
                log.warning(
                    "Operation took longer than the period - consider increasing the period"
                )

            # sleep until next loop
            if op_duration < period:
                time.sleep(period - op_duration)
            loop_counter += 1
    finally:
        # stop slewing and restore the tracking mode no matter what
        log.info("Completed satellite tracking")
        hc.slew_stop()
        hc.set_tracking_mode(current_tracking_mode)

    # plot the positional errors over time
    fig, ax = plt.subplots()
    ax.plot(
        [p[0] for p in pos_error],
        [p[1][0] for p in pos_error],
        "r-",
        label="azimuth error",
    )
    ax.plot(
        [p[0] for p in pos_error],
        [p[1][1] for p in pos_error],
        "b-",
        label="altitude error",
    )
    ax.set_xlabel("time (s)")
    ax.set_ylabel("error (°)")
    ax.legend()
    plt.show()
