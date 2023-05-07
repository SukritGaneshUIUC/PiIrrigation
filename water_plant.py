import schedule
import smtplib
import time
import ssl
from gpiozero import OutputDevice
import json
import os, shutil
import datetime
import calendar
import requests

from threading import Thread
from threading import Lock

# Global variables
CONFIG_FILEPATH = "config.json"
SCHEDULE_FILEPATH = "schedule.json"
LOG_FILEPATH = "logs/log.txt"

log_lock = Lock()

OPENWEATHER_API_URL = 'https://api.openweathermap.org/data/2.5/onecall/timemachine?lat={lat}&lon={lon}&dt={day}&appid={key}'

HOURS_IN_DAY = 24

######################################################################
# Helper functions
######################################################################

# Parse config JSON
def parse_config_json(config_filepath):
    data = ""
    with open(config_filepath, "r") as f:
        data = json.load(f)
    email_address = data["email_address"]
    password = data["password"]
    latitude = data["latitude"]
    longitude = data["longitude"]
    open_weather_api_key = data["open_weather_api_key"]
    return email_address, password, latitude, longitude, open_weather_api_key

# Parse schedule JSON
def load_schedule_json(schedule_filepath):
    data = ""
    with open(schedule_filepath, "r") as f:
        data = json.load(f)
    return data

# Configure relay at specific pin
# Relay used to control gardening hardware
# steady_state - whether solenoid valve is closed (False) or open (True) by default
def configure_relay(pin, steady_state=False):
    relay = OutputDevice(pin, steady_state)
    return relay

# return the time and day of week
def get_current_time():
    t = datetime.datetime.now()
    hour = t.strftime("%H")
    minute = t.strftime("%M")
    day_of_week = t.strftime("%A")
    return day_of_week, hour, minute

# Get hourly rainfall statistics for 24 hours before the specified timestamp
# Must find rainfall for current day up until timestamp, and previous day after timestamp - 24 hours
def get_24_hour_rainfall(latitude, longitude, open_weather_api_key):

    # get current timestamp (end of window)
    timestamp_current = calendar.timegm(datetime.datetime.utcnow().utctimetuple())

    # get timestamp 24 hours ago (beginning of window)
    timestamp_24_hours_prior = calendar.timegm((datetime.datetime.utcnow() - datetime.timedelta(hours=HOURS_IN_DAY)).utctimetuple())

    # get hourly rainfall statistics for previous day
    api_request = OPENWEATHER_API_URL.format(key=open_weather_api_key,
                                       day=timestamp_24_hours_prior,
                                       lat=latitude,
                                       lon=longitude)
    print(api_request)
    yesterday_weather = requests.get(api_request)
    yesterday_weather_data = json.loads(yesterday_weather.content.decode('utf-8'))
    yesterday_hourly_rain = {d.get('dt'): d.get('rain').get('1h') for d in yesterday_weather_data.get('hourly') if d.get('rain') and d.get('dt') >= timestamp_24_hours_prior}

    # get hourly rainfall statistics for current day
    today_weather = requests.get(OPENWEATHER_API_URL.format(key=open_weather_api_key,
                                       day=timestamp_current,
                                       lat=latitude,
                                       lon=longitude))
    today_weather_data = json.loads(today_weather.content.decode('utf-8'))
    today_hourly_rain = {d.get('dt'): d.get('rain').get('1h') for d in today_weather_data.get('hourly') if d.get('rain') and d.get('dt') < timestamp_current}
    
    # get rainfall statistics for the past hour
    # add it to the today_hourly_rain dictionary
    curr_weather_data = today_weather_data.get('current')
    curr_rain = {}  
    if curr_weather_data:
      rain = curr.get('rain', 0)
      if rain:
        curr_rain = {timestamp_current: rain.get('1h', 0)}
    today_hourly_rain.update(curr_rain)

    # sum up rainfall over the last 24 hours
    last_24_hours_hourly_rain = yesterday_hourly_rain
    last_24_hours_hourly_rain.update(today_hourly_rain)
    last_24_hours_total_rainfall = sum(last_24_hours_hourly_rain.values())
    return last_24_hours_total_rainfall

# write to log
def log_watering(pin_number, start_time, duration, log_filepath, log_lock):
    log_lock.acquire()
    with open(log_filepath, "a") as f:
        log_str = "Valve " + str(pin_number) + " watered for " + str(duration) + " seconds on " + start_time + ".\n"
        f.writelines([log_str])
    log_lock.release()

