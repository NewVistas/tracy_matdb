"""Tests the controller and database collection objects methods
directly. These tests rely on the `./tests/Pd` directory, which has the model
outputs that temporary directories will be compared to.
"""
import numpy as np
from os import path
import pytest
from matdb.utility import reporoot, relpath
from matdb.atoms import AtomsList
import six

def _mimic_vasp(folder, xroot, prefix="W.1"):
    """Copies a `vasprun.xml` and `OUTCAR ` output files from the given folder into
    the execution directory to mimic what VASP would have done.

    Args:
        folder (str): path to the folder where the model files are stored.
        xroot (str): path to the root folder where the config steps are stored.
    """
    from matdb.utility import chdir
    from glob import glob
    from os import path
    from matdb.utility import symlink

    files = ["vasprun.xml", "OUTCAR"]

    with chdir(folder):
        for vaspfile in files:
            pattern = vaspfile + "__*"
            for dft in glob(pattern):
                name, config = dft.split("__")
                xpath = path.join(xroot, path.join(*config.split("_")), prefix)
                #We want to make some testing assertions to ensure that the
                #stubs ran correctly.
                #Bypass checking the DynMatrix subfolder
                if "DynMatrix" in xpath:
                    continue
                assert path.isfile(path.join(xpath, "CONTCAR"))
                assert path.isfile(path.join(xpath, ".matdb.module"))
                target = path.join(xpath, name)
                symlink(target, path.join(folder, dft))

@pytest.fixture()
def Pd(tmpdir):
    from matdb.utility import relpath, copyonce
    from matdb.database import Controller
    from os import mkdir, symlink, remove, path

    target = relpath("./tests/Pd/matdb.yml")
    dbdir = str(tmpdir.join("pd_db"))
    mkdir(dbdir)
    copyonce(target, path.join(dbdir, "matdb.yml"))
    target = path.join(dbdir,"matdb")
    
    #We need to copy the POSCAR over from the testing directory to the temporary
    #one.
    from shutil import copy
    POSCAR = relpath("./tests/Pd/POSCAR")
    mkdir(path.join(dbdir,"seed"))
    copy(POSCAR, path.join(dbdir,"seed","Pd"))
    # the source file `matdb.yml` linked to might be gone, that left `matdb.yml` not an valid "file"
    # we need to get rid if it anyway
    try:
        remove("matdb.yml")
    except:
       pass
    symlink("{}.yml".format(target),"matdb.yml")
    
    result = Controller("matdb", dbdir)
    remove("matdb.yml")
    result = Controller(target, dbdir)
    return result

@pytest.fixture()
def Pd_copy(tmpdir):
    from matdb.utility import relpath, copyonce
    from matdb.database import Controller
    from os import path, remove, mkdir

    target = relpath("./tests/Pd/matdb_copy.yml")
    dbdir = str(tmpdir.join("pd_db_copy"))
    mkdir(dbdir)
    copyonce(target, path.join(dbdir, "matdb.yml"))
    target = path.join(dbdir,"matdb")

    from shutil import copy
    POSCAR = relpath("./tests/Pd/POSCAR")

    if path.isfile("matdb_copy.yml"):
        remove("matdb_copy.yml")
        
    result = Controller(target, dbdir)

    mkdir(path.join(dbdir,"seed"))
    copy(POSCAR, path.join(dbdir, "seed", "Pd"))
    result = Controller(target, dbdir)
    return result

@pytest.fixture()
def Pd_split(tmpdir):
    from matdb.utility import relpath, copyonce
    from matdb.database import Controller
    from os import mkdir, path

    target = relpath("./tests/Pd/matdb_split.yml")
    dbdir = str(tmpdir.join("pd_db_splits"))
    mkdir(dbdir)
    copyonce(target, path.join(dbdir, "matdb.yml"))
    target = path.join(dbdir,"matdb")

    from shutil import copy
    POSCAR = relpath("./tests/Pd/POSCAR")
    mkdir(path.join(dbdir,"seed"))
    copy(POSCAR, path.join(dbdir,"seed","Pd-1"))
    copy(POSCAR, path.join(dbdir,"seed","Pd-2"))
    copy(POSCAR, path.join(dbdir,"seed","Pd-3"))
    copy(POSCAR, path.join(dbdir,"seed","Pd-4"))
    copy(POSCAR, path.join(dbdir,"seed","Pd-5"))

    result = Controller(target, dbdir)
    return result

