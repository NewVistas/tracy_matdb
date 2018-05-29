"""Implements the classes needed for the Tracy calculations, i.e.,
those calculations that will be added to the Tracy compute queue.
"""
from datetime import datetime
from os import path
from random import seed, uniform
import json
import abc

from matdb.database.utility import make_primitive
from matdb.descriptors import soap
from matdb.calculators.basic import AsyncCalculator
from matdb.calculators import Qe


class Tracy(AsyncCalculator):
    """Represents a calculator that will be submitted to the Tracy queue.

    Args:
    Attributes:
        role (str): The role of the user, i.e., "Cheif Scientist".
    """
    key = "tracy"
    
    def __init__(self, folder, role=None, notifications=None,
                 group_preds=None, contract_preds=None, ecommerce=None,
                 contract_priority=None, max_time=None, min_flops=None,
                 min_mem=None, ncores=None, max_net_lat=None, min_ram=None):

        # If this folder has already been submitted then there will be
        # a file containing the contract number in it. We want to read
        # this in so we can check it's status later.
        self.folder = folder
        if path.isfile(path.join(folder, "contract.txt")):
            with open(path.join(folder, "contract.txt"), "r") as f:        
                self.contract_id = f.readline().strip()
        else:
            self.contract_id = None
            
        if path.isfile(path.join(folder, "post_print.txt")):
            with open(path.join(folder, "post_print.txt")):
                self.after_print = f.readline().strip()
        else:
            self.after_print = None

        # All these will be set by either input or latter methods
        self.contract_type = None
        self.input_dict = None
        self.ecommerce_priority = ecommerce if ecommerce is not None else 1
        self.group_preds = group_preds
        self.contract_preds = contract_preds
        self.contract_priority = contract_priority if contract_priority is not None else 1
        self.sys_specs = {"max_time": max_time, "min_flops": min_flops, "min_mem": min_mem,
                          "ncores": ncores, "min_ram": min_ram, "max_net_lat": max_net_lat}

    def _compress_struct(self, atoms):
        """Compresess the input atoms object so that it is ready to be sent to
        the queue.
        
        Args:
            atoms (matdb.Atoms): the atoms object for the calculaton.
        
        Returns:
            A dictionary of the compressed structure that the
            decompression algorithm can unpack.
        """
        a_vecs, pos, types, hnf = make_primitive(self.atoms)

        result = {"a": [list(a) for a in a_vecs],
                  "b": [list(b) for b in pos],
                  "t": [self.type_map[i] for i in types],
                  "h": [hnf[0][0], hnf[1][0], hnf[1][1], hnf[2][0], hnf[2][1], hnf[2][2]]}
        return result

    @abc.abstractmethod
    def get_input_dict(self):
        """Constructs the input dictionary from the files written.
        """
        pass
    
    def _get_source(self):
        """Determines the priority of the source submitting the calculations.
        """
        source_dict = {"Chief Scientist": 10,
                       "Scientist": 9,
                       "Intern": 8,
                       "ASPEN": 7,
                       "Enumerated": 3}

        if self.role in source_dict.keys():
            return source_dict[self.role]
        else:
            raise ValueError("The source {0} is not recognized. Cannot assign "
                             "priority.".format(self.role))
    

    def prep_submit(self, folder):
        """Submits the job to the authetication code before being sent to the queue.
        """
        self.get_input_dict()
        package = {}
        package["MatDB ID"] = self.atoms.uuid
        package["MatDB Group ID"] = self.atoms.group_uuid
        # package["Source ID"] = Get this from Josh's scripit
        package["Source"] = self._get_source()
        package["Contract Type"] = self.contract_type
        package["Input Dictionary"] = self.input_dict
        package["Input Dictionary"]["cryst"] = self._compress_struct(self.atoms)
        package["Before fingerprint"] = soap(self.atoms)
        package["Contract Priority"] = self.contract_priority
        package["eCommerce Priority"] = self.ecommerce
        package["Maximum Processing Time"] = self.sys_specs["max_time"]
        package["Minimum FLOPS"] = self.sys_specs["min_flops"]
        package["Minimum RAM"] = self.sys_specs["min_ram"]
        package["Minimum Storage"] = self.sys_specs["min_mem"]
        package["Number of Cores"] = self.sys_specs["ncores"]
        package["Maximum Network Latency"] = self.sys_specs["max_net_lat"]
        
        if self.can_execute(self, self.folder):
            package["Date Ready"] = datetime.now()
        job_reqs = self._get_job_reqs()
        for k,v in job_needs.values():
            package[k] = v
            
        if self.group_preds is not None:
            package["Group Predecessors"] = self.group_preds
        if self.contract_preds is not None:
            package["Contract Predecossors"] = self.contract_preds

        target = path.join(folder, "submission.json")

        with open(target, "w+") as f:
            json.dump(package, f)
        

    def can_extract(self, folder):
        """Returns `True` if the calculation has been completed and the data
        is ready for extraction.
    
        Args:
            folder (str): the directory to the folder.
        """
        # Here we need to do a query of the endpoint to determine if
        # the calculation has been completed.
        pass

    def is_executing(self, folder):
        """Returns `True` if the calculation is being performed on the queue.
        """
        # Here we need to da a querry of the endpoint to determin if
        # the calculation has been started.
        pass

    def to_dict(self):
        """Converts the arguments of the calculation to a dictionary.
        """
        results = {}
        return results        
        