# send email to the specified email address
def send_email(message, email_address, password):
    port = 465
    smtp_server = "smtp.gmail.com"
    FROM = TO = email_address
    
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        server.login(email_address, password)
        server.sendmail(email_address, email_address, message)

# Actually water the plant for the given duration and update the log
def water_plant(pin_number, relay, duration, log_filepath, log_lock, email_address, password):
    start_time_str = datetime.datetime.now().strftime("%A %D %H:%M:%S")
    relay.on()
    print("Valve", pin_number, "watering commenced! Duration:", duration, "seconds.")
    time.sleep(duration)
    print("Valve", pin_number, "watering finished! Duration:", duration, "seconds.")
    relay.off()

    # add watering to log
    log_watering(pin_number, start_time_str, duration, log_filepath, log_lock)

    # send email confirming watering was done successfully
    email_message = "Subject: PiIrrigation Watering Completed\n\nValve " + str(pin_number) + " watered for " + str(duration) + " seconds on " + start_time_str + ".\n"
    send_email(email_message, email_address, password)

    # sleep for one minute (just to ensure that the current minute passes)
    time.sleep(60)

######################################################################
# Thread driver
######################################################################

# pin number: the pin from which the respective pump or solenoid valve is controlled
# rain_sensing: TRUE if watering will NOT occur on rainy days, FALSE otherwise
# rain_threshold: if amount of rain in last 24 hours exceeds threshold, sprinkler won't turn on (must have rain sensing enabled)
# schedule: a list of watering times and durations
# lock: the mutex lock used to update the log
def station_driver(pin_number, rain_sensing, rain_threshold, schedule, log_filepath, log_lock, email_address, password, latitude, longitude, open_weather_api_key):
    print("Station", pin_number, "active!")
    curr_relay = configure_relay(pin_number, steady_state=False)

    while True:
        # get current day and time
        day_of_week, hour, minute = get_current_time()

        # check if current time matches any of the scheduled times (and begin watering if so)
        for slot in schedule:
            start_day = slot["day"]
            start_hour, start_minute = tuple(slot["start"].split(":"))
            duration_seconds = int(slot["duration"] * 60)
            if (start_day == day_of_week and start_hour == hour and start_minute == minute):

                # check if it already rained
                if (rain_sensing):
                    last_24_hours_total_rainfall = get_24_hour_rainfall(latitude, longitude, open_weather_api_key)
                    if (last_24_hours_total_rainfall > rain_threshold):
                        # don't water, send email informing 
                        email_message = "Subject: PiIrrigation Watering CANCELLED Due to Rainfall\n\nValve " + str(pin_number) + " watering at " + start_time_str + " CANCELLED due to 24 hour rainfall of " + str(last_24_hours_hourly_rain) + " mm exceeding threshold of " + rain_threshold + " mm.\n"
                        send_email(email_message, email_address, password)
                        time.sleep(60)  # sleep to ensure entire minute passes, and current watering time isn't activated again
                        continue

                # if the rain checks pass, then go ahead and water the plant
                water_plant(pin_number, curr_relay, duration_seconds, log_filepath, log_lock, email_address, password)

        # sleep for 45 seconds before checking time again
        # We only need to check every minute
        time.sleep(45)

######################################################################
# Main function: Start threads
######################################################################

def main():

    print("Starting irrigation system at time:", get_current_time())

    # Parse the config JSON file (contains parameters like email)
    email_address, password, latitude, longitude, open_weather_api_key = parse_config_json(CONFIG_FILEPATH)
    # print("Rainfall last 24 hours (mm): ", get_24_hour_rainfall(latitude, longitude, open_weather_api_key))

    # Parse the schedule JSON File (contains the watering schedule)
    schedule_data = load_schedule_json(SCHEDULE_FILEPATH)

    # Create log file if it doesn't yet exist
    if (not os.path.exists(os.path.dirname(LOG_FILEPATH))):
        os.path.makedirs(os.path.dirname(LOG_FILEPATH))
    with open(LOG_FILEPATH, "a") as f:
        f.write("")

    log_lock = Lock()

    # Create individual threads to run
    for pin_number_str in schedule_data["stations"]:
        pin_number = int(pin_number_str)
        rain_sensing = schedule_data["stations"][pin_number_str]["rain_sensing"]
        rain_threshold = schedule_data["stations"][pin_number_str]["rain_threshold"]
        schedule = schedule_data["stations"][pin_number_str]["schedule"]
        Thread(target=station_driver, args=(pin_number, rain_sensing, rain_threshold, schedule, LOG_FILEPATH, log_lock, email_address, password, latitude, longitude, open_weather_api_key)).start()

main()