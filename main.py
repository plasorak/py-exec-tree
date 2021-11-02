import executabletrees as ET
from anytree import Node, search
from rich.console import Console
from random import randrange
import time

c = Console()

exectree = ET.loads("top_config.json", c)
wibnodes = []
wibnodes += search.findall_by_attr(exectree, "wib1", name="name")

# There are 2 ways to deal with transitions:
#  -1 Either the transitions are long, and there is a state of the FSM called  "command"+"-ing".
#        In this case, once we are done with the command, we need to "end_"+"command" to move the FSM to the next state
#  -2 Either the transition are short, and the FSM moves to the next state when we call it, but the command may not have finished.

def booting_wib(cls, _):
    '''
    This is what user code would look like for booting the WIBs. Wait from 1 to 6 seconds
    This is an example of long transitions
    '''
    s = randrange(1,6,1)
    time.sleep(s)

    ## Now we are done so we "end_boot()" otherwise the FSM can't go into next stage
    cls.end_boot()
    return

def boot_wib(cls, _):
    '''
    This is an example of a short transition
    We just need to notify
    '''
    time.sleep(2)
    cls.notify_on_success("boot")
    return


def init_wib(cls, _):
    '''
    This is an example of a long transition
    We need to end the state
    '''
    print(f"{cls.name} responding to cmd {cls.event.event.name} (but state is already {cls.state}), this is going to be fast")
    # print(f"Finish up booting {cls.name}, now state is {cls.state}")
    cls.end_init()
    return

def conf_wib(cls, _):
    '''
    This is an example of a short transition
    We just need to notify
    '''
    print(f"{cls.name} responding to cmd {cls.event.event.name} (but state is already {cls.state}), this is going to be fast")
    # print(f"Finish up booting {cls.name}, now state is {cls.state}")
    cls.end_conf()
    return

def start_wib(cls, _):
    '''
    This is an example of a short transition
    We just need to notify
    '''
    print(f"{cls.name} responding to cmd {cls.event.event.name} (but state is already {cls.state}), this is going to be fast")
    # print(f"Finish up booting {cls.name}, now state is {cls.state}")
    cls.notify_on_success("start")
    return

for wibnode in wibnodes: # Now we register
    # wibnode.register_command("on_enter_booted", boot_wib)
    wibnode.register_command("on_enter_boot-ing", booting_wib)
    wibnode.register_command("on_enter_init-ing", init_wib   )
    wibnode.register_command("on_enter_conf-ing", conf_wib   )
    wibnode.register_command("on_enter_started" , start_wib  )

class dfgdsfgad:
    def on_enter_boot(self):
        asdfsdfg


Machine(model: fddsa, )
fddsa.boot()
# AFTER we register, we create the fsm on the tree
exectree.create_fsms()
exectree.print_status(c)
exectree.print_fsm(c)
# sending commands... 
exectree.send_command("boot")
time.sleep(10)
exectree.print_fsm(c)
exectree.send_command("init")
time.sleep(2)
exectree.print_fsm(c)
exectree.send_command("conf")
time.sleep(2)
exectree.print_fsm(c)
exectree.send_command("start")
time.sleep(2)
exectree.print_fsm(c)
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
