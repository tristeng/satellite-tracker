# Satellite Tracker
This is a work in progress project to track satellites in real time, with the goal of imaging the ISS with a Celestron
Nexstar 8SE telescope. The project is written in Python and uses the Skyfield library to calculate the position of 
Earth satellites. The project is currently in the early stages of development.

In its current state, it calculates minimum trajectories based on the projected positions of the ISS and plots them.

After you install the required libraries, you can run the project by executing the following command in the terminal:
```bash
python main.py conf\iss.json trajectory
```

This sample plots out the calculated trajectories of the ISS for a particular date.