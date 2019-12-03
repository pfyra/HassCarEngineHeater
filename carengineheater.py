from __future__ import print_function
import threading
import atexit
from flask import Flask
from flask import render_template
from flask import send_from_directory
from flask import jsonify
from flask import request
import datetime
import pickle as pickle
import time
import jobscheduler
#import log
import sys
import random
import signal
from logger import log, loglevel
#import homeassistant.remote as remote
from homeassistant.const import STATE_ON, STATE_OFF
import jsonpickle
import copy
import json

#internal
import termcolor2 as color
from job import Job
from hassapi import HassAPI



# lock to control access to departureTimes,
dataLock = threading.Lock()
jobThread = None
keep_running = True
jobscheduler = jobscheduler.JobScheduler()
switches = [] # list of Switch
cars = [] # list of Car
config = {}
departureTimes = [] # list of DepartureTime
recurringDepartureTimes = [] # list of RecurringDepartureTime

def read_config(config_filename):
    config = None
    with open(config_filename, "r") as f:
        data = f.read()
        if data != "":
            config = jsonpickle.decode(data)
            assert len(config['weekdays']) == 7
            assert len(config['cars']) > 0

            # Set some default values
            if config['temp2startheater'] is None:
                config['temp2startheater'] = 10.0
            if config['minutes_per_degree'] is None:
                config['minutes_per_degree'] = 5
            if config['max_heat_time'] is None:
                config['max_heat_time'] = 90

    return config


def weekday2index(weekday):
    # dont use dayIndexDict directly in app since it relies on config which is bound late
    dayIndexDict = {
    config['weekdays'][0]: 0,
    config['weekdays'][1]: 1,
    config['weekdays'][2]: 2,
    config['weekdays'][3]: 3,
    config['weekdays'][4]: 4,
    config['weekdays'][5]: 5,
    config['weekdays'][6]: 6}
    return dayIndexDict[weekday]


class Car(object):
    def __init__(self, name, entity_id):
        self.name = name
        self.entity_id = entity_id  # in home assistant
        self.state = False    # True = on, False = off


def getSwitchByCarName(carName):
    for car in cars:
        if car.name == carName:
            return getSwitchForCar(car)

    log.warn("Switch for car name " + carName + " not found!")
    return None


def getSwitchForCar(car):
    for switch in switches:
        if car.entity_id == switch.entity_id:
            return switch

    log.warn("Switch for car " + car.name + " not found!")
    return None


class DepartureTime(object):
    def __init__(self, when, carName, recurringId=-1):
        # date time in local time zone
        self.when = when
        self.carName = carName
        self.id = random.randrange(1000000, 999999999)
        self.recurringId = recurringId

        # enabled:
        #    True == this departure is planned to happen
        #    False == This departure is "removed". It is marked disabled instead of removed
        #               to avoid having the AddRecurringDepartureJob readd the job
        self.enabled = True


class RecurringDepartureTime(object):
    def __init__(self, dow, time_, carName):
        self.day_of_week = weekday2index(dow)
        self.time = time_
        self.carName = carName
        self.id = random.randrange(1000000, 999999999)
        print("Recurring departure time set up for " + self.carName + \
              " @ " + dow + \
              " (" + str(self.day_of_week) + \
              ") @ " + str(time_) + \
              " " + str(self))


class CheckCarEngineHeaterJob(Job):
    """
    Check when car engine heater should be activated and schedule a nexa job for that
    """
    def __init__(self, execTime, carName, departureTime, departureId):
        super(CheckCarEngineHeaterJob, self).__init__(execTime)
        log.info(color.turquoise("Creating") + " CheckCarEngineHeaterJob for '" + carName + "' @ " + str(execTime))
        self.carName = carName
        self.departureTime = departureTime

        # ID of a departure. Used to map a "DepartureTime" to its jobs
        self.departureId = departureId

    def execute(self):
        global jobscheduler

        if datetime.datetime.now() > self.departureTime + datetime.timedelta(hours=3):
            log.debug("Ignoring passed heat job")
            return


        temp = get_current_temperature()
        diff = float(config['temp2startheater']) - temp
        minutes2heat = diff * float(config['minutes_per_degree'])  # 5 minutes per degree lower than 10C
        if minutes2heat > config['max_heat_time']:
            # Cap at 90 minutes
            minutes2heat = config['max_heat_time']
        if minutes2heat < 0:
            # no heating needed.
            return

        heatTime = self.departureTime - datetime.timedelta(minutes=minutes2heat)

        log.info("CheckCarEngineHeaterJob: car: " + self.carName + \
                 " temp " + str(temp) + \
                 " deptime " + str(self.departureTime) + \
                 " heatTime " + str(heatTime))

        armjob = ActivateCarEngineHeaterJob(heatTime,
                                            self.carName,
                                            self.departureId)
        jobscheduler.addJob(armjob)

        disarmjob = DeactivateCarEngineHeaterJob(self.departureTime,
                                                 self.carName,
                                                 self.departureId)
        jobscheduler.addJob(disarmjob)

    def __str__(self):
        return self.jobname + ", id: " + str(self.jobid) + \
                              ", time: " + str(self.execTime) + \
                              ", departureId: " + str(self.departureId) + \
                              ", carName: " + self.carName


