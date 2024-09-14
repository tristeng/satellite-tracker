# Satellite Tracker
This is a work in progress project to track satellites in real time, with the goal of imaging the ISS with a Celestron
Nexstar 8SE telescope. The project is written in Python and uses the Skyfield library to calculate the position of 
Earth satellites. The project is currently in the early stages of development.

```bash
usage: main.py [-h] [-c CONFIG] [--set-location] [--set-time] satellite {execute,dryrun,trajectory}

positional arguments:
  satellite             The path to the satellite tracking configuration file.
  {execute,dryrun,trajectory}
                        The command to execute.

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        The path to the configuration file.
  --set-location        Set the telescope location using the configured latitude and longitude.
  --set-time            Set the telescope time using the PC time and the configured timezone.

```

After you install the required libraries, you can view trajectories of satellites by running the following command:
```bash
python main.py conf\iss.json trajectory
```

This sample plots out the calculated trajectories of the ISS for a particular date.

You can also perform a dryrun for a given configuration which will move the satellite to the first point of the 
trajectory and immediately start following the trajectory - it will plot out the error between the ideal and the
actual positions of the telescope over time. This is useful for debugging the telescope configuration.
```bash
python main.py conf\iss.json dryrun
```

Finally, you can execute the satellite tracking by running the following command:
```bash
python main.py conf\iss.json execute
```
This will move the telescope to the first point of the trajectory at which point it will wait for the trajectory start
time and then start following the trajectory.

## How to Create a Satellite Configuration File
The satellite configuration file is a JSON file that contains the following fields:
- `name`: The name of the satellite as defined in the Celestrak database.
- `start`: The start time of the trajectory with timezone information.
- `end`: The end time of the trajectory with timezone information.
- `trajectory.step`: The time step between trajectory points in seconds (I typically leave this at 1 second).
- `trajectory.pad`: The time in seconds to pad the trajectory start and end times (this allows the telescope to ramp up 
  its speed).
- `trajectory.offset_multiplier`: Used in conjunction with the `trajectory.pad` field to multiply the 'distance' between
  the first and last points of the trajectory, and use that value to inject a new first and last point.
- `tracking_period`: The time in seconds to update the telescope with the current slew rates.

To track a satellite:
1. Use an existing application to find the satellite you want to track, e.g.: [Heavens Above](https://heavens-above.com).
2. Find a pass for the satellite you wish to track and make note of its start and end times.
3. Determine the satellite's name as defined in the Celestrak database and use that name in your configuration file.
4. Create the JSON file with the above fields and save it in the `conf` directory.
5. Run the application with the path to the configuration file and use the `trajectory` command to plot the trajectory.
6. If the trajectory plots look correct, you are done! If not, you can play around with the `trajectory.pad` and 
  `trajectory.offset_multiplier` fields to help fit a better trajectory (I've found that longer period trajectories 
  need larger padding).

Use some of the existing configuration files as a template for your own.

## Known Issues
- Trajectories that pass through the zenith can result in unattainble slew speeds for the telescope. This is due to
  the fact that the telescope will attempt to move its vertical axis 180 degrees as it passes through the zenith in
  a short amount of time.