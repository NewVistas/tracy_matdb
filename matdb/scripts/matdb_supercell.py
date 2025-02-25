#Copyright (C) 2019  HALL LABS
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#If you have any questions contact: wmorgan@tracy.com
"""When producing hessians with the Hessian group, a supercell
   needs to be selected. This script streamlines the selection
   process for multiple seeds and sizes.
"""
#!/usr/bin/python
from os import path
from glob import glob
from tqdm import tqdm

from matdb import msg
from matdb.utility import chdir
from matdb.transforms import _get_supers
from matdb.atoms import Atoms

def examples():
    """Prints examples of using the script to the console using colored output.
    """
    from matdb import msg
    script = "MATDB Supercell Generator"
    explain = ("When producing hessians with the Hessian group, a supercell "
               "needs to be selected. This script streamlines the selection "
               "process for multiple seeds and sizes.")
    contents = [(("Select supercells for all the seeds and sizes 32 and 64."), 
                 "matdb_supercell.py * --sizes 32 64",
                 "")]
    required = ("Seed files in the `seed` directory.")
    output = ("")
    details = ("")
    outputfmt = ("")

    msg.example(script, explain, contents, required, output, outputfmt, details)

_script_options = {
    "seeds": {"help": ("File patterns for choosing seeds."),
              "nargs": '+'},
    "--sizes": {"help": ("Target cell sizes to find for."),
                "nargs": '+', "type": int, "required": True},
    }
"""dict: default command-line arguments and their
    :meth:`argparse.ArgumentParser.add_argument` keyword arguments.
"""

def _parser_options():
    """Parses the options and arguments from the command line."""
    #We have two options: get some of the details from the config file,
    import argparse
    import sys
    from matdb import base
    pdescr = "MATDB Supercell Selector"
    parser = argparse.ArgumentParser(parents=[base.bparser], description=pdescr)
    for arg, options in _script_options.items():
        parser.add_argument(arg, **options)
        
    args = base.exhandler(examples, parser)
    if args is None:
        return

    return args

def run(args):
    """Runs the matdb setup and cleanup to produce database files.
    """
    print("matdb  Copyright (C) 2019  HALL LABS")
    print("This program comes with ABSOLUTELY NO WARRANTY.")
    print("This is free software, and you are welcome to redistribute it under "
          "certain conditions.")
    if args is None:
        return

    targets = {}
    with chdir("seed"):
        for pattern in args["seeds"]:
            #Handle the default file type, which is vasp.
            if ':' in pattern:
                fmt, pat = pattern.split(':')
            else:
                fmt, pat = "vasp", pattern
            for filename in glob(pat): 
                targets[filename] = Atoms(filename, format=fmt)

    result = {}
    for filename, at in tqdm(list(targets.items())):
        result[filename] = _get_supers(at, args["sizes"])

    items = [
        ("Filename", 20, "cokay"),
        ("Supercell", 40, "cstds"),
        ("Req.", 6, "cinfo"),
        ("Act.", 6, "cgens"),
        ("rmin", 8, "cerrs"),
        ("pg", 6, "cwarn")
    ]

    msg.blank(2)
    heading = '|'.join(["{{0: ^{0}}}".format(size).format(name)
                        for name, size, color in items])
    msg.arb(heading, [msg.cenum[i[2]] for i in items], '|')
    msg.std(''.join('-' for i in range(len(heading)+1)))
    for filename, hs in result.items():
        for size, hnf in hs.items():
            names = (filename, hnf.hnf.flatten().tolist(), size,
                     hnf.size, hnf.rmin, hnf.pg)
            text = '|'.join(["{{0: <{0}}}".format(item[1]).format(name)
                                for name, item in zip(names, items)])
            msg.arb(text, [msg.cenum[i[2]] for i in items], '|')
        msg.blank(2)
        
    return result
        
if __name__ == '__main__': # pragma: no cover
    run(_parser_options())
