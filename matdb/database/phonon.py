"""Database of configurations that is created by displacing a given
unit cell along phonon modes using the eigenvectors.
"""
from .basic import Database
from matdb import msg
from os import path
import numpy as np

def _parsed_kpath(poscar):
    """Gets the special path in the BZ for the structure with the specified
    POSCAR and then parses the results into the format required by the package
    machinery.

    Args:
        poscar (str): path to the structure to get special path for.

    Returns:
        tuple: result of querying the materialscloud.org special path
        service. First term is a list of special point labels; second is the
        list of points corresponding to those labels.
    """
    from matdb.kpoints import kpath
    ktup = kpath(poscar)
    band = []
    labels = []
    names, points = ktup

    def fix_gamma(s):
        return r"\Gamma" if s == "GAMMA" else s
    
    for name in names:
        #Unfortunately, the web service that returns the path names returns
        #GAMMA for \Gamma, so that the labels need to be fixed.
        if isinstance(name, tuple):
            key = name[0]
            labels.append("{}|{}".format(*map(fix_gamma, name)))
        else:
            key = name
            labels.append(fix_gamma(name))

        band.append(points[key].tolist())

    return (labels, band)

class PhononDFT(Database):
    """Sets up the displacement calculations needed to construct the dynamical
    matrix. The dynamical matrix is required by :class:`PhononDatabase` to
    create the individual modulations.

    Args:
        atoms (quippy.atoms.Atoms): seed configuration that will be
          displaced to generate the database.
        root (str): path to the folder where the database directories will
          be stored.
        parent (matdb.database.controller.DatabaseCollection): parent collection
          to which this database belongs.
        incar (dict): specify additional settings for the INCAR file (i.e.,
          differing from, or in addition to those in the global set).
        kpoints (dict): specify additional settings for the PRECALC file (i.e.,
          differing from, or in addition to those in the global set).
        phonons (dict): specifying additional settings for `phonopy`
          configuration files (i.e., differing from, or in addition to those in
          the global set).

    .. note:: Additional attributes are also exposed by the super class
      :class:`Database`.

    Attributes:
        name (str): name of this database type relative to the over database
          collection. This is also the name of the folder in which all of its
          calculations will be performed.
        supercell (list): of `int`; number of cells in each direction for
          generating the supercell.
        phonodir (str): directory in which all `phonopy` executions take place.
        grid (list): of `int`; number of splits in each reciprocal
          lattice vector according to Monkhorst-Pack scheme.
    """
    name = "phondft"
    
    def __init__(self, atoms=None, root=None, parent=None,
                 kpoints={}, incar={}, phonons={}, execution={}):
        super(PhononDFT, self).__init__(atoms, incar, kpoints, execution,
                                         path.join(root, self.name),
                                         parent, "W", nconfigs=None)
        self.supercell = list(phonons.get("dim", [2, 2, 2]))
        self.grid = list(phonons.get("mp", [20, 20, 20]))
        self.phonodir = path.join(self.root, "phonopy")
        self.phonocache = path.join(self.root, "phoncache")
        
        self._bands = None
        """dict: keys are ['q', 'w', 'path', 'Q'], values are the distance along
        the special path (scalar), phonon frequencies at that distance (vector,
        one component for each frequency), q-positions of the special points
        along the paths, and their corresponding distances.
        """

        self._kpath = None
        """tuple: result of querying the materialscloud.org special path
        service. First term is a list of special point labels; second is the
        list of points corresponding to those labels.
        """

        self._dmatrix = None
        """dict: with keys ['dynmat', 'eigvals', 'eigvecs'] representing the dynamical
        matrix for the gamma point in the seed configuration along with its
        eigenvalues and eigenvectors.
        """
        
        from os import mkdir
        if not path.isdir(self.phonodir):
            mkdir(self.phonodir)
        if not path.isdir(self.phonocache):
            mkdir(self.phonocache)

        self._update_incar()

    def _update_incar(self):
        """Adds the usual settings for the INCAR file when performing
        frozen-phonon calculations. They are only added if they weren't already
        specified in the config file.
        """
        usuals = {
            "encut": 500,
            "ibrion": -1,
            "ediff": '1.0e-08',
            "ialgo": 38,
            "ismear": 0,
            "lreal": False
        }
        for k, v in usuals.items():
            if k not in self.incar:
                self.incar[k] = v
            
    def ready(self):
        """Returns True if all the phonon calculations have been completed, the
        force sets have been created, and the DOS has been calculated.
        """
        #If the DOS has been calculated, then all the other steps must have
        #completed correctly.
        dosfile = path.join(self.phonodir, "mesh.yaml")
        return path.isfile(dosfile)

    @property
    def dmatrix(self):
        """Returns the dynamical matrix extracted from the frozen
        phonon calculations at the gamma point in the BZ.
        """
        if self._dmatrix is not None:
            return self._dmatrix
        
        #Otherwise, we need to calculate it from scratch.
        qpoints = path.join(self.phonodir, "qpoints.yaml")
        if not path.isfile(qpoints):
            from matdb.utility import execute
            DIM = ' '.join(map(str, self.supercell))
            sargs = ["phonopy", '--dim="{}"'.format(DIM),
                     '--qpoints="0 0 0"', "--writedm"]
            xres = execute(sargs, self.phonodir, venv=True)
            if not path.isfile(qpoints):
                msg.err("could not calculate phonon bands; see errors.")

            if len(xres["error"]) > 0:
                msg.std(''.join(xres["error"]))

        if path.isfile(qpoints):
            import yaml
            data = yaml.load(open(qpoints))
            result = {}
            for i in range(len(data["phonon"])):
                dynmat = []
                dynmat_data = data['phonon'][i]['dynamical_matrix']
                for row in dynmat_data:
                    vals = np.reshape(row, (-1, 2))
                    dynmat.append(vals[:, 0] + vals[:, 1] * 1j)
                dynmat = np.array(dynmat)

                eigvals, eigvecs, = np.linalg.eigh(dynmat)
                q = data["phonon"][i]["q-position"]

                #This should technically always be true since we only
                #ran it at a single q-point.
                if np.allclose(q, [0., 0., 0.]):
                    result["dynmat"] = dynmat
                    result["eigvals"] = eigvals
                    result["eigvecs"] = eigvecs
                    break

            if len(result) < 3:
                msg.err("Could not extract dynamical matrix from qpoints.yaml "
                        "file...")
                return
            
            self._dmatrix = result
        return self._dmatrix
    
    @property
    def bands(self):
        """Returns the DFT-accurate phonon bands in a format that can be
        consumed by the `matdb` interfaces.

        Returns:
            dict: keys are ['q', 'w', 'path', 'Q'], values are the distance along
            the special path (scalar), phonon frequencies at that distance (vector,
            one component for each frequency), q-positions of the special points
            along the paths, and their corresponding distances.
        """
        if self._bands is None:
            from matdb.phonons import from_yaml
            byaml = path.join(self.phonodir, "band.yaml")
            return from_yaml(byaml)
        return self._bands

    @property
    def kpath(self):
        """Returns the materialscloud.org special path in k-space for the seed
        configuration of this database.

        Returns:
            tuple: result of querying the materialscloud.org special path
            service. First term is a list of special point labels; second is the
            list of points corresponding to those labels.
        """
        if self._kpath is None:
            import json
            poscar = path.join(self.phonodir, "POSCAR")
            kcache = path.join(self.phonodir, "kpath.json")
            #We use some caching here so that we don't have to keep querying the
            #server and waiting for an identical response.
            if path.isfile(kcache):
                with open(kcache) as f:
                    kdict = json.load(f)
            else:
                labels, band = _parsed_kpath(poscar)
                kdict = {"labels": labels, "band": band}
                with open(kcache, 'w') as f:
                    json.dump(kdict, f)
            
            self._kpath = (kdict["labels"], kdict["band"])
            
        return self._kpath
    
    def calc_bands(self, recalc=False):
        """Calculates the bands at the special points given by the
        materialscloud.org service.

        Args:
            recalc (bool): when True, recalculate the DOS, even if the
              file already exists.
        """
        bandfile = path.join(self.phonodir, "band.yaml")
        if not recalc and path.isfile(bandfile):
            return

        #We need to create the band.conf file and write the special
        #paths in k-space at which the phonons should be calculated.
        settings = {
            "ATOM_NAME": ' '.join(self.parent.species),
            "DIM": ' '.join(map(str, self.supercell)),
            "MP": ' '.join(map(str, self.grid))
        }

        labels, bands = self.kpath
        bandfmt = "{0:.3f} {1:.3f} {2:.3f}"
        sband = []
        
        for Q in bands:
            sband.append(bandfmt.format(*Q))

        settings["BAND"] = "  ".join(sband)
        settings["BAND_LABELS"] = ' '.join(labels)

        with open(path.join(self.phonodir, "band.conf"), 'w') as f:
            for k, v in settings.items():
                f.write("{} = {}\n".format(k, v))

        from matdb.utility import execute
        sargs = ["phonopy", "-p", "band.conf"]
        xres = execute(sargs, self.phonodir, venv=True)
        if not path.isfile(bandfile):
            msg.err("could not calculate phonon bands; see errors.")

        if len(xres["error"]) > 0:
            msg.std(''.join(xres["error"]))
    
    def calc_DOS(self, recalc=False):
        """Calculates the *total* density of states.

        Args:
            recalc (bool): when True, recalculate the DOS, even if the
              file already exists.
        """
        dosfile = path.join(self.phonodir, "mesh.yaml")
        if not recalc and path.isfile(dosfile):
            return

        #Make sure we have calculated the force sets already.
        self.calc_forcesets(recalc)
        settings = {
            "ATOM_NAME": ' '.join(self.parent.species),
            "DIM": ' '.join(map(str, self.supercell)),
            "MP": ' '.join(map(str, self.grid))
        }
        with open(path.join(self.phonodir, "dos.conf"), 'w') as f:
            for k, v in settings.items():
                f.write("{} = {}\n".format(k, v))

        from matdb.utility import execute
        sargs = ["phonopy", "-p", "dos.conf"]
        xres = execute(sargs, self.phonodir, venv=True)
        if not path.isfile(dosfile):
            msg.err("could not calculate the DOS; see errors.")

        if len(xres["error"]) > 0:
            msg.std(''.join(xres["error"]))
            
    def calc_forcesets(self, recalc=False):
        """Extracts the force sets from the displacement calculations.

        Args:
            recalc (bool): when True, recalculate the force sets, even if the
              file already exists.
        """
        fsets = path.join(self.phonodir, "FORCE_SETS")
        if not recalc and path.isfile(fsets):
            return
        
        #First, make sure we have `vasprun.xml` files in each of the
        #directories.
        vaspruns = []
        for i, folder in self.configs.items():
            vasprun = path.join(folder, "vasprun.xml")
            if not path.isfile(vasprun):
                msg.err("vasprun.xml does not exist for {}.".format(folder))
            else:
                vaspruns.append(vasprun)

        if len(vaspruns) == len(self.configs):
            from matdb.utility import execute
            sargs = ["phonopy", "-f"] + vaspruns
            xres = execute(sargs, self.phonodir, venv=True)

        if not path.isfile(fsets):
            msg.err("Couldn't create the FORCE_SETS:")
        if len(xres["error"]) > 0:
            msg.std(''.join(xres["error"]))
            
    def setup(self, rerun=False):
        """Displaces the seed configuration preparatory to calculating the force
        sets for phonon spectra.

        Args:
            rerun (bool): when True, recreate the folders even if they
              already exist. 
        """
        folders_ok = super(PhononDFT, self).setup()
        if folders_ok and not rerun:
            return

        #We also don't want to setup again if we have the results already.
        if self.ready():
            return

        if not folders_ok:
            from ase.io import write
            from matdb.utility import execute
            write(path.join(self.phonodir, "POSCAR"), self.atoms, "vasp")        
            scell = ' '.join(map(str, self.supercell))
            sargs = ["phonopy", "-d", '--dim="{}"'.format(scell)]
            pres = execute(sargs, self.phonodir, venv=True)

            from os import getcwd, chdir, mkdir, rename
            from glob import glob
            current = getcwd()
            chdir(self.phonodir)

            try:
                from quippy.atoms import Atoms
                for dposcar in glob("POSCAR-*"):
                    dind = int(dposcar.split('-')[1])
                    datoms = Atoms(dposcar, format="POSCAR")
                    self.create(datoms)
            finally:
                chdir(current)

        # Last of all, create the job file to execute the job array.
        self.jobfile(rerun)

    def cleanup(self, recalc=False):
        """Runs post-DFT execution routines to calculate the force-sets and the
        density of states.

        Args:
            recalc (bool): when True, redo any calculations that use the DFT
              outputs to find other quantities.

        Returns:
           bool: True if the database is ready; this means that any other
           databases that rely on its outputs can be run.
        """
        if not super(PhononDFT, self).cleanup():
            return
        
        self.calc_forcesets(recalc)
        self.calc_DOS(recalc)
        return self.ready()

