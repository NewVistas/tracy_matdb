"""Implements a `matdb` compatible subclass of the
:class:`ase.calculators.espresso.Espresso` calculator.
.. note:: Because this calculator is intended to be run asynchronously as part
  of `matdb` framework, it does *not* include a method to actually execute the
  calculation. Although the ASE calculator provides an interface to do so,
  `matdb` uses templates to access HPC resources.
.. warning:: Because of the underlying implementation in ASE, you must use a separate
  instance of the :class:`AsyncQe` for each :class:`ase.Atoms` object that you
  want to calculate for.
"""
from os import path, stat, mkdir, remove, environ
import mmap

import ase
from ase.calculators.espresso import Espresso

from matdb.calculators.basic import AsyncCalculator
from matdb import msg
from matdb.kpoints import custom as write_kpoints
from matdb.utility import chdir, execute, relpath
from matdb.exceptions import VersionError
        
class AsyncQe(Espresso, AsyncCalculator):
    """Represents a calculator that can compute material properties with Quantum Espresso,
    but which can do so asynchronously.
    .. note:: The arguments and keywords for this object are identical to the
      :class:`~ase.calculators.qe.Espresso` calculator that ships with ASE. We
      add some extra functions so that it plays nicely with `matdb`.

    Args:
        atoms (matdb.Atoms): configuration to calculate using QE.
        folder (str): path to the directory where the calculation should take
          place.
        contr_dir (str): The absolute path of the controller's root directory.
        ran_seed (int or float): the random seed to be used for this calculator.
    
    Attributes:
        tarball (list): of `str` QE output file names that should be included
          in an archive that represents the result of the calculation.
        folder (str): path to the directory where the calculation should take
          place.
    """
    key = "qe"
    tarball = ["vasprun.xml"]

    def __init__(self, atoms, folder, contr_dir, ran_seed, *args, **kwargs):
        
        self.folder = path.abspath(path.expanduser(folder))
        self.kpoints = None
        if path.isdir(contr_dir):
            self.contr_dir = contr_dir
        else:
            msg.err("{} is not a valid directory.".format(contr_dir))

        self.in_kwargs = kwargs.copy()
        input_dict = {}
        
        # set default values for tprnfor and tstress so that the QE
        # calculates the forces and stresses unless over-written by
        # user.
        input_dict["tprnfor"] = kwargs["tprnfor"]  if "tprnfor" in kwargs else True
        input_dict["tstress"] = kwargs["tstress"]  if "tstress" in kwargs else True

        if "kpoints" in kwargs:
            self.kpoints = kwargs.pop("kpoints")
        if self.kpoints["method"] == "mueller":
            msg.err("The Mueller server does not support QE at this time.")
        elif self.kpoints["method"] == "MP":
            input_dict["kpts"] = self.kpoints["divisions"]
            del self.kpoints["divisions"]
        elif self.kpoints["method"] == "kspacing":
            input_dict["kspacing"] = self.kpoints.pop(["spacing"])

        if "offset" in self.kpoints:
            input_dict["koffset"] = self.kpoints["offset"]

        self.potcars = kwargs.pop("potcars")
        if "directory" in self.potcars:
            input_dict["pseudo_dir"] = self.potcars["directory"]
        input_dict["pseudopotentials"] = self.potcars["potentials"]

        self.args = args
        self.kwargs = kwargs

        self.ran_seed = ran_seed
        self.version = None
        print(input_dict)
        super(AsyncQe, self).__init__(input_dict=input_dict, *args, **kwargs)
        if not path.isdir(self.folder):
            mkdir(self.folder)
            
        self.atoms = atoms
           
        self._check_potcars()

    def _check_potcars(self):
        """Checks that the potcar version match the input versions.
        """
        if "directory" in self.potcars:
            pseudo_dir = self.potcars["directory"]
        else:
            pseudo_dir = environ.get("ESPRESSO_PSEUDO", None)
            if pseudo_dir is None:
                pseudo_dir = path.join(path.expanduser('~'), 'espresso', 'pseudo')

        versions = self.potcars["versions"]
        for spec, potcar in self.potcars["potentials"].items():
            target = path.join(pseudo_dir, potcar)
            if path.isfile(target):
                #QE potentials have two version numbers. The first is
                #usually on the first line of the file and the second
                #is somewhere in the introductory information block.
                v1 = versions[spec][0]
                v2 = versions[spec][1]
                v2_found = False
                l_count = 0
                with open(target, "r") as f:
                    for line in f:
                        temp_line = line.strip()
                        if l_count == 0:
                            if not v1 in temp_line:
                                VersionError("{0} does not match supplied version "
                                             "{1} for species {2}".format(line, v1, spec))
                        else:
                            if v2 in temp_line:
                                v2_found = True
                                break
                        l_count += 1
                        
                if not v2_found:
                    VersionError("Version {0} could not be found in potential file {1} "
                                 "for species {2}".format(v2, target, spec))
                    
            else:
                raise IOError("Potential file {0} does not exist".format(target))
        
    def write_input(self, atoms):
        """Overload of the ASE input writer.
        """
        if not path.isdir(self.folder):
            mkdir(self.folder)
        with chdir(self.folder):
            super(AsyncQe, self).write_input(atoms)

    def can_execute(self, folder):
        """Returns True if the specified folder is ready to execute QE
        in.
        """
        if not path.isdir(folder):
            return False

        sizeok = lambda x: stat(x).st_size > 25
        required = ["espresso.pwi"]
            
        present = {}
        for rfile in required:
            target = path.join(folder, rfile)
            present[rfile] = path.isfile(target) and sizeok(target)

        if not all(present.values()):
            for f, ok in present.items():
                if not ok:
                    msg.info("{} not present for Quantum Espresso execution.".format(f), 2)
        return all(present.values())

    def can_extract(self, folder):
        """Returns True if the specified VASP folder has completed
        executing and the results are available for use.
        """
        if not path.isdir(folder):
            return False
    
        #If we can extract a final total energy from the OUTCAR file, we
        #consider the calculation to be finished.
        outcar = path.join(folder, "pwscf.xml")
        if not path.isfile(outcar):
            return False

        line = None
        with open(outcar, 'r') as f:
            # memory-map the file, size 0 means whole file
            m = mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ)  
            i = m.rfind('free  energy')
            # we look for this second line to verify that VASP wasn't
            # terminated during runtime for memory or time
            # restrictions
            if i > 0:
                # seek to the location and get the rest of the line.
                m.seek(i)
                line = m.readline()

        if line is not None:
            return "TOTEN" in line or "Error" in line
        else:
            return False

    def is_executing(self, folder):
        """Returns True if the specified VASP folder is in process of executing.

        Args:
            folder (str): path to the folder in which the executable was run.
        """
        outcar = path.join(folder, "pwscf.xml")
        outcars = path.isfile(outcar)
        busy = not self.can_extract(folder)            
        return outcars and busy

    def create(self, rewrite=False):
        """Creates all necessary input files for the QE calculation.

        Args:
            rewrite (bool): when True, overwrite any existing files with the
              latest settings.
        """
        self.write_input(self.atoms)

    def extract(self, folder, cleanup="default"):
        """Extracts results from completed calculations and sets them on the
        :class:`ase.Atoms` object.

        Args:
            folder (str): path to the folder in which the executable was run.
            cleanup (str): the level of cleanup to perfor after extraction.
        """
        # Read output
        # atoms_sorted = ase.io.read(path.join(folder,'CONTCAR'), format='vasp')

        # if (self.int_params['ibrion'] is not None and
        #         self.int_params['nsw'] is not None):
        #     if self.int_params['ibrion'] > -1 and self.int_params['nsw'] > 0:
        #         # Update atomic positions and unit cell with the ones read
        #         # from CONTCAR.
        #         self.atoms.positions = atoms_sorted[self.resort].positions
        #         self.atoms.cell = atoms_sorted.cell

        # # we need to move into the folder being extracted in order to
        # # let ase check the convergence
        # with chdir(folder):
        #     self.converged = self.read_convergence()
        #     self.set_results(self.atoms)
        #     E = self.get_potential_energy(atoms=self.atoms)
        #     F = self.forces
        #     S = self.stress
        #     self.atoms.add_property("qe_force", F)
        #     self.atoms.add_param("qe_stress", S)
        #     self.atoms.add_param("qe_energy", E)

        # self.cleanup(folder,clean_level=cleanup)

    def cleanup(self, folder, clean_level="default"):
        """Performs cleanup on the folder where the calculation was
        performed. The clean_level determines which files get removed.

        Args:
            folder (str): the folder to be cleaned.
            clean_level (str): the level of cleaning to be done.
        """

        light = ["CHG", "XDATCAR", "DOSCAR", "PCDAT"]
        default =["CHGCAR", "WAVECAR", "IBZKPT", "EIGENVAL",
                  "DOSCAR", "PCDAT"]
        aggressive = ["vasprun.xml", "OUTCAR", "CONTCAR", "OSZICAR"]

        # if clean_level == "light":
        #     rm_files = light
        # elif clean_level == "aggressive":
        #     rm_files = light + default + aggressive
        # else:
        #     rm_files = light + default
        
        # for f in rm_files:
        #     target = path.join(folder,f)
        #     if path.isfile(target):
        #         remove(target)

    def to_dict(self):
        """Writes the current version number of the code being run to a
        dictionary along with the parameters of the code.

        Args:
            folder (str): path to the folder in which the executable was run.
        """
        # qe_dict = {"folder":self.folder, "ran_seed":self.ran_seed,
        #              "contr_dir":self.contr_dir, "kwargs": self.in_kwargs,
        #              "args": self.args}

        return qe_dict