class ActivateCarEngineHeaterJob(Job):
    """
    Turn on the car engine heater
    """

    def __init__(self, execTime, carName, departureId=None):
        super(ActivateCarEngineHeaterJob, self).__init__(execTime)
        log.info(color.grey("Creating") + " ActivateCarEngineHeaterJob for '" + carName + "' @ " + str(execTime) + ", departureId: " + str(departureId))
        self.carName = carName
        # ID of a departure. Used to map a "DepartureTime" to its jobs
        self.departureId = departureId

    def execute(self):
        print ("Starting heater for " + self.carName + " NOW (departure " + str(self.departureId) + ")")
        switch = getSwitchByCarName(self.carName)
        switch.on()

    def __str__(self):
        return self.jobname + ", id: " + str(self.jobid) + \
                              ", time: " + str(self.execTime) + \
                              ", departureId: " + str(self.departureId) + \
                              ", carName: " + self.carName


class DeactivateCarEngineHeaterJob(Job):
    """
    Disarm the car engine heater timer when the car is heated
    """

    def __init__(self, execTime, carName, departureId=None):
        super(DeactivateCarEngineHeaterJob, self).__init__(execTime)
        log.info(color.grey("Creating") + " DeactivateCarEngineHeaterJob for '" + carName + "' @ " + str(execTime))
        self.carName = carName
        # ID of a departure. Used to map a "DepartureTime" to its jobs
        self.departureId = departureId

    def execute(self):
        print ("Departure for " + self.carName + " NOW (departure " + str(self.departureId) + ")")
        #log.info(color.turquoise("Running") + " DisarmCarEngineJob for car: " + self.carName)
        switch = getSwitchByCarName(self.carName)
        switch.off()

    def __str__(self):
        return self.jobname + ", id: " + str(self.jobid) + \
                              ", time: " + str(self.execTime) + \
                              ", departureId: " + str(self.departureId) + \
                              ", carName: " + self.carName


class RemoveDepartureJob(Job):

    """
    Removes DepartureTime that have passed in time
    """

    def __init__(self, execTime):
        super(RemoveDepartureJob, self).__init__(execTime)

    def execute(self):
        global departureTimes
        global dataLock
        with dataLock:
            deptimecopy = list(departureTimes)
            for deptime in deptimecopy:
                if deptime.when < datetime.datetime.today():
                    print ("remove departure! " + str(deptime.id) + " when: " + str(deptime.when))
                    departureTimes.remove(deptime)

    def reschedule(self):
        return datetime.datetime.today() + datetime.timedelta(minutes=1)


class AddRecurringDepartureJob(Job):

    """
    Creates and updates DepartureTime based on RecurringDepartureTime
    """

    def __init__(self, execTime):
      super(AddRecurringDepartureJob, self).__init__(execTime)

    def execute(self):
        global departureTimes
        global dataLock
        with dataLock:
            for recdeptime in recurringDepartureTimes:
                # dont add departuretimes for the same week day as today. removal and adding will be racing...
                # Checking the time could of course solve that, but meh..
                #print (str(recdeptime.day_of_week) + " != " + str(datetime.datetime.now().weekday()))
                if (recdeptime.day_of_week) != datetime.datetime.now().weekday():
                    #print( str(recdeptime) + " is up for renewal today!")
                    already_added = False
                    for deptime in departureTimes:
                        if deptime.recurringId == recdeptime.id:
                            already_added = True

                    if already_added == False:
                        # days until departure
                        dud = recdeptime.day_of_week - datetime.datetime.now().weekday()
                        if dud <= 0:
                            dud += 7

                        deptime = datetime.datetime.today() + datetime.timedelta(days=dud)
                        deptime = deptime.replace(
                            hour = recdeptime.time.hour,
                            minute = recdeptime.time.minute)

                        log.debug("Adding recurring departure: " + recdeptime.carName + " when: " + str(deptime) + ", recId: " + str(recdeptime.id))
                        departureTimes += [DepartureTime(when=deptime, carName=recdeptime.carName, recurringId=recdeptime.id)]
                        writeDepartureTimesToFile(departureTimes)

    def reschedule(self):
        # Needs to run "often" to readd moved jobs
        return datetime.datetime.today() + datetime.timedelta(minutes=1)