def test_Pd_setup(Pd, Pd_copy):
    """Makes sure the initial folders were setup according to the spec.
    """
    #raise Exception("RAWR")
    Pd.setup()
    modelroot = path.join(Pd.root, "Manual","phonon.manual","Pd")
    #import pdb; pdb.set_trace()
    assert Pd["Manual/phonon/Pd/"].root == modelroot
    
    #The matdb.yml file specifies the following database:
    dbs = ["Manual/phonon.manual/Pd/"]
    #Each one should have a folder for: ["hessian", "modulations"]
    #On the first go, the modulations folder will be empty because the DFT
    #calculations haven't been performed yet. However, hessian should have DFT
    #folders ready to go.
    folders = {
        "__files__": ["compute.pkl","jobfile.sh"],
        "S1.1": {
            "__files__": ["INCAR", "POSCAR", "POTCAR", "PRECALC", "KPOINTS"]
        }
    }

    from matdb.utility import compare_tree
    for db in dbs:
        dbfolder = path.join(Pd.root, db)
        compare_tree(dbfolder, folders)

    #import pdb; pdb.set_trace()
    #Now we will test some of the border cases of the database __init__ method
    Pd_copy.setup()

    db = "Manual/phonon.manual/Pd"
    dbfolder = path.join(Pd_copy.root, db)
    compare_tree(dbfolder, folders)

def test_steps(Pd):
    """Tests compilation of all steps in the database.
    """
    assert Pd.steps() == ['manual/phonon']
    Pd.setup()
    steps = sorted(['manual/phonon/Pd'])
    assert Pd.steps() == steps
    
    seqs = sorted(['Pd'])
    assert Pd.sequences() == seqs

def test_find(Pd):
    """Tests the find function and the __getitem__ method with pattern matching.
    """
    Pd.setup()
    steps = Pd.find("manual/phonon")
    model = ['phonon']
    assert model == [s.parent.name for s in steps]
    model = [path.join(Pd.root,'Manual/phonon.manual')]
    assert sorted(model) == sorted([s.root for s in steps])
   
    steps = Pd.find("*/phonon")
    model = ['phonon']
    assert model == [s.parent.name for s in steps]
    model = [path.join(Pd.root,'Manual/phonon.manual')]
    assert model == [s.root for s in steps]

    steps = Pd.find("manual/phonon/Pd")
    model = ['manual']
    assert model == [s.parent.name for s in steps]
    model = [path.join(Pd.root,'Manual/phonon.manual/Pd')]
    assert model == [s.root for s in steps]

    steps = Pd.find("phonon")
    model = ['phonon']
    assert model == [s.name for s in steps]
    model = [Pd.root]
    assert model == [s.root for s in steps]

    steps = Pd.find('*')
    model = ['phonon']
    assert model == [s.name for s in steps]
    model = [Pd.root]
    assert model == [s.root for s in steps]

    steps = Pd.find("manual/phonon/Pd/S1.1")
    model = [('phonon','manual')]
    assert model == [(s.parent.parent.name,s.name) for s in steps]
    model = [path.join(Pd.root,'Manual/phonon.manual/Pd')]
    assert model == [s.root for s in steps]
                             
    # test uuid finding.
    assert all([Pd.find(s.uuid)==s for s in steps])

    # test the __getitem__ method
    model = 'phonon'
    modelroot = path.join(Pd.root,'Manual/phonon.manual')
    group = Pd["manual/phonon"]
    assert group.parent.name == model
    assert group.root == modelroot

    model = 'manual'
    modelroot = path.join(Pd.root,'Manual/phonon.manual/Pd')
    group = Pd["manual/phonon/Pd"]
    assert group.parent.name == model
    assert group.root == modelroot

    group = Pd["manual/phonon/Pd/S1.1"]
    assert group.parent.name == model
    assert group.root == modelroot

    group = Pd["enumeration/phonon"]
    assert group == None

def test_execute(Pd, capsys):
    """Tests the execute and extract methods 
    """
    from os import path
    from matdb.utility import relpath, chdir
    from matdb.msg import verbosity

    verbosity = 2

    Pd.status()
    output = capsys.readouterr()
    status = "ready to execute 0/0; finished executing 0/0;"
    assert status in output.out

    # test to ensure execute prints error message if ran before setup
    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID":"1"})
    output = capsys.readouterr()
    status = "Group phonon.manual is not ready to execute yet, or is already executing. Done."
    assert status in output.out

    # Run setup and status to make sure the staus output is correct
    Pd.setup()
    Pd.status()
    output = capsys.readouterr()
    status = "ready to execute 1/1; finished executing 0/1;"
    assert status in output.out

    # Execute the jobfile and test an incomplete OUTCAR to check the status
    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID":"1"})
    folder = path.join(reporoot, "tests", "data", "Pd", "manual_recover")
    _mimic_vasp(folder, Pd.root,"S1.1")

    Pd.status(True)
    busy_status = "Pd./Manual/phonon.manual/Pd/S1.1"
    output = capsys.readouterr()
    assert busy_status in output.out

    #now use a complete OUTCAR and test the status again
    folder = path.join(reporoot, "tests", "data", "Pd", "manual")
    _mimic_vasp(folder,Pd.root,"S1.1")
    
    Pd.status()
    output = capsys.readouterr()
    status = "ready to execute 1/1; finished executing 1/1;"
    assert status in output.out

    # Run exctract and test to see if the status is correct
    Pd.extract()
    Pd.status()
    output = capsys.readouterr()
    status = "ready to execute 1/1; finished executing 1/1;"
    assert status in output.out

    # Run extract again to make sure the atoms.h5 files are no rewritten
    Pd.extract()