def sample_dos(meshfile, sampling="uniform", nfreqs=100):
    """Samples the DOS to extract frequencies from which modulations can be
    generated.
    
    Args:
        meshfile (str): path to the `mesh.yaml` file that the frequencies and
          q-vectors can be extracted from.
        sampling (str): one of ['uniform', 'sample', 'top'], where the method
          dictates how frequencies are selected from the DOS for the seed
          configuration's phonon spectrum.
        nfreqs (int): number of frequencies to return by sampling the DOS.

    - *uniform*: frequencies are selected uniformly from the list of *unique*
       frequencies in the DOS.
    - *sample*: frequencies are chosen randomly *and* weighted by the q-point
       weight in the BZ and the number of times the frequency shows up.
    - *top*: the top N *unique* frequencies are selected.

    .. note:: Because each atomic degree of freedom produces 3 phonon bands, a
      cell with 4 unique atoms will produce 12 different frequencies. When the
      DOS is sampled, we consider each of these frequencies as independent in
      the overall BZ. Thus, if a 20x20x20 q-point grid is used for sampling in
      the `mesh.yaml` file, then we would have 8,000 * 12 = 96,000 frequencies
      to choose from, each with a corresponding q-vector.

    Returns:
        numpy.ndarray: where each row is a q-vector in reciprocal space
        corresponding to a frequency that was selected using the specified
        sampling method.
    """
    import yaml
    with open(meshfile, 'r') as stream:
        dmesh = yaml.load(stream)
        
    freqs = []
    lookup = {}
    for ph in dmesh["phonon"]:
        #Depending on the type of sampling we do, we are interested in
        #either the mere existing of a frequency or how often it actually
        #appears in the BZ.
        fs = [b["frequency"] for b in ph["band"]]
        q = ph["q-position"]
        w = ph["weight"]
        
        if sampling in ["uniform", "top"]:
            freqs.extend(fs)
        elif sampling == "sample":
            freqs.extend(fs*w)

        for bandi, f in enumerate(fs):
            rf = np.round(f, 6)
            if rf not in lookup:
                lookup[rf] = (bandi, q)

    #Now we can do the actual sampling.
    if sampling == "uniform":
        dfreqs = np.unique(freqs)
        sample = np.random.choice(dfreqs, size=nfreqs)
    elif sampling == "top":
        sfreqs = np.sort(np.unique(freqs))
        sample = sfreqs[-nfreqs:]
    elif sampling == "sample":
        sample = np.random.choice(freqs, size=nfreqs)

    return [lookup[f] for f in np.round(sample, 6)]