class UpdateJobsJob(Job):

    """
    Adds/Updates jobs based on the list of DepartureTime
    """

    # XXX: Perhaps moving/rescheduling a job should be forbidden altogether? at least for now?

    def __init__(self, execTime):
        super(UpdateJobsJob, self).__init__(execTime)

    def execute(self):
        with dataLock:
            for deptime in departureTimes:
                checkCarEngineHeaterJobFound = False
                activationjob_found = False
                deactivationjob_found = False

                # Look up and update CheckCarEngineHeaterJob for this departure
                for job in jobscheduler.joblist:
                    if isinstance(job, (CheckCarEngineHeaterJob)):
                        if job.departureId == deptime.id:
                            checkCarEngineHeaterJobFound = True
                            # relevant job found.
                            if timediff(job.execTime, deptime.when) > datetime.timedelta(minutes=1):
                                # Departure time has been changed!
                                CheckCarEngineHeaterJob.execTime = deptime.when
                    if isinstance(job, (ActivateCarEngineHeaterJob)):
                        if job.departureId == deptime.id:
                            activationjob_found = True
                    if isinstance(job, (DeactivateCarEngineHeaterJob)):
                        if job.departureId == deptime.id:
                            deactivationjob_found = True

                if checkCarEngineHeaterJobFound:
                    # CheckCarEngineHeaterJob has been found, meaning that
                    #   this departure is not close to its departure time.
                    # CheckCarEngineHeaterJob has already been rescheduled
                    #   so we are done.
                    pass
                else:
                    # CheckCarEngineHeaterJob has not been found which means that an
                    #   activate and deactivation job has been scheduled. The activation
                    #   job may have passed in time already.
                    for job in jobscheduler.joblist:
                        if isinstance(job, (DeactivateCarEngineHeaterJob)):
                            if job.departureId == deptime.id:
                                if timediff(job.execTime, deptime.when) > datetime.timedelta(minutes=1):
                                    # CheckCarEngineHeaterJob has already executed AND departure time has been
                                    #  changed. Remove existing jobs and add CheckCarEngineHeaterJob
                                    (_checkcarengineheaterjob_found, activationjob_found, deactivationjob_found) =\
                                         removeJobsForDepartureTime(deptime)
                                    if not activationjob_found:
                                        # Departure is close ! wtf do we do!?
                                        # XXX: turning off heater risk race condition with enabling the heater from new jobs!
                                        turn_off_heater(deptime.carName)


                if not checkCarEngineHeaterJobFound \
                    and not deactivationjob_found:
                    # Departure have not had any jobs scheduled yet.
                    #
                    # deptime is not removed until kinda late. It may be removed from list _after_ the actual departure has happened (but should be within the same minute). Not so nice..
                    if deptime.enabled and \
                        timediff(deptime.when, datetime.datetime.now()) < datetime.timedelta(minutes=3):

                        checkjob = CheckCarEngineHeaterJob(deptime.when - datetime.timedelta(hours=3),
                                                           deptime.carName,
                                                           deptime.when,
                                                           deptime.id)
                        jobscheduler.addJob(checkjob)


    def reschedule(self):
        return datetime.datetime.today() + datetime.timedelta(minutes=1)


