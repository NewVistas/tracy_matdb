"""Implements a `matdb` compatible subclass of the
:class:`ase.calculators.vasp.Vasp` calculator.

.. note:: Because this calculator is intended to be run asynchronously as part
  of `matdb` framework, it does *not* include a method to actually execute the
  calculation. Although the ASE calculator provides an interface to do so,
  `matdb` uses templates to access HPC resources.

.. warning:: Because of the underlying implementation in ASE, you must use a separate
  instance of the :class:`AsyncVasp` for each :class:`ase.Atoms` object that you
  want to calculate for.

"""
import ase
from ase.calculators.vasp import Vasp
from os import path, stat, mkdir
import mmap
from matdb.calculators.basic import AsyncCalculator
from matdb import msg
from matdb.kpoints import custom as write_kpoints

class AsyncVasp(Vasp, AsyncCalculator):
    """Represents a calculator that can compute material properties with VASP,
    but which can do so asynchronously.

    .. note:: The arguments and keywords for this object are identical to the
      :class:`~ase.calculators.vasp.Vasp` calculator that ships with ASE. We
      add some extra functions so that it plays nicely with `matdb`.

    Args:
        atoms (quippy.Atoms): configuration to calculate using VASP.
        folder (str): path to the directory where the calculation should take
          place.

    Attributes:
        tarball (list): of `str` VASP output file names that should be included
          in an archive that represents the result of the calculation.
        folder (str): path to the directory where the calculation should take
          place.
    """
    tarball = ["vasprun.xml"]

    def __init__(self, atoms, folder, *args, **kwargs):
        self.folder = path.abspath(path.expanduser(folder))
        self.kpoints = kwargs.pop("kpoints")
        super(AsyncVasp, self).__init__(*args, **kwargs)
        if not path.isdir(self.folder):
            mkdir(self.folder)
        self.initialize(atoms)

    def write_input(self, atoms, directory='./'):
        """Overload of the ASE input writer that handles the k-points using our
        built-in routines.
        """
        from ase.io.vasp import write_vasp
        write_vasp(join(directory, 'POSCAR'),
                   self.atoms_sorted,
                   symbol_count=self.symbol_count)
        self.write_incar(atoms, directory=directory)
        self.write_potcar(directory=directory)
        if self.kpoints is not None:
            write_kpoints(directory, self.kpoints, self.atoms)
        else:
            self.write_kpoints(directory=directory)
        self.write_sort_file(directory=directory)
        
    def can_execute(self, folder):
        """Returns True if the specified folder is ready to execute VASP
        in.
        """
        if not path.isdir(folder):
            return False
        
        required = ["INCAR", "POSCAR", "KPOINTS", "POTCAR"]
        present = {}
        for rfile in required:
            target = path.join(folder, rfile)
            sizeok = stat(target).st_size > 25
            present[rfile] = path.isfile(target) and sizeok

        if not all(present.values()):
            for f, ok in present.items():
                if not ok:
                    msg.info("{} not present for VASP execution.".format(f), 2)
        return all(present.values())

    def can_cleanup(self, folder):
        """Returns True if the specified VASP folder has completed
        executing and the results are available for use.
        """
        if not path.isdir(folder):
            return False
    
        #If we can extract a final total energy from the OUTCAR file, we
        #consider the calculation to be finished.
        outcar = path.join(folder, "OUTCAR")
        if not path.isfile(outcar):
            return False

        line = None
        with open(outcar, 'r') as f:
            # memory-map the file, size 0 means whole file
            m = mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ)  
            i = m.rfind('free  energy')
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
        outcar = path.join(folder, "OUTCAR")
        outcars = path.isfile(outcar)
        busy = not self.can_cleanup(folder)            
        return outcars and busy

    def create(self, rewrite=False):
        """Creates all necessary input files for the VASP calculation.

        Args:
            rewrite (bool): when True, overwrite any existing files with the
              latest settings.
        """
        self.write_input(atoms, self.folder)

    def cleanup(self, folder):
        """Extracts results from completed calculations and sets them on the
        :class:`ase.Atoms` object.

        Args:
            folder (str): path to the folder in which the executable was run.
        """
        # Read output
        atoms_sorted = ase.io.read('CONTCAR', format='vasp')

        if (self.int_params['ibrion'] is not None and
                self.int_params['nsw'] is not None):
            if self.int_params['ibrion'] > -1 and self.int_params['nsw'] > 0:
                # Update atomic positions and unit cell with the ones read
                # from CONTCAR.
                self.atoms.positions = atoms_sorted[self.resort].positions
                self.atoms.cell = atoms_sorted.cell

        self.converged = self.read_convergence()
        self.set_results(self.atoms)
