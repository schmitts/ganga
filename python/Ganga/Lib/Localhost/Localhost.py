from Ganga.GPIDev.Adapters.IBackend import IBackend
from Ganga.GPIDev.Schema import *

import Ganga.Utility.logging
logger = Ganga.Utility.logging.getLogger()

import Ganga.Utility.Config
config = Ganga.Utility.Config.makeConfig('Local','parameters of the local backend (jobs in the background on localhost)')

config.addOption('remove_workdir', True, 'remove automatically the local working directory when the job completed')
config.addOption('location', None, 'The location where the workdir will be created. If None it defaults to the value of $TMPDIR')

import Ganga.Utility.logic, Ganga.Utility.util

from Ganga.GPIDev.Lib.File import FileBuffer

import os,sys,copy
import os.path,re,errno

import subprocess

import datetime
import time

import re

class Localhost(IBackend):
    """Run jobs in the background on local host.

    The job is run in the workdir (usually in /tmp).
    """
    _schema = Schema(Version(1,2), {'nice' : SimpleItem(defvalue=None,typelist=None,doc='*NOT USED*', hidden=1),
                                    'id' : SimpleItem(defvalue=-1,protected=1,copyable=0,doc='Process id.'),
                                    'status' : SimpleItem(defvalue=None,typelist=None,protected=1,copyable=0,hidden=1,doc='*NOT USED*'),
                                    'exitcode' : SimpleItem(defvalue=None,typelist=['int','type(None)'],protected=1,copyable=0,doc='Process exit code.'),
                                    'workdir' : SimpleItem(defvalue='',protected=1,copyable=0,doc='Working directory.'),
                                    'actualCE' : SimpleItem(defvalue='',protected=1,copyable=0,doc='Hostname where the job was submitted.'),
                                    'wrapper_pid' : SimpleItem(defvalue=-1,protected=1,copyable=0,hidden=1,doc='(internal) process id of the execution wrapper'),
                                    'nice' : SimpleItem(defvalue=0, doc='adjust process priority using nice -n command')
                                    })
    _category = 'backends'
    _name = 'Local'
    _GUIPrefs = [ { 'attribute' : 'nice', 'widget' : 'String' },
                  { 'attribute' : 'id', 'widget' : 'Int' },
                  { 'attribute' : 'status' , 'widget' : 'String' },
                  { 'attribute' : 'exitcode', 'widget' : 'String' } ]
    _GUIAdvancedPrefs = [ { 'attribute' : 'nice', 'widget' : 'String' },
                          { 'attribute' : 'exitcode', 'widget' : 'String' } ]



    def __init__(self):
      super(Localhost,self).__init__()

    def submit(self, jobconfig, master_input_sandbox):
      prepared = self.preparejob(jobconfig, master_input_sandbox)
      self.run( prepared )
      return 1

    def resubmit(self):
      job = self.getJobObject()
      import shutil

      try:
          shutil.rmtree(self.workdir)
      except OSError as x:
          import errno
          if x.errno != errno.ENOENT:
              logger.error('problem cleaning the workdir %s, %s',self.workdir,str(x))
              return 0
      try:
          os.mkdir(self.workdir)
      except Exception as x:
        logger.error('cannot make the workdir %s, %s',self.workdir,str(x))
        return 0
      return self.run(job.getInputWorkspace().getPath('__jobscript__'))
      
    def run(self,scriptpath):
      try:
          process=subprocess.Popen(["python",scriptpath,'subprocess'])
      except OSError as x:
          logger.error('cannot start a job process: %s',str(x))
          return 0
      self.wrapper_pid=process.pid
      self.actualCE = Ganga.Utility.util.hostname()
      return 1

    def peek( self, filename = "", command = "" ):
      """
      Allow viewing of output files in job's work directory
      (i.e. while job is in 'running' state)
                                                                                
      Arguments other than self:
      filename : name of file to be viewed
                => Path specified relative to work directory
      command  : command to be used for file viewing
                                                                                
      Return value: None
      """
      job = self.getJobObject()
      topdir = self.workdir.rstrip( os.sep )
      path = os.path.join( topdir, filename ).rstrip( os.sep )
      job.viewFile( path = path, command = command )
      return None

    def getStateTime(self, status):
        """Obtains the timestamps for the 'running', 'completed', and 'failed' states.

           The __jobstatus__ file in the job's output directory is read to obtain the start and stop times of the job.
           These are converted into datetime objects and returned to the user.
        """
        j = self.getJobObject()
        end_list = ['completed', 'failed']
        d = {}
        checkstr=''
        
        if status == 'running': checkstr='START:'
        elif status == 'completed': checkstr='STOP:'
        elif status == 'failed': checkstr='FAILED:'
        else:
            checkstr=''
            
        if checkstr=='':
            logger.debug("In getStateTime(): checkstr == ''")
            return None 

        try:
            p = os.path.join(j.outputdir, '__jobstatus__')
            logger.debug("Opening output file at: %s", p)
            f = open(p)
        except IOError:
            logger.debug('unable to open file %s', p)
            return None 

        for l in f.readlines():
            if checkstr in l:
                pos=l.find(checkstr)
                timestr=l[pos+len(checkstr)+1:pos+len(checkstr)+25]
                try:
                    t = datetime.datetime(*(time.strptime(timestr, "%a %b %d %H:%M:%S %Y")[0:6]))
                except ValueError:
                    logger.debug("Value Error in file: '%s': string does not match required format.", p)
                    return None 
                return t

        f.close()
        logger.debug("Reached the end of getStateTime('%s'). Returning None.", status)
        return None 

    def timedetails(self):
        """Return all available timestamps from this backend.
        """
        j = self.getJobObject()
        try: ## check for file. if it's not there don't bother calling getSateTime (twice!)
            p = os.path.join(j.outputdir, '__jobstatus__')
            logger.debug("Opening output file at: %s", p)
            f = open(p)
            f.close()
        except IOError:
            logger.error('unable to open file %s', p) 
            return None 
        del f
        r = self.getStateTime('running')
        c = self.getStateTime('completed')
        d = {'START' : r, 'STOP' : c} 

        return d

    def preparejob(self, jobconfig, master_input_sandbox):

      job = self.getJobObject()
      #print str(job.backend_output_postprocess)        
      mon = job.getMonitoringService()
      import Ganga.Core.Sandbox as Sandbox
      subjob_input_sandbox = job.createPackedInputSandbox( jobconfig.getSandboxFiles()
        + Sandbox.getGangaModulesAsSandboxFiles(Sandbox.getDefaultModules())
        + Sandbox.getGangaModulesAsSandboxFiles(mon.getSandboxModules()) )

      appscriptpath = [jobconfig.getExeString()]+jobconfig.getArgStrings()
      if self.nice:
          appscriptpath = ['nice','-n %d'%self.nice] + appscriptpath
      if self.nice < 0:
          logger.warning('increasing process priority is often not allowed, your job may fail due to this')
          
      sharedoutputpath=job.getOutputWorkspace().getPath()
      outputpatterns=jobconfig.outputbox
      environment=jobconfig.env

      from Ganga.Utility import tempfile
      workdir = tempfile.mkdtemp(dir=config['location'])
      
      script= """#!/usr/bin/env python

import os,os.path,shutil,tempfile
import sys,time
import glob
import sys

# FIXME: print as DEBUG: to __syslog__ file
#print sys.path
#print os.environ['PATH']
#print sys.version

# bugfix #13314 : make sure that the wrapper (spawned process) is detached from Ganga session
# the process will not receive Control-C signals
# using fork  and doing setsid() before  exec would probably  be a bit
# better (to avoid  slim chance that the signal  is propagated to this
# process before setsid is reached)
# this is only enabled if the first argument is 'subprocess' in order to enable
# running this script by hand from outside ganga (which is sometimes useful)
if len(sys.argv)>1 and sys.argv[1] == 'subprocess':
 os.setsid()

############################################################################################

###INLINEMODULES###

############################################################################################

input_sandbox = ###INPUT_SANDBOX###
sharedoutputpath= ###SHAREDOUTPUTPATH###
outputpatterns = ###OUTPUTPATTERNS###
appscriptpath = ###APPSCRIPTPATH###
environment = ###ENVIRONMENT###
workdir = ###WORKDIR###

statusfilename = os.path.join(sharedoutputpath,'__jobstatus__')

try:
  statusfile=open(statusfilename,'w')
except IOError as x:
  print 'ERROR: not able to write a status file: ', statusfilename
  print 'ERROR: ',x
  raise
  
line='START: '+ time.strftime('%a %b %d %H:%M:%S %Y',time.gmtime(time.time())) + os.linesep
statusfile.writelines(line)
statusfile.flush()

os.chdir(workdir)

# -- WARNING: get the input files including the python modules BEFORE sys.path.insert()
# -- SINCE PYTHON 2.6 THERE WAS A SUBTLE CHANGE OF SEMANTICS IN THIS AREA

for f in input_sandbox:
  getPackedInputSandbox(f)

# -- END OF MOVED CODE BLOCK

#get input files
###DOWNLOADINPUTFILES###

# create inputdata list
###CREATEINPUTDATALIST###

import sys
sys.path.insert(0, ###GANGADIR###)
sys.path.insert(0,os.path.join(os.getcwd(),PYTHON_DIR))

try:
    import subprocess
except ImportError as x:
    sys.path.insert(0,###SUBPROCESS_PYTHONPATH###)
    import subprocess
try:
    import tarfile
except ImportError as x:
    sys.path.insert(0,###TARFILE_PYTHONPATH###)
    import tarfile


fullenvironment = os.environ.copy()
for key,value in environment.iteritems():
    fullenvironment[key] = value

outfile=open('stdout','w')
errorfile=open('stderr','w')

sys.stdout=open('./__syslog__','w')
sys.stderr=sys.stdout

###MONITORING_SERVICE###
monitor = createMonitoringObject()
monitor.start()

import subprocess

import time #datetime #disabled for python2.2 compatiblity

try:
 child = subprocess.Popen(appscriptpath, shell=False, stdout=outfile, stderr=errorfile, env=fullenvironment)
except OSError as x:
 errfile = open( 'tt', 'w' )
 errfile.close()
 print >> statusfile, 'EXITCODE: %d'%-9999
 print >> statusfile, 'FAILED: %s'%time.strftime('%a %b %d %H:%M:%S %Y') #datetime.datetime.utcnow().strftime('%a %b %d %H:%M:%S %Y')
 print >> statusfile, 'PROBLEM STARTING THE APPLICATION SCRIPT: %s %s'%(appscriptpath,str(x))
 statusfile.close()
 sys.exit()
 
print >> statusfile, 'PID: %d'%child.pid
statusfile.flush()

result = -1

try:
  while 1:
    result = child.poll()
    if result is not None:
        break
    outfile.flush()
    errorfile.flush()
    monitor.progress()
    time.sleep(0.3)
finally:
    monitor.progress()
    sys.stdout=sys.__stdout__
    sys.stderr=sys.__stderr__

monitor.stop(result)

outfile.flush()
errorfile.flush()

createOutputSandbox(outputpatterns,None,sharedoutputpath)

def printError(message):
    errorfile.write(message + os.linesep)
    errorfile.flush()  

def printInfo(message):
    outfile.write(message + os.linesep)
    outfile.flush()  


###OUTPUTUPLOADSPOSTPROCESSING###

outfile.close()
errorfile.close()

###OUTPUTSANDBOXPOSTPROCESSING###

line="EXITCODE: " + repr(result) + os.linesep
line+='STOP: '+time.strftime('%a %b %d %H:%M:%S %Y',time.gmtime(time.time())) + os.linesep
statusfile.writelines(line)
statusfile.close()
sys.exit()

"""

      import inspect
      script = script.replace('###INLINEMODULES###',inspect.getsource(Sandbox.WNSandbox))

      from Ganga.GPIDev.Lib.File.OutputFileManager import getWNCodeForOutputSandbox, getWNCodeForOutputPostprocessing, getWNCodeForDownloadingInputFiles, getWNCodeForInputdataListCreation
      from Ganga.Utility.Config import getConfig
      jobidRepr = repr(job.getFQID('.'))
      script = script.replace('###OUTPUTSANDBOXPOSTPROCESSING###',getWNCodeForOutputSandbox(job, ['stdout', 'stderr', '__syslog__'], jobidRepr))

      script = script.replace('###OUTPUTUPLOADSPOSTPROCESSING###',getWNCodeForOutputPostprocessing(job, ''))
      
      script = script.replace('###DOWNLOADINPUTFILES###',getWNCodeForDownloadingInputFiles(job, ''))

      script = script.replace('###CREATEINPUTDATALIST###', getWNCodeForInputdataListCreation(job, '') )

      script = script.replace('###APPLICATION_NAME###',repr(job.application._name))
      script = script.replace('###INPUT_SANDBOX###',repr(subjob_input_sandbox+master_input_sandbox))
      script = script.replace('###SHAREDOUTPUTPATH###',repr(sharedoutputpath))
      script = script.replace('###APPSCRIPTPATH###',repr(appscriptpath))
      script = script.replace('###OUTPUTPATTERNS###',repr(outputpatterns))
      script = script.replace('###JOBID###',jobidRepr)
      script = script.replace('###ENVIRONMENT###',repr(environment))
      script = script.replace('###WORKDIR###',repr(workdir))
      script = script.replace('###INPUT_DIR###',repr(job.getStringInputDir()))
      
      script = script.replace('###MONITORING_SERVICE###',job.getMonitoringService().getWrapperScriptConstructorText())

      self.workdir = workdir

      script = script.replace('###GANGADIR###',repr(getConfig('System')['GANGA_PYTHONPATH']))

      import Ganga.PACKAGE
      script = script.replace('###SUBPROCESS_PYTHONPATH###',repr(Ganga.PACKAGE.setup.getPackagePath2('subprocess','syspath',force=True)))
      script = script.replace('###TARFILE_PYTHONPATH###',repr(Ganga.PACKAGE.setup.getPackagePath2('tarfile','syspath',force=True)))             

      wrkspace = job.getInputWorkspace()
      scriptPath = wrkspace.writefile( FileBuffer('__jobscript__',script), executable=1)

      return scriptPath

    def kill(self):
        import os,signal

        job = self.getJobObject()
        
        ok = True
        try:
            # kill the wrapper script
            # bugfix: #18178 - since wrapper script sets a new session and new group, we can use this to kill all processes in the group
            os.kill(-self.wrapper_pid,signal.SIGKILL)
        except OSError as x:
            logger.warning('while killing wrapper script for job %d: pid=%d, %s',job.id,self.wrapper_pid,str(x))
            ok = False

        # waitpid to avoid zombies
        try:
            ws = os.waitpid(self.wrapper_pid,0)
        except OSError as x:
            logger.warning('problem while waitpid %d: %s',job.id,x)

        from Ganga.Utility.files import recursive_copy

        for fn in ['stdout','stderr','__syslog__']:
            try:
                recursive_copy(os.path.join(self.workdir,fn),job.getOutputWorkspace().getPath())
            except Exception as x:
                logger.info('problem retrieving %s: %s',fn,x)

        self.remove_workdir()
        return 1

    def remove_workdir(self):
        if config['remove_workdir']:
            import shutil
            try:
                shutil.rmtree(self.workdir)
            except OSError as x:
                logger.warning('problem removing the workdir %s: %s',str(self.id),str(x))            
    
    def updateMonitoringInformation(jobs):

      def get_exit_code(f):
          import re
          statusfile=open(f)
          stat = statusfile.read()
          statusfile.close()
          m = re.compile(r'^EXITCODE: (?P<exitcode>-?\d*)',re.M).search(stat)

          if m is None:
              return None
          else:
              return int(m.group('exitcode'))

      def get_pid(f):
          import re
          statusfile=open(f)
          stat = statusfile.read()
          statusfile.close()
          m = re.compile(r'^PID: (?P<pid>\d*)',re.M).search(stat)

          if m is None:
              return None
          else:
              return int(m.group('pid'))          

      logger.debug('local ping: %s',str(jobs))
      
      for j in jobs:
          outw=j.getOutputWorkspace()

          # try to get the application exit code from the status file
          try:
            statusfile = os.path.join(outw.getPath(),'__jobstatus__')
            if j.status == 'submitted':
                pid = get_pid(statusfile)
                if pid:
                    j.backend.id = pid
                    #logger.info('Local job %d status changed to running, pid=%d',j.id,pid)
                    j.updateStatus('running') # bugfix: 12194
            exitcode = get_exit_code(statusfile)
            status_file = open(statusfile)
            logger.debug('status file: %s %s',statusfile, status_file.read())
            status_file.close()
          except IOError as x:
            logger.debug('problem reading status file: %s (%s)',statusfile,str(x))
            exitcode=None
          except Exception as x:
              logger.critical('problem during monitoring: %s',str(x))
              import traceback
              traceback.print_exc()
              raise x

          # check if the exit code of the wrapper script is available (non-blocking check)
          # if the wrapper script exited with non zero this is an error
          try:
              ws = os.waitpid(j.backend.wrapper_pid,os.WNOHANG)
              if not Ganga.Utility.logic.implies(ws[0]!=0,ws[1]==0):
                  #FIXME: for some strange reason the logger DOES NOT LOG (checked in python 2.3 and 2.5)
                  ##print 'logger problem', logger.name
                  ##print 'logger',logger.getEffectiveLevel()
                  logger.critical('wrapper script for job %s exit with code %d',str(j.id),ws[1])
                  logger.critical('report this as a bug at https://its.cern.ch/jira/browse/GANGA')
                  j.updateStatus('failed')
          except OSError as x:
              if x.errno != errno.ECHILD:
                  logger.warning('cannot do waitpid for %d: %s',j.backend.wrapper_pid,str(x))

          # if the exit code was collected for the application get the exit code back
          
          if not exitcode is None:
              # status file indicates that the application finished
              j.backend.exitcode = exitcode

              if exitcode == 0:
                  j.updateStatus('completed')
              else:
                  j.updateStatus('failed')
              
              #logger.info('Local job %d finished with exitcode %d',j.id,exitcode)

              ##if j.outputdata:
              ##    j.outputdata.fill()

              j.backend.remove_workdir()
                  
                       
    updateMonitoringInformation = staticmethod(updateMonitoringInformation)