class Switch(object):
    def __init__(self, friendly_name, entity_id, state):
        self.friendly_name = friendly_name
        self.entity_id = entity_id
        self.state = state

    def __str__(self):
        return "name: " + self.friendly_name + \
               ", enitity_id: " + self.entity_id + \
               ", state:" + self.state

    def on(self):
        return self.setState(STATE_ON)

    def off(self):
        return self.setState(STATE_OFF)

    def setState(self, state):
        self.state = state
        domain = 'switch'
        if state == STATE_ON:
            assert hassapi.turn_on(self.entity_id)
        elif state == STATE_OFF:
            assert hassapi.turn_off(self.entity_id)
        else:
            assert False


class HomeAssistantSyncJob(Job):

    """
    Retrieves info from home assistant
    """

    def __init__(self, execTime):
      super(HomeAssistantSyncJob, self).__init__(execTime)

    def execute(self):
        global switches
        with dataLock:
            switches = []
            entities = hassapi.get_states()
            for entity in entities:
                if entity['entity_id'].startswith('switch'):
                    #data = remote.get_state(hassapi, entity.entity_id)
                    state = entity['state']
                    try:
                        friendly_name = entity['attributes']['friendly_name']
                    except:
                        friendly_name = "-"
                    switches += [Switch(friendly_name,
                                        entity['entity_id'],
                                        entity['state'])]
                    log.debug("Added H-A switch: " + friendly_name + \
                              ", " + entity['entity_id'] + \
                              ", " + state)

            # do a config check:
            for car in cars:
                if getSwitchForCar(car) is None:
                    log.fatal("Switch for car " + car.name + " not found!")
                else:
                    log.debug("Switch for car " + car.name + " found!")

    def reschedule(self):
        return datetime.datetime.today() + datetime.timedelta(hours=3)

class HomeAssistantStateSyncJob(Job):

    """
    Retrieves state for car switches from home assistant
    """

    def __init__(self, execTime):
      super(HomeAssistantStateSyncJob, self).__init__(execTime)

    def execute(self):
        entities = hassapi.get_states()

        for car in cars:
            if getSwitchForCar(car) is None:
                log.fatal("Switch for car " + car.name + " not found!")
            else:
                #log.debug("Switch for car " + car.name + " found!")
                for entity in entities:
                    if car.entity_id == entity['entity_id']:
                        car.state = entity['state']

    def reschedule(self):
        return datetime.datetime.today() + datetime.timedelta(minutes=1)



class InfoJob(Job):

    """
    Prints info

    Superseeded by <ip>:port/_debug
    """

    def __init__(self, execTime):
        super(InfoJob, self).__init__(execTime)

    def execute(self):
        log.debug("Configured recurring departures:")
        for recdep in recurringDepartureTimes:
            log.debug("   Car: " + recdep.carName + \
                      ", DoW: " + str(recdep.day_of_week) + \
                      ", when: " + str(recdep.time) + \
                      ", id: " + str(recdep.id))

        log.debug("Planned departures:")
        for dep in departureTimes:
            log.debug("   Car: " + dep.carName + \
                      ", when: " + str(dep.when) + \
                      ", id: " + str(dep.id) + \
                      ", recurringId: " + str(dep.recurringId) + \
                      ", enabled: " + str(dep.enabled))

        log.debug("Jobs:")
        for job in jobscheduler.joblist:
            log.debug("   " + str(job))

    def reschedule(self):
        return datetime.datetime.today() + datetime.timedelta(hours=6)


def writeDepartureTimesToFile(departureTimes_):
    with open("departuretimes.json", "w") as f:
        f.write(jsonpickle.encode(departureTimes_))


def writeRecurringDepartureTimesToFile(recurringDepartureTimes_):
    with open("recurringdeparturetimes.json", "w") as f:
        f.write(jsonpickle.encode(recurringDepartureTimes_))


def timediff(t1, t2):
    if t1 > t2:
        return t2 - t1
    else:
        return t1 - t2


def signal_handler(signal, frame):
    global keep_running
    keep_running = False
    for car in cars:
        switch = getSwitchByCarName(car.name)
        switch.off()
    print('You pressed Ctrl+C!')
    jobThread.join()
    sys.exit(0)


def turn_off_heater(carName):
    log.info("Heater for " + carName + " turned off!")
    jobscheduler.addJob(DeactivateCarEngineHeaterJob(datetime.datetime.now(), carName=carName))


def turn_on_heater(carName):
    log.info("Heater for " + carName + " turned on!")
    jobscheduler.addJob(ActivateCarEngineHeaterJob(datetime.now(), carName=carName))


