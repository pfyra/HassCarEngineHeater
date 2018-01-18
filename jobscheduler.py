from __future__ import print_function
from datetime import datetime, timedelta
from logger import log
import sys
import random

#internal
import termcolor2 as color
from job import Job



#
# Why do the jobs themselves know when they will run? Shouldn't that information be handled by the scheduler?
#


class JobScheduler:
  def __init__(self):
    self.joblist = []

  def addJob(self, job):
    self.joblist.append(job)
    self.joblist.sort(key=lambda j: j.execTime)

  def removeJob(self, job):
    self.joblist.remove(job)
    log.info("removing " + str(job))

  def process(self):
    joblistcopy = list(self.joblist)

    for job in joblistcopy:
      if (job.execTime < datetime.now()):
        log.debug( color.grey("running  " + job.jobname + \
                   " @ " + str(job.execTime)))
                    # + ", now: " +\
                   #str(datetime.now())))
        job.execute()
        newTime = job.reschedule()
        if newTime is not None:
          #log.debug("rescheduling " + str(job) + " @ " + str(newTime))
          job.execTime = newTime
        else:
          #log.debug("removing " + str(job))
          self.joblist.remove(job)
        #return # max 1 job to process at a time (i.e 1 job/second). Nexa signals will get messed up otherwise

  def listJobs(self):
    for job in self.joblist:
      log.info("Job: " + str(job) + " @ " + str(job.execTime))