def update_phonons(basic):
    """Updates the `basic` phonon settings using the usual defaults. The update
    only happens if the user didn't already specify a value in the config file.

    Args:
        basic (dict): user-specified phonon settings that should be updated to
          include defaults.
    """
    usuals = {
        "mesh": [13, 13, 13],
        "dim": [2, 2, 2]
    }
    for k, v in usuals.items():
        if k not in basic:
            basic[k] = v

def modulate_atoms(db):
    """Generates modulated configurations using the dynamical matrix of the
    :class:`PhononDFT` instance.

    Args:
        db (Database): database with parameters needed to module the atoms.
    """
    #Generating the modulation file. We need to sample the DOS in order to
    #compute that correctly.
    dosfile = path.join(db.base.phonodir, "mesh.yaml")
    qvecs = sample_dos(dosfile, sampling=db.sampling, nfreqs=db.nconfigs)
    conffile = path.join(db.base.phonodir, db.confname)

    modstr = [' '.join(map(str, db.phonons["dim"]))]
    for iq, (bandi, qvec) in enumerate(qvecs):
        mstr = "{0:.7f} {1:.7f} {2:.7f} {3:d} {4:.7f} {5:.7f}"
        if hasattr(db, "_amplitudes"):
            A = db._amplitudes[iq]
        else:
            A = np.random.normal(1, 0.25)*db.amplitude
            
        phi = np.random.uniform(0, 180)
        args = qvec + [bandi, A, phi]
        modstr.append(mstr.format(*args))

    phondict = db.phonons.copy()
    phondict["atom_name"] = ' '.join(db.base.parent.species)
    phondict["modulation"] = ', '.join(modstr)
    with open(conffile, 'w') as f:
        for k, v in phondict.items():
            if isinstance(v, (list, tuple, set)):
                value = ' '.join(map(str, v))
                f.write("{} = {}\n".format(k.upper(), value))
            else:
                f.write("{} = {}\n".format(k.upper(), v))

    from matdb.utility import execute
    sargs = ["phonopy", db.confname]
    xres = execute(sargs, db.base.phonodir, venv=True)
            