def get_current_temperature():
    entities = hassapi.get_states()
    for entity in entities:
        if entity['entity_id'] == config["outdoor_temp_sensor_name"]:
            #data = remote.get_state(hassapi, entity.entity_id)
            return float(entity['attributes']['temperature'])
    assert False, "Outdoor temp sensor not found. Check your config!"


def removeRecurringDepartureTime(recurringDepartureTimes, id):
    recdeptime2remove = None
    for recdeptime in copy.copy(recurringDepartureTimes):
        if recdeptime.id == id:
            removeDepartureTimesForRecurringDepartureTime(recdeptime)
            recdeptime2remove = recdeptime
            break
    assert recdeptime2remove is not None
    recurringDepartureTimes.remove(recdeptime2remove)


# dataLock must be held by caller!
def removeDepartureTimesForRecurringDepartureTime(recdep):
    global departureTimes
    deptimescopy = copy.deepcopy(departureTimes)
    for i, deptime in enumerate(deptimescopy):
        if deptime.recurringId == recdep.id:
            removeDepartureTime(departureTimes[i])


# dataLock must be held by caller!
def removeDepartureTime(deptime):
    global departureTimes
    (checkcarengineheaterjob_found, activationjob_found, deactivationjob_found) = removeJobsForDepartureTime(deptime)
    if deactivationjob_found and not activationjob_found:
        # Heater has been activated for this departure! Turn it off immediately
        turn_off_heater(deptime.carName)
    if deptime.recurringId == -1:
        # single shot departure -> remove it
        departureTimes.remove(deptime)
    else:
        # recurring departure, just disable it. Removing it will make it be readded
        deptime.enabled = False


# dataLock must be held by caller!
def removeJobsForDepartureTime(deptime):
    checkcarengineheaterjob_found = False
    activationjob_found = False
    deactivationjob_found = False
    jobs2remove = []
    for job in jobscheduler.joblist:
        if isinstance(job, (CheckCarEngineHeaterJob,
                            ActivateCarEngineHeaterJob,
                            DeactivateCarEngineHeaterJob)):
            if job.departureId == deptime.id:
                if isinstance(job, CheckCarEngineHeaterJob):
                    checkcarengineheaterjob_found = True
                if isinstance(job, ActivateCarEngineHeaterJob):
                    activationjob_found = True
                if isinstance(job, DeactivateCarEngineHeaterJob):
                    deactivationjob_found = True
                jobs2remove += [job]  # "Schedule" deactivate job for removal

    for job in jobs2remove:
        jobscheduler.removeJob(job)
    return (checkcarengineheaterjob_found,
            activationjob_found,
            deactivationjob_found)


