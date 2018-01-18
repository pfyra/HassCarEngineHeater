from __future__ import print_function
from datetime import datetime
import random
import termcolor2 as color

#
# Job stuff
#

class Job(object):
    """
    Superclass for Jobs
    """
    def __init__(self, execTime, jobname=None):
        # get rid of timezone crap
        self.execTime = datetime(execTime.year,
                                 execTime.month,
                                 execTime.day,
                                 execTime.hour,
                                 execTime.minute,
                                 execTime.second)
        self.jobname = jobname if jobname is not None else str(self.__class__)[17:-2] # remove class __main__ etc
  #      _logger.debug("\033[0;33mCreating\033[0m " + self.toString() + " @ " + str(execTime))
        self.jobid = random.randrange(1000000, 9999999)
  
    def execute(self):
  #     _logger.critical(color.red("ERROR: Superclass Job execute called for Job " + self.jobname))
        print(color.red("ERROR: Superclass Job execute called for Job " + self.jobname))
        exit(1)
  
    def reschedule(self):
        return None
  
    def __str__(self):
        #return "Type: " + self.jobname + ", id: " + str(self.jobid) + ", time: " + str(self.execTime)
        return self.jobname + ", id: " + str(self.jobid) + ", time: " + str(self.execTime)


