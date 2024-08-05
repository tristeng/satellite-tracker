#
# Copyright Tristen Georgiou 2024
#
import argparse
import datetime
import logging
import pathlib
from zoneinfo import ZoneInfo

from skyfield.api import load, wgs84

from tracker.model import load_config, load_tracking_config
from tracker.utils import (
    load_stations_data,
    generate_trajectory,
    init_telescope,
    track_satellite,
    load_active_data,
)

log = logging.getLogger(__name__)


# Press the green button in the gutter to run the script.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        help="The path to the configuration file.",
        type=pathlib.Path,
    )

    # add a required argument for the path to the tracking configuration file
    parser.add_argument(
        "satellite",
        help="The path to the satellite tracking configuration file.",
        type=pathlib.Path,
    )

    # add a required argument for the command, where the commands are execute, dryrun, or trajectory
    parser.add_argument(
        "command",
        help="The command to execute.",
        choices=["execute", "dryrun", "trajectory"],
    )

    # add optional flag to set the telescope location
    parser.add_argument(
        "--set-location",
        help="Set the telescope location using the configured latitude and longitude.",
        action="store_true",
        default=False,
    )

    # add optional flag to set the telescope time
    parser.add_argument(
        "--set-time",
        help="Set the telescope time using the PC time and the configured timezone.",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    # load the base configuration
    if args.config:
        config = load_config(args.config)
    else:
        config = load_config()

    # load the satellite tracking configuration
    ts = load.timescale()
    tracking_config = load_tracking_config(args.satellite)

    stations_data = load_stations_data(ts)
    active_data = load_active_data(ts)

    # merge the 2 dictionaries
    stations_data.update(active_data)
    try:
        satellite = stations_data[tracking_config.satellite]
    except KeyError:
        log.error(
            f"Could not find tracking information for '{tracking_config.satellite}'."
        )
        available = "\n".join(stations_data.keys())
        log.error(f"Available satellites: \n{available}")
        exit(1)

    log.info(
        f"Loaded tracking information for '{tracking_config.satellite}', starting at {tracking_config.start} for "
        f"{tracking_config.get_duration_seconds} seconds."
    )

    # define the observer location
    obs_location = wgs84.latlon(config.location.latitude, config.location.longitude)
    log.info(
        f"Observer location: {obs_location.latitude.degrees:.5f}°, {obs_location.longitude.degrees:.5f}°"
    )

    # get the current time in the timezone specified in the configuration
    tz = ZoneInfo(config.datetime.timezone)
    now = datetime.datetime.now(tz=tz)
    log.info(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # determine how long before tracking is set to begin
    delta = tracking_config.start - now

    # if its negative, exit if the command is execute
    if args.command == "execute" and delta.total_seconds() < 0:
        log.error("Tracking start time has already passed! Cannot execute.")
        exit(1)

    # figure out how many hours, minutes, and seconds until satellite pass begins
    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    log.info(
        f"Satellite pass will begin in {hours:.0f} hours, {minutes:.0f} minutes, and {seconds:.0f} seconds."
    )

    # generate and plot the trajectory
    is_trajectory = args.command == "trajectory"
    traj = generate_trajectory(
        satellite,
        obs_location,
        tracking_config,
        ts,
        tz,
        config.telescope.max_slew_rate,
        is_trajectory,  # plot the trajectory if we are in trajectory mode
    )

    if is_trajectory:
        log.info("Trajectory generated. Exiting.")
        exit(0)

    # initialize the telescope, setting the location and time if the flags are not set
    hc = init_telescope(config, set_location=args.set_location, set_time=args.set_time)

    # track the satellite - in dryryn mode it will sweep across the trajectory immediately
    is_dryrun = args.command == "dryrun"
    track_satellite(hc, traj, tracking_config, is_dryrun)
