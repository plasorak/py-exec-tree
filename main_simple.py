import simpleExecTree as ET
from anytree import Node, search
import threading
from rich.console import Console
from random import randrange
import time

c = Console()

exectree = ET.loads("top_config_simple.json", c)
wnodes = []
wnodes += search.findall_by_attr(exectree, "wib1", name="name")
wnodes += search.findall_by_attr(exectree, "wib2", name="name")
wnodes += search.findall_by_attr(exectree, "wib3", name="name")

# There are 2 ways to deal with transitions:
#  -1 Either the transitions are long, and there is a state of the FSM called  "command"+"-ing".
#        In this case, once we are done with the command, we need to "end_"+"command" to move the FSM to the next state
#  -2 Either the transition are short, and the FSM moves to the next state when we call it, but the command may not have finished.

class WIBNode(ET.ExecLeaf):
    def __init__(self, name:str, parent=None, fsm_config=None, console=None):
        super().__init__(name=name, parent=parent,
                         fsm_config=fsm_config,
                         console=console)
    
    def user_on_enter_boot_ing(self):
        print("Sane WIBNode user code!")
        time.sleep(1)
        print("Sane WIBNode user code DONE!")

class WIBBuggyNode(ET.ExecLeaf):
    def __init__(self, name:str, parent=None, fsm_config=None, console=None):
        super().__init__(name=name, parent=parent,
                         fsm_config=fsm_config,
                         console=console)
    
    def user_on_enter_boot_ing(self):
        print("Buggy WIBNode user code!")
        raise RuntimeError("whatnot")
        print("Buggy WIBNode user code DONE!")

class WIBSlowNode(ET.ExecLeaf):
    def __init__(self, name:str, parent=None, fsm_config=None, console=None):
        super().__init__(name=name, parent=parent,
                         fsm_config=fsm_config,
                         console=console)
    
    def user_on_enter_boot_ing(self):
        print("Slow WIBNode user code!")
        time.sleep(300)
        raise RuntimeError("whatnot")
        print("Slow WIBNode user code DONE!")

wibs = []
wnodes[0].quit()
wnodes[1].quit()
wnodes[2].quit()
WIBNode     (wnodes[0].name+"real", wnodes[0].parent, wnodes[0].fsm_config.config_json, wnodes[0].console)
WIBBuggyNode(wnodes[1].name+"real", wnodes[1].parent, wnodes[1].fsm_config.config_json, wnodes[1].console)
WIBSlowNode (wnodes[2].name+"real", wnodes[2].parent, wnodes[2].fsm_config.config_json, wnodes[2].console)
wnodes[0].parent = None
wnodes[1].parent = None
wnodes[2].parent = None

# AFTER we register, we create the fsm on the tree
exectree.create_fsms()
exectree.print_status(c)
exectree.print_fsm(c)
# sending commands... 
exectree.send_command("boot")
for _ in range(30):
    time.sleep(0.4)
    exectree.print_status(c)
# exectree.send_command("init")
time.sleep(10)
exectree.print_status(c)
# exectree.print_fsm(c)
# exectree.send_command("conf")
# time.sleep(2)
# exectree.print_fsm(c)
# exectree.send_command("start")
# time.sleep(2)
# exectree.print_fsm(c)
exectree.quit()
# time.sleep(2)
# exectree.send_command("conf")
# time.sleep(2)
# exectree.print_fsm(c)
# time.sleep(2)
# exectree.send_command("start")
# time.sleep(2)
# exectree.print_fsm(c)
# time.sleep(2)
# exectree.print_status(c)
# exectree.print_fsm(c)
# exectree.quit()
