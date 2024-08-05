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