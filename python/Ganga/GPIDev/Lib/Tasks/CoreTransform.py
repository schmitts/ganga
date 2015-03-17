from Ganga.GPIDev.Lib.Tasks.common import *
from Ganga.GPIDev.Lib.Tasks.ITransform import ITransform
from Ganga.GPIDev.Lib.Tasks.CoreUnit import CoreUnit
from Ganga.GPIDev.Lib.Dataset.GangaDataset import GangaDataset
from Ganga.GPIDev.Lib.Job.Job import JobError, Job
import copy, re

class CoreTransform(ITransform):
   _schema = Schema(Version(1,0), dict(ITransform._schema.datadict.items() + {
            'unit_splitter'           : ComponentItem('splitters', defvalue=None, optional=1,load_default=False, doc='Splitter to be used to create the units'),
            'chaindata_as_inputfiles' : SimpleItem(defvalue=False,doc="Treat the inputdata as inputfiles, i.e. copy the inputdata to the WN"),
            'files_per_unit'          : SimpleItem(defvalue=-1,doc="Number of files per unit if possible. Set to -1 to just create a unit per input dataset"),
            'fields_to_copy': SimpleItem(defvalue = [], typelist=['str'], sequence=1, doc = 'A list of fields that should be copied when creating units, e.g. application, inputfiles. Empty (default) implies all fields are copied unless the GeenricSplitter is used '),
    }.items()))
   
   _category = 'transforms'
   _name = 'CoreTransform'
   _exportmethods = ITransform._exportmethods + [ ]

   def __init__(self):
      super(CoreTransform,self).__init__()

   def createUnits(self):
      """Create new units if required given the inputdata"""

      # call parent for chaining
      super(CoreTransform,self).createUnits()

      
      # Use the given splitter to create the unit definitions
      if len(self.units) > 0:
         # already have units so return
         return

      if self.unit_splitter == None and len(self.inputdata) == 0:
         raise ApplicationConfigurationError(None, "No unit splitter or InputData provided for CoreTransform unit creation, Transform %d (%s)" % 
                                             (self.getID(), self.name))

      # -----------------------------------------------------------------
      # split over unit_splitter by preference
      if self.unit_splitter:

         # create a dummy job, assign everything and then call the split
         j = Job()
         j.backend = self.backend.clone()
         j.application = self.application.clone()

         if self.inputdata:
            j.inputdata = self.inputdata.clone()

         subjobs = self.unit_splitter.split(j)

         if len(subjobs) == 0:
            raise ApplicationConfigurationError(None, "Unit splitter gave no subjobs after split for CoreTransform unit creation, Transform %d (%s)" % 
                                                (self.getID(), self.name))

         # only copy the appropriate elements    
         fields = []
         if len( self.fields_to_copy ) > 0:
            fields = self.fields_to_copy
         elif self.unit_splitter._name == "GenericSplitter":
            if self.unit_splitter.attribute != "":
               fields = [ self.unit_splitter.attribute.split(".")[0] ]
            else:
               for attr in self.unit_splitter.multi_attrs.keys():
                  fields.append( attr.split(".")[0] )

         # now create the units from these jobs
         for sj in subjobs:
            unit = CoreUnit()
         
            for attr in fields:
               setattr( unit, attr, copy.deepcopy( getattr(sj, attr) ) )

            self.addUnitToTRF( unit )

      # -----------------------------------------------------------------
      # otherwise split on inputdata
      elif len(self.inputdata) > 0:

         if self.files_per_unit > 0:

            # combine all files and split accorindgly
            filelist = []
            for ds in self.inputdata:
            
               if ds._name == "GangaDataset":
                  for f in ds.files:
                     try:
                        for sf in f.getSubFiles():
                           filelist.append( sf )
                        
                     except NotImplementedError:
                        logger.warning("getSubFiles not implemented for File '%s'" % f._name)

               else:
                  logger.warning("Dataset '%s' doesn't support files" % ds._name)
               
            # create DSs and units for this list of files
            fid = 0
            while fid < len(filelist):
               unit = CoreUnit()
               unit.name = "Unit %d" % len(self.units)
               unit.inputdata = GangaDataset(files=filelist[fid:fid+self.files_per_unit])
               unit.inputdata.treat_as_inputfiles = self.inputdata[0].treat_as_inputfiles

               fid += self.files_per_unit

               self.addUnitToTRF( unit )

         else:
            # just produce one unit per dataset
            for ds in self.inputdata:
               unit = CoreUnit()
               unit.name = "Unit %d" % len(self.units)
               unit.inputdata = copy.deepcopy( ds )
               self.addUnitToTRF( unit )


   def createChainUnit( self, parent_units, use_copy_output = True ):
      """Create an output unit given this output data"""
      
      # check parent units/jobs are complete
      if not self.checkUnitsAreCompleted( parent_units ):
         return None

      # get the include/exclude masks
      incl_pat_list, excl_pat_list = self.getChainInclExclMasks( parent_units )

      # go over the output files and transfer to input data
      for sj in self.getParentUnitJobs( parent_units ):
         for f in sj.outputfiles:
            for f2 in f.getSubFiles():
               if len(incl_pat_list) > 0:
                  for pat in incl_pat_list:
                     if re.search( pat, f2.namePattern ):
                        flist.append( f2 )
               else:
                  flist.append( f2 )

               for pat in excl_pat_list:
                  if re.search( pat, f2.namePattern ):
                     flist.remove( f2 )

      # now create the unit with a GangaDataset
      unit = CoreUnit()
      unit.name = "Unit %d" % len(self.units)
      unit.inputdata = GangaDataset(files=flist )
      unit.inputdata.treat_as_inputfiles = self.chaindata_as_inputfiles

      return unit