class Tracy_QE(Tracy, Qe):
    """Represents a DFT calculation that will be submitted to the Tracy queue.

    Args:
        atoms (matdb.Atoms): configuration to calculate using QE.
        folder (str): path to the directory where the calculation should take
          place.
        contr_dir (str): The absolute path of the controller's root directory.
        ran_seed (int or float): the random seed to be used for this calculator.
        kwargs (dict): a dictionary of the kwargs to be passed to the queue.

    Attributes:
        input_data (dict): A dictionary of the keywords and args needed to perform
          the calculations, using the ASE format.
    
    """

    key = "tracy_qe"
        
    def __init__(self, atoms, folder, contr_dir, ran_seed, *args, **kwargs):
        
        self.contract_type = 1
        QE_input = kwargs["calcargs"]
        tracy_input = kwargs["tracy"]
        self.ran_seed = ran_seed
        self.contr_dir = contr_dir
        self.folder = folder
        self.atoms = atoms

        if self.ran_seed is not None:
            seed(self.ran_seed)            

        Qe.__init__(self, atoms, folder, contr_dir, ran_seed, **QE_input)
        Tracy.__init__(self, folder, **tracy_input)

    def _check_potcar(self):
        """We don't construct the potetial files on the user's end so we don't
        actuall want to do any checking.
        """
        pass

    def write_input(self, folder):
        """Writes the input to a folder.
        
        Args:
            folder (str): the path to the folder for this calculation.
        """

        Qe.write_input(folder)
        self.prep_submit(folder)

    def get_input_dict(self):
        """Reads in the input file to a dictionary.
        """
        self.input_dict = {}
        self.type_map = {}
        skip_until_next_key == False
        k_val = None
        with open(path.join(self.folder, "espresso.pwi"), "r") as f:
            for line in f:
                if "&" in line:
                    key = line.strip()[1:]
                    skip_until_next_key == False
                elif line.strip().lower() == "atomic_species":
                    key = "atomic_species"
                    skip_until_next_key == False
                elif line.strip().split()[0].lower() == "k_points":
                    key = "k_points"
                    k_val = line.strip().split()[1]
                    skip_until_next_key == False
                elif line.strip().split()[0].lower() in ["cell_paramaters", "atomic_positions"]:
                    skip_until_next_key = True
                elif not skip_until_next_key:
                    if "=" in line:
                        sub_key, val = line.strip().split("=")
                        if sub_key == "psuedo_dir":
                            continue
                        self.input_dict[key][sub_key] = val
                    elif line.strip() == "/":
                        continue
                    elif k_val is not None and key == "k_points":
                        self.input_dict[key][k_val] = line.strip()
                    elif key == "atomic_species":
                        species = line.strip().split()[0]
                        if species not in self.type_map.keys():
                            self.type_map[species] = len(self.type_map.keys())
                            
                        self.input_dict[key][self.type_map[species]] = uniform(0, 100)
                    else: #pragma: no cover
                        msg.warn("Could no process line {0} of file "
                                 "{1}".format(line, path.join(self.folder, "espresso.pwi")))
                    
                if key not in input_dict.keys():
                    self.input_dict[key] = {}

    def can_execute(self, folder):
        """Returns True if the specified file is ready to be submitted to the queue.
        
        Args:
            folder (str): the path to the folder.
        """
        qe_ready = Qe.can_execute(folder)
        sub_ready = path.isfile(path.join(folder,"submission.json"))
        return qe_ready and sub_ready
                    
    def extract(self, folder):
        """Extracts the results from the returned data package.
        """
        # Waiting on Andrew for this part
        pass
        
