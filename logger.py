from datetime import datetime
#from datetime import timedelta, tzinfo
import logging, logging.handlers
from BufferingSMTPHandler import BufferingSMTPHandler
#from enum import Enum
#import termcolor as color
#  mail_mailHost = 'smtp.hjartquist.se',
#  mail_fromAddr = 'timer@hjartquist.se',
#  mail_toAddr = 'peter@hjartquist.se')

class Loglevel:
  def __init__(self):
    _dummy = 0

  nolog = 0
  error = 1
  warn = 2
  info = 3
  debug = 4

loglevel = Loglevel()

class Logger():
  """
  """

  def __init__(self):
#    self.mailhost = None
#    self.fromaddr = None
#    self.toaddr = None
    self.logger = None
    self.bufferingSmtpHandler = None
    self.loglevel = loglevel.debug
    self.loglevel_file = loglevel.debug
    self.formatter = None
    self.logfile = ""

  def setup(self, mailhost, fromaddr, toaddr, logfile, loglevel_, loglevel_file, show_timestamps):
    if show_timestamps:
      logging.basicConfig(format='%(asctime)s %(message)s')
#    self.mailhost = mailhost
#    self.fromaddr = fromaddr
#    self.toaddr = toaddr
    self.logger = logging.getLogger()
    self.logger.setLevel(logging.DEBUG)

    if show_timestamps:
      self.formatter = logging.Formatter('%(asctime)s %(message)s')
    self.bufferingSmtpHandler = BufferingSMTPHandler(mailhost,
                                                     fromaddr,
                                                     toaddr,
                                                     'Car engine heater crashed',
                                                     1000000) #XXX: get rid of limit
    self.bufferingSmtpHandler.setFormatter(self.formatter)
    self.logger.addHandler(self.bufferingSmtpHandler)
    self.logfile = logfile
    self.loglevel = loglevel_
    self.loglevel_file = loglevel_file

  def fatal(self, string):
    if (self.loglevel >= loglevel.error):
      self.logger.fatal(string)
    if (self.loglevel_file >= loglevel.error):
      self.log2file(string)
    exit(1)

  def warn(self, string):
    if (self.loglevel >= loglevel.warn):
      self.logger.warn(string)
    if (self.loglevel_file >= loglevel.warn):
      self.log2file(string)

  def info(self, string):
    if (self.loglevel >= loglevel.info):
      self.logger.info(string)
    if (self.loglevel_file >= loglevel.info):
      self.log2file(string)

  def debug(self, string):
    if (self.loglevel >= loglevel.debug):
      self.logger.debug(string)
    if (self.loglevel_file >= loglevel.debug):
      self.log2file(string)

  def error(self, string, exc):
    if (self.loglevel >= loglevel.error):
      self.logger.error(string, exc_info=exc)
    if (self.loglevel_file >= loglevel.error):
      self.log2file(string)

  def destroy(self):
    self.bufferingSmtpHandler.dropAllMessages()

  def log2file(self, msg):
    try:
        with open(self.logfile, 'a+') as f:
            f.write(str(datetime.now()) + ": " + msg + '\n')
    except Exception as e:
        # I get stupid errors about log file not found when a+ should create it.
        pass



log = Logger()