class PhononCalibration(Database):
    """Represents a set of modulated sub-configurations of differing amplitude,
    used to determine the maximum modulation amplitude where the force is still
    in the linear regime.

    Args:
        atoms (quippy.atoms.Atoms): seed configuration that will be
          displaced to generate the database.
        root (str): path to the folder where the database directories will
          be stored.
        parent (matdb.database.controller.DatabaseCollection): parent collection
          to which this database belongs.
        incar (dict): specify additional settings for the INCAR file (i.e.,
          differing from, or in addition to those in the global set).
        kpoints (dict): specify additional settings for the PRECALC file (i.e.,
          differing from, or in addition to those in the global set).
        phonons (dict): specifying additional settings for `phonopy`
          configuration files (i.e., differing from, or in addition to those in
          the global set).
        nconfigs (int): the number of different *amplitudes* to try out in
          calibrating.

    .. note:: Additional attributes are also exposed by the super class
      :class:`Database`.

    Attributes:
        name (str): name of this database type relative to the over database
          collection. This is also the name of the folder in which all of its
          calculations will be performed.
        phonons (dict): specifying additional settings for `phonopy`
          configuration files (i.e., differing from, or in addition to those in
          the global set).
        base (PhononDFT): reference database that computed the dynamical matrix
          for the seed configuration.
        confname (str): name of the phonopy configuration file used for the
          modulations in this database.
        amplitudes (dict): of logarithmically-spaced amplitudes to
          modulate the seed configuration with. Keys are the `cid` keys in
          :attr:`configs`.
        outfile (str): path to the `calibration.dat` file that contains the list
          of amplitudes and displacements from the calibration run.
        sampling (str): specifies how the DOS is sampled for this database to
          produce modulated sub-configurations.
    """
    name = "phoncalib"
    confname = "calibrate.conf"
    sampling = "uniform"
    
    def __init__(self, atoms=None, root=None, parent=None,
                 kpoints={}, incar={}, phonons={}, execution={}, nconfigs=10):
        super(PhononCalibration, self).__init__(atoms, incar, kpoints, execution,
                                                path.join(root, self.name),
                                                parent, "C", nconfigs)
        self.base = self.parent.databases[PhononDFT.name]
        self.phonons = phonons
        
        update_phonons(self.phonons)

        #Calculate which amplitudes to use for the calibration based on the
        #number of desired configurations (calibration points).
        self._amplitudes = np.logspace(0, 1.7, nconfigs)
        self.outfile = path.join(self.root, "calibration.dat")

        self.amplitudes = {}
        if len(self.configs) == self.nconfigs:
            for cid in self.configs:
                self.amplitudes[cid] = self._amplitudes[cid-1]
        
    def ready(self):
        """Determines if this database is finished calculating by testing the
        existence of the xyz database file in the root folder.
        """
        return path.isfile(self.outfile)

    def cleanup(self):
        """Extracts the calibration information from the configurations to
        determine the maiximum allowable amplitude to maintain linear force
        regime.

        Returns:
           bool: True if the amplitude calibration is ready.
        """
        if not super(PhononCalibration, self).cleanup():
            msg.warn("cannot cleanup calibration; not all configs ready.")
            return False

        success = self.xyz(config_type="phcalib")
        if not success:
            msg.warn("could not extract the calibration XYZ configurations.")
            return False
        else:
            imsg = "Extracted calibration configs from {0:d} folders."
            msg.okay(imsg.format(len(self.configs)))

        #Read in the XYZ file and extract the forces on each atom in each
        #configuration.
        import quippy
        forces = {}
        failed = 0
        for cid, folder in self.configs.items():
            #Find the mean, *absolute* force in each of the directions. There
            #will only be one atom in the atoms list. If the calculation didn't
            #finish, then we exclude it. This happens for some of the
            #calibration runs if the atoms are too close together.
            try:
                al = quippy.AtomsList(path.join(folder, "output.xyz"))
                forces[cid] = np.mean(np.abs(np.array(al[0].dft_force)), axis=1)
            except:
                failed += 1
                pass

        if failed > 0:
            msg.warn("couldn't extract forces for {0:d} configs.".format(failed))

        if len(forces) > 0:
            fmt = "{0:.7f}  {1:.7f}  {2:.7f}  {3:.7f}\n"
            with open(self.outfile, 'w') as f:
                for cid in forces:
                    A, F = self.amplitudes[cid], forces[cid]
                    f.write(fmt.format(A, *F))
        else:
            msg.warn("no forces available to write {}.".format(self.outfile))

        return len(forces) > 3
    
    def setup(self, rerun=False):
        """Displaces the seed configuration with varying amplitudes so that the
        resulting forces can be calibrated sensibly.

        Args:
            rerun (bool): when True, recreate the folders even if they
              already exist. 
        """
        if super(PhononCalibration, self).setup():
            return

        #We can't module atoms unless the phonon base is ready.
        if not self.base.ready():
            return

        #Don't reproduce the folders if they already exist or we have already
        #computed.
        if self.ready():
            return
        
        modulate_atoms(self)
        
        from os import getcwd, chdir, remove
        from glob import glob
        from quippy.atoms import Atoms
        current = getcwd()
        chdir(self.base.phonodir)

        try:
            for mi, mposcar in enumerate(sorted(list(glob("MPOSCAR-*")))):
                if mposcar == "MPOSCAR-orig":
                    remove(mposcar)
                    continue
                
                cid = int(mposcar.split('-')[1])
                matoms = Atoms(mposcar, format="POSCAR")
                self.create(matoms, cid)
                self.amplitudes[cid] = self._amplitudes[mi]
                #Remove the MPOSCAR file so that the directory isn't polluted.
                remove(mposcar)
        finally:
            chdir(current)
            
        # Last of all, create the job file to execute the job array.
        self.jobfile()

    def infer_amplitude(self):
        """Tries to infer the maximum amplitude that can be used for modulation
        such that the average forces experienced by all atoms in the seed
        configuration's supercell are still in the linear regime.
        """
        #Our approach is to interpolate linearly starting with the two closest
        #points and then moving away one point at a time until the error starts
        #to diverge between the linear interpolation and the actual points.
        if not self.ready():
            return None
        else:
            raise NotImplementedError("Automatic calibration not configured.")
            