def test_recovery(Pd):
    """Tests the rerun on unfinshed jobs
    """
    from os import path
    from matdb.utility import symlink, chdir
    from glob import glob

    Pd.setup()
    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID":"1"})

    files = ["vasprun.xml", "OUTCAR"]
    folder = path.join(reporoot, "tests", "data", "Pd", "manual_recover")
    with chdir(folder):
        for vaspfile in files:
            pattern = vaspfile + "__*"
            for dft in glob(pattern):
                name, config = dft.split("__")
                xpath = path.join(Pd.root, path.join(*config.split("_")), "S1.1")
                target = path.join(xpath, name)
                symlink(target, path.join(folder, dft))

    Pd.extract()
    
    Pd.recover(True)
    assert path.isfile(path.join(Pd.root,"Manual","phonon.manual","Pd","recovery.sh"))
    assert path.isfile(path.join(Pd.root,"Manual","phonon.manual","Pd","failures"))

    folder = path.join(reporoot, "tests", "data", "Pd", "manual")
    _mimic_vasp(folder,Pd.root,"S1.1")
    Pd.recover(True)
    assert not path.isfile(path.join(Pd.root,"Manual","phonon.manual","Pd","recovery.sh"))
    assert not path.isfile(path.join(Pd.root,"Manual","phonon.manual","Pd","failures"))

def test_hash(Pd):
    """Tests the hash_dbs and verify_hash methods
    """
    from os import path, chdir
    Pd.setup()
    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID":"1"})
    folder = path.join(reporoot, "tests", "data", "Pd", "manual")
    _mimic_vasp(folder,Pd.root,"S1.1")
    db_hash = Pd.hash_dbs()
    assert Pd.verify_hash(db_hash)

def test_finalize(Pd):
    """ Test the finalize function in the controller module
    """
    from os import path
    Pd.setup()
    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID":"1"})
    folder = path.join(reporoot,"tests","data","Pd","manual")
    _mimic_vasp(folder,Pd.root,"S1.1")

    Pd.extract()
    Pd.split()
    Pd.finalize()

    from matdb.io import load_dict_from_h5
    from matdb import __version__
    import h5py

    str_ver = []
    for item in __version__:
        str_ver.append(str(item))
    mdb_ver = ".".join(str_ver)
    target = path.join(Pd.root, "final_{}.h5".format(mdb_ver))
    with h5py.File(target, "r") as hf:
        loaded_final = load_dict_from_h5(hf)
    assert path.isfile(target)

def test_split(Pd_split):
    """ Test the split function in the controller object
    """
    from os import path
    Pd_split.setup()
    Pd_split.execute(env_vars={"SLURM_ARRAY_TASK_ID":"1"})
    folder = path.join(reporoot,"tests","data","Pd","manual_split")
    _mimic_vasp(folder,Pd_split.root,"S1.1")

    Pd_split.extract()
    Pd_split.split()

    for dbname, db in Pd_split.collections.items():
        for s, p in db.splits.items():
            tfile = path.join(db.train_file(s).format(s))
            hfile = path.join(db.holdout_file(s).format(s))
            sfile = path.join(db.super_file(s).format(s))

            tal = AtomsList(tfile)
            hal = AtomsList(hfile)
            sal = AtomsList(sfile)

            assert len(tal) == int(np.ceil(5*p))
            assert len(hal) == int(np.ceil((5-len(tal))*p))
            assert len(sal) == 5-len(tal)-len(hal)
    
def test_Pd_hessian(Pd):
    """Tests the `niterations` functionality and some of the standard
    methods of the class on simple Pd.

    """
    from os import remove
    Pd.setup()
    
    #Test the status, we should have some folder ready to execute.
    Pd.status()
    Pd.status(busy=True)

    #Test execution command; this uses stubs for all of the commands that would
    #be executed.
    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID": "1"})
    folder = path.join(reporoot, "tests", "data", "Pd", "recover")
    _mimic_vasp(folder, Pd.root)

    #Now that we have vasp files, we can queue recovery. The recover
    #`vasprun.xml` files that we linked to are not complete for all the
    #structures (on purpose).
    Pd.recover()
    recoveries = ["Manual/phonon/Pd"]

    for rkey in recoveries:
        assert path.isfile(path.join(Pd[rkey].root, "recovery.sh"))

    Pd.execute(env_vars={"SLURM_ARRAY_TASK_ID": "1"}, recovery=True)
    folder = path.join(reporoot, "tests", "data", "Pd", "manual")
    _mimic_vasp(folder,Pd.root,"S1.1")
    remove(path.join(Pd[rkey].root, "recovery.sh"))

    #Now that we have recovered vasp files, we can queue a *second*
    #recovery. All but one of the `vasprun.xml` files that we linked to are
    #complete for all the structures. This test that we can recover and execute
    #multiple times in order.
    Pd.recover()
    okay = ["Manual/phonon/Pd"]
    for rkey in okay:
        assert not path.isfile(path.join(Pd[rkey].root, "recovery.sh"))