def create_app():
    app = Flask(__name__, static_url_path='')

    #
    # Departures
    #

    @app.route('/_get_departures')
    def get_departures():
        #global departureTimes
        carName = request.args.get('carname', None, type=str)
        deptimes = []
        for departureTime in departureTimes:
            if departureTime.enabled:
                if carName is None or carName == departureTime.carName:
                    deptimes += [copy.deepcopy(departureTime)]
        for deptime in deptimes:
            deptime.when_str = deptime.when.strftime("%a %d/%m %H:%M")
            deptime.year = deptime.when.strftime("%Y")
            deptime.month = deptime.when.strftime("%m")
            deptime.day_of_month = deptime.when.strftime("%d")
            deptime.hour = deptime.when.strftime("%H")
            deptime.minute = deptime.when.strftime("%M")
        deptimes.sort(key=lambda x: x.when, reverse=True)
        return jsonpickle.encode(deptimes)


    @app.route('/_add_departure')
    def add_departure():
        global departureTimes
        global dataLock
        with dataLock:
            new_departure_datetime = request.args.get('when', None, type=str)
            carName = request.args.get('carname', None, type=str)

            if new_departure_datetime is None or \
               carName is None:
                result = jsonify("")
                result.status_code = 500
                log.info("Add departure failed. not all params provided")
                return result
            when = datetime.datetime.strptime(new_departure_datetime, '%Y/%m/%d %H:%M')
            departureTimes += [DepartureTime(when, carName)]
            writeDepartureTimesToFile(departureTimes)
            return jsonify(result="OK")


    @app.route('/_remove_departure')
    def remove_departure():
        global departureTimes
        global dataLock
        with dataLock:
            id = request.args.get('id', 0, type=int)
            for deptime in departureTimes:
                if deptime.id == id:
                    deptime.enabled = False
                    carName = deptime.carName

                    removeDepartureTime(deptime)

            writeDepartureTimesToFile(departureTimes)
            return jsonify(result="OK")

    #
    # Recurring Departures
    #

    @app.route('/_get_recurring_departures')
    def get_recurring_departures():
        global recurringDepartureTimes
        recdeptimes = []
        for recDepartureTime in recurringDepartureTimes:
            recdeptimes += [copy.deepcopy(recDepartureTime)]
        for recdeptime in recdeptimes:
            recdeptime.hour = recdeptime.time.strftime("%H")
            recdeptime.minute = recdeptime.time.strftime("%M")
        recdeptimes.sort(key=lambda x: x.day_of_week)
        writeRecurringDepartureTimesToFile(recurringDepartureTimes)
        return jsonpickle.encode(recdeptimes)


    @app.route('/_update_recurring_departure')
    def update_recurring_departure():
        global recurringDepartureTimes
        global dataLock
        with dataLock:
            id = request.args.get('id', 0, type=int)
            carname = request.args.get('carname', None, type=str)
            dayofweek = request.args.get('dayofweek', None, type=str)
            hour = request.args.get('hour', None, type=int)
            minute = request.args.get('minute', None, type=int)
            log.debug("Update: id: " + str(id) +
                      ", carname: " + str(carname) +
                      ", dayofweek: " + str(dayofweek) +
                      ", hour: " + str(hour) +
                      ", minute: " + str(minute))
            print("innan remove")
            InfoJob(datetime.datetime.now()).execute()

            found = False
            for _, recdep in enumerate(recurringDepartureTimes):
                if recdep.id == id:
                    found = True
                    if carname is not None:
                        recdep.carName = carname
                    if dayofweek is not None:
                        recdep.day_of_week = weekday2index(dayofweek)
                    if hour is not None:
                        recdep.time = recdep.time.replace(hour=hour)
                    if minute is not None:
                        recdep.time = recdep.time.replace(minute=minute)

                    removeDepartureTimesForRecurringDepartureTime(recdep)

            writeRecurringDepartureTimesToFile(recurringDepartureTimes)
            if found:
                return jsonify(result="OK")
            #else:
                # ???

    @app.route('/_add_recurring_departure')
    def add_recurring_departure():
        global recurringDepartureTimes
        global dataLock
        with dataLock:
            carname = request.args.get('carname', None, type=str)
            dayofweek = request.args.get('dayofweek', None, type=int)
            hour = request.args.get('hour', None, type=int)
            minute = request.args.get('minute', None, type=int)
            log.debug("Add recurring departure: " +
                      "carname: " + str(carname) +
                      ", dayofweek: " + str(dayofweek) +
                      ", hour: " + str(hour) +
                      ", minute: " + str(minute))
            recdeptime = RecurringDepartureTime(config['weekdays'][dayofweek], datetime.time(hour=hour, minute=minute), carName=carname)
            recurringDepartureTimes.append(recdeptime)
            writeRecurringDepartureTimesToFile(recurringDepartureTimes)
            return jsonify(result="OK")


    @app.route('/_remove_recurring_departure')
    def remove_recurring_departure():
        global recurringDepartureTimes
        global dataLock
        with dataLock:
            id = request.args.get('id', 0, type=int)
            removeRecurringDepartureTime(recurringDepartureTimes, id)
            writeRecurringDepartureTimesToFile(recurringDepartureTimes)
            return jsonify(result="OK")

    #
    # Misc
    #

    @app.route('/_debug')
    def debug():
        string = "Configured recurring departures:<br>"
        for recdep in recurringDepartureTimes:
            string += "   Car: " + recdep.carName + \
                      ", DoW: " + str(recdep.day_of_week) + \
                      ", when: " + str(recdep.time) + \
                      ", id: " + str(recdep.id) + "<br>"

        string += "<br>Planned departures:<br>"
        for dep in departureTimes:
            string += "   Car: " + dep.carName + \
                      ", when: " + str(dep.when) + \
                      ", id: " + str(dep.id) + \
                      ", recurringId: " + str(dep.recurringId) + \
                      ", enabled: " + str(dep.enabled) + "<br>"

        string += "<br>Jobs:<br>"
        for job in jobscheduler.joblist:
            string += "   " + str(job) + "<br>"

        string += "<br>Switches:<br>"
        for switch in switches:
            string += "   " + str(switch) + "<br>"
        return string


    @app.route('/_get_cars')
    def get_cars():
        global dataLock
        with dataLock:
            return jsonpickle.encode(cars)


    #
    # HTML stuffs
    #

    @app.route('/')
    def root():
        #return app.send_static_file('index.html')
        #return send_static('index.html')
        carnames = []
        for car in cars:
            carnames.append(car.name)
        data = {
            "cars": carnames,
            "weekdays": config['weekdays'],
            "hours": config['hours'],
            "minutes": config['minutes'],
            #"lang_departures": config['lang_departures'],
            #"lang_recurring_departures": config['lang_recurring_departures'],
            "lang_remove": config['lang_remove']
        }
        return render_template('index.html',
                               python_data=data,
                               lang_add=config['lang_add'],
                               lang_departures=config['lang_departures'],
                               lang_recurring_departures=config['lang_recurring_departures'],
                               lang_cars=config['lang_cars'])

    @app.route('/static/<path:path>')
    def send_static(path):
        return send_from_directory('static', path)


    @app.route('/static/datetimepicker-master/<path:path>')
    def send_static_datetimepicker_master(path):
        return send_from_directory('static/datetimepicker-master/', path)


    @app.route('/static/datetimepicker-master/build/<path:path>')
    def send_static_datetimepicker_master_build(path):
        return send_from_directory('static/datetimepicker-master/build/', path)

    #
    # Misc
    #

    return app