class PhononDatabase(Database):
    """Represents a set of displaced configurations where atoms are
    moved, within a supercell, according to phonon eigenmodes.

    Args:
        atoms (quippy.atoms.Atoms): seed configuration that will be
          displaced to generate the database.
        root (str): path to the folder where the database directories will
          be stored.
        parent (matdb.database.controller.DatabaseCollection): parent collection
          to which this database belongs.
        incar (dict): specify additional settings for the INCAR file (i.e.,
          differing from, or in addition to those in the global set).
        kpoints (dict): specify additional settings for the PRECALC file (i.e.,
          differing from, or in addition to those in the global set).
        phonons (dict): specifying additional settings for `phonopy`
          configuration files (i.e., differing from, or in addition to those in
          the global set).
        calibrate (bool): when True, the maximum amplitude possible will be
          selected ensuring that the force is still in the linear regime.
        amplitude (float): amplitude of displacement :math:`A` for eigenmode
          modulation. 
        sampling (str): on of ['uniform', 'sample', 'top'], where the method
          dictates how frequencies are selected from the DOS for the seed
          configuration's phonon spectrum.

    .. note:: Additional attributes are also exposed by the super class
      :class:`Database`.

    Attributes:
        sampling (str): on of ['uniform', 'sample', 'top'], where the method
          dictates how frequencies are selected from the DOS for the seed
          configuration's phonon spectrum.
        supercell (list): of `int`; number of cells in each direction for
          generating the supercell.
        phonodir (str): directory in which all `phonopy` executions take place.
        calibrate (bool): when True, the maximum amplitude possible will be
          selected ensuring that the force is still in the linear regime.
        amplitude (float): amplitude of displacement :math:`A` for eigenmode
          modulation. 
        calibrator (PhononCalibration): instance used to calculate force
          vs. amplitude for the seed configuration.
        name (str): name of this database type relative to the over database
          collection. This is also the name of the folder in which all of its
          calculations will be performed.
        confname (str): name of the phonopy configuration file used for the
          modulations in this database.
    """
    name = "phonons"
    confname = "modulate.conf"

    def __init__(self, atoms=None, root=None, parent=None,
                 kpoints={}, incar={}, phonons={}, execution={}, nconfigs=100,
                 calibrate=True, amplitude=None, sampling="uniform"):
        super(PhononDatabase, self).__init__(atoms, incar, kpoints, execution,
                                             path.join(root, self.name),
                                             parent, "M", nconfigs)
        self.sampling = sampling
        self.calibrate = calibrate

        #Setup a calibrator if automatic calibration was selected.
        if calibrate and amplitude is None:
            self.calibrator = PhononCalibration(atoms, root, parent, kpoints,
                                                incar, phonons, execution, calibrate)
            self.parent.databases[PhononCalibration.name] = self.calibrator
            self.amplitude = self.calibrator.infer_amplitude()
            calibrated = "*calibrated* "
        else:
            self.calibrator = None
            self.amplitude = amplitude
            calibrated = ""

        imsg = "Using {} as modulation {}amplitude for {}."
        msg.info(imsg.format(self.amplitude, calibrated, self.parent.name), 2)

        self.base = self.parent.databases[PhononDFT.name]
        self.phonons = phonons        
        update_phonons(self.phonons)

    def ready(self):
        """Determines if this database is finished calculating by testing the
        existence of the xyz database file in the root folder.
        """
        return (path.isfile(path.join(self.root, "output.xyz")) and
                len(self.configs) == self._nsuccess)

    def cleanup(self):
        """Generates the XYZ database file for all the sub-configs in this
        phonon database.

        Returns:
           bool: True if the database is ready; this means that any other
           databases that rely on its outputs can be run.
        """
        if not super(PhononDatabase, self).cleanup():
            return
        
        return self.xyz(config_type="ph")
    
    def setup(self, rerun=False):
        """Displaces the seed configuration preparatory to calculating the force
        sets for phonon spectra.

        Args:
            rerun (bool): when True, recreate the folders even if they
              already exist. 
        """
        if super(PhononDatabase, self).setup():
            return

        #We can't modulate atoms unless the phonon base is ready.
        if not self.base.ready():
            return

        #We can't module in calibrate mode unless the calibrator is also ready.
        if self.amplitude is None:
            return
        
        modulate_atoms(self)

        from os import getcwd, chdir, remove
        from glob import glob
        from quippy.atoms import Atoms
        current = getcwd()
        chdir(self.base.phonodir)

        from tqdm import tqdm
        try:
            for mi, mposcar in tqdm(enumerate(sorted(list(glob("MPOSCAR-*"))))):
                if mposcar == "MPOSCAR-orig":
                    continue
                
                cid = int(mposcar.split('-')[1])
                matoms = Atoms(mposcar, format="POSCAR")
                self.create(matoms, cid)
                #Remove the MPOSCAR file so that the directory isn't polluted.
                remove(mposcar)
        finally:
            chdir(current)
            
        # Last of all, create the job file to execute the job array.
        self.jobfile()
