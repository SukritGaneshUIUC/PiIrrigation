# PiIrrigation

# Code - How to use

config.json contains the general config parameters for the irrigation system. You must enter your email, app password (to get email reminders), as well as the latitude, longitude, & openweather API key (for rain sensing)

schedule.json contains the watering schedules for every station. You can specify whether you want rain sensing (as well as the 24 hour rainfall threshold, which will stop irrigation if 24-hour rainfall exceeds that threshold), along with a list of start days and times. You can turn on multiple stations at once.

This assumes you have hooked up the respective pins to relays which control irrigation circuits. You can use pumps or solenoid valves. The voltage and nature of the circuit doesn't matter, as long as the relay is compatible with Raspberry Pi.

You will get an email when a station performs watering, or if a watering is cancelled due to excessive rainfall.

For my demo, I used pins 12, 16, 20, and 21