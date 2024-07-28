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
from tracker.utils import load_stations_data, generate_trajectory

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
    try:
        satellite = stations_data[tracking_config.satellite]
    except KeyError:
        log.error(f"Could not find tracking information for '{tracking_config.satellite}'.")
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

    traj = generate_trajectory(
        satellite, obs_location, tracking_config, ts, tz, config.telescope.max_slew_rate
    )