def jobExec():
    while keep_running:
        jobscheduler.process()
        time.sleep(1)


def interrupt():
    print("interrupt caught")
    #sys.exit()

def loadDepartureTimesFromFile(filename):
    global departureTimes
    try:
        with open(filename, "r") as f:
            data = f.read()
            if data != "":
                departureTimes = jsonpickle.decode(data)
                log.debug("Departures read from file:")
                for deptime in departureTimes:
                    log.debug( deptime.carName + ": " + str(deptime.when))
    except FileNotFoundError as e:
        log.info ("departuretimes.json not found. Continuing without it.")


def loadRecurringDeparturesFromFile(filename):
    global recurringDepartureTimes
    try:
        with open(filename, "r") as f:
            data = f.read()
            if data != "":
                recurringDepartureTimes = jsonpickle.decode(data)
                log.debug("Recurring departures read from file:")
                for recdeptime in recurringDepartureTimes:
                    log.debug(recdeptime.carName + ": " +
                              str(recdeptime.day_of_week) + " " +
                              str(recdeptime.time))
    except FileNotFoundError as e:
        log.info("recurringdeparturetimes.json not found. Continuing without it.")


def main():
    global config
    global hassapi
    global cars
    global jobThread
    global jobscheduler
    global recurringDepartureTimes

    config = read_config("config.json")
    if config is None:
        print ("Please copy config.json_sample to config.json and adjust")
        exit(1)

    log.setup(config['mailHost'],
              config['mailFromAddr'],
              config['mailToAddr'],
              config['logfile'],
              config['loglevel_screen'],
              config['loglevel_file'],
              True)

    log.info("Starting up")
    hassapi = HassAPI(token=config['homeassistant_token'])
    for car in config['cars']:
        cars.append(Car(car['name'], car['switch']))

    atexit.register(interrupt)

    jobThread = threading.Thread(target=jobExec)
    jobThread.start()

    loadDepartureTimesFromFile("departuretimes.json")
    loadRecurringDeparturesFromFile("recurringdeparturetimes.json")

    jobscheduler.addJob(RemoveDepartureJob(datetime.datetime.today()))
    jobscheduler.addJob(AddRecurringDepartureJob(datetime.datetime.today()))
    jobscheduler.addJob(UpdateJobsJob(datetime.datetime.today()))
    jobscheduler.addJob(InfoJob(datetime.datetime.today() + datetime.timedelta(seconds=30)))
    jobscheduler.addJob(HomeAssistantSyncJob(datetime.datetime.today()))
    jobscheduler.addJob(HomeAssistantStateSyncJob(datetime.datetime.today() + datetime.timedelta(seconds=5)))

    signal.signal(signal.SIGINT, signal_handler)
    app = create_app()
    app.run(host='0.0.0.0')


if __name__ == "__main__":
    main()
