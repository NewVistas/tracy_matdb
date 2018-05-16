 #!/usr/bin/python
from os import path
from matdb import msg

def examples():
    """Prints examples of using the script to the console using colored output.
    """
    from matdb import msg
    script = "MATDB Finder for Groups/Trainers and General Contexts"
    explain = ("Each context has a controller that provides a find() method for"
               "looking up instances within that context. This script provides "
               "a simple interface for finding things.")
    contents = [(("Find hessian databases."), 
                 "matdb_find.py system.yaml -d -p hessian-*/hessian",
                 "The find function uses the format dbname/group/seed")]
    required = ("'matdb.yaml' file with database settings.")
    output = ("")
    details = ("")
    outputfmt = ("")

    msg.example(script, explain, contents, required, output, outputfmt, details)

script_options = {
    "dbspec": {"help": "File containing the database specifications."},
    "-d": {"help": ("When specified, search the database context."),
           "action": "store_true"},
    "-p": {"help": ("Specify the search pattern(s)"), "nargs": '+',
           "required": True}
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
    pdescr = "MATDB Context Finder"
    parser = argparse.ArgumentParser(parents=[base.bparser], description=pdescr)
    for arg, options in script_options.items():
        parser.add_argument(arg, **options)
        
    args = base.exhandler(examples, parser)
    if args is None:
        return

    return args
        
def run(args):
    """Runs the matdb setup and cleanup to produce database files.
    """
    if args is None:
        return

    #No matter what other options the user has chosen, we will have to create a
    #database controller for the specification they have given us.
    from matdb.database import Controller
    cdb = Controller(args["dbspec"])

    if args["d"]:
        msg.info("Database Context Instances")
        msg.info("--------------------------")
        msg.blank()
        for pattern in args["p"]:
            for entry in cdb.find(pattern):
                text = "{} | {} ".format(entry.uuid, entry.root)
                msg.arb(text, [msg.cenum["cwarn"],
                               msg.cenum["cstds"]], '|')
        
if __name__ == '__main__': # pragma: no cover
    run(_parser_options())
