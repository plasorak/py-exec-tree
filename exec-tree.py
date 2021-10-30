from anytree import NodeMixin, RenderTree
import types
from transitions import Machine
from transitions.extensions import GraphMachine
import inspect
from rich.console import Console
from rich.table import Table
import multiprocessing as mp
import os
import signal
from threading import Thread
from queue import Queue
import threading as th
from random import randrange
import time

states = ["none",
          "booting", "booted",
          "initialising", "initialised",
          "configuring", "configured",
          "starting", "started",
          "pausing", "paused",
          "resuming",
          "stopping",
          "scrapping",
          "terminating"]

transitions = [
    {'trigger': 'boot'         , 'source': 'none'        , 'dest': 'booting'     },
    {'trigger': 'end_boot'     , 'source': 'booting'     , 'dest': 'booted'      },
    {'trigger': 'init'         , 'source': 'booted'      , 'dest': 'initialising'},
    {'trigger': 'end_init'     , 'source': 'initialising', 'dest': 'initialised' },
    {'trigger': 'conf'         , 'source': 'initialised' , 'dest': 'configuring' },
    {'trigger': 'end_conf'     , 'source': 'configuring' , 'dest': 'configured'  },
    {'trigger': 'start'        , 'source': 'configured'  , 'dest': 'starting'    },
    {'trigger': 'end_start'    , 'source': 'starting'    , 'dest': 'started'     },
    {'trigger': 'pause'        , 'source': 'started'     , 'dest': 'pausing'     },
    {'trigger': 'end_pause'    , 'source': 'pausing'     , 'dest': 'paused'      },
    {'trigger': 'resume'       , 'source': 'paused'      , 'dest': 'resuming'    },
    {'trigger': 'end_resume'   , 'source': 'resuming'    , 'dest': 'started'     },
    {'trigger': 'stop'         , 'source': 'started'     , 'dest': 'stopping'    },
    {'trigger': 'end_stop'     , 'source': 'stopping'    , 'dest': 'configured'  },
    {'trigger': 'scrap'        , 'source': 'configured'  , 'dest': 'scrapping'   },
    {'trigger': 'end_scrap'    , 'source': 'scrapping'   , 'dest': 'initialised' },
    {'trigger': 'terminate'    , 'source': 'initialised' , 'dest': 'terminating' },
    {'trigger': 'end_terminate', 'source': 'terminating' , 'dest': 'none'        },
]

def transition_with_intermediate(cls, _):
    trigger = cls.event.event.name
    print(f"Trigger was {trigger}")
    
    if isinstance(cls, DAQApp):
        s = randrange(1,6,1)
        print(f"Booting {cls.name} now in state {cls.state}, this is going to take {s} sec")
        time.sleep(s)
        # if randrange(10) > 5:
        #     print(f"Something weird with {cls.name}, couldn't finish booting transition")
        #     return
        
        finalisor = getattr(cls, "end_"+trigger, None)
        finalisor()
        print(f"Finish up booting {cls.name}, now state is {cls.state}")
        return
    
    if not cls.children:
        return
    
    still_to_exec = []
    for child in cls.children:
        still_to_exec.append(child)
        child.send_command(trigger)
        
    timeout=30
    for _ in range(timeout):
        print(f"still to exec on {cls.name}: {len(still_to_exec)} processes")
        for child in cls.children:
            
            print(f"{child.name} thinks {child.last_successful_cmd} is his last successful cmd, last sent cmd {trigger}")
            if child in still_to_exec and child.last_successful_cmd == "end_"+trigger:
                print(f"chuking {child.name}")
                still_to_exec.remove(child)
                
        if len(still_to_exec) == 0:
            break
        time.sleep(1)
        
    if len(still_to_exec) > 0:
        print("Shit hit the fan")
        return
    finalisor = getattr(cls, "end_"+trigger, None)
    finalisor()

    
def notify_on_success(cls, _):
    trigger = cls.event.event.name
    print(f"notifying that {cls.name}.{trigger} was successful")
    cls.last_successful_cmd = trigger


    
def FSMFactory(model):
    for state in states:
        if state[-3:]=="ing":
            function_name = 'on_enter_'+state
            setattr(model, function_name, transition_with_intermediate.__get__(model))
        else:
            function_name = 'on_enter_'+state
            setattr(model, function_name, notify_on_success.__get__(model))
    machine = Machine(model=model, states=states, initial="none", auto_transitions=False, send_event=True)
    
    for transition in transitions:
        machine.add_transition(transition["trigger"], transition["source"], transition["dest"], before="set_environment")
    return machine

    
class DAQNode(NodeMixin):
    def set_environment(self, event):
        self.event = event
    
    def __init__(self, name:str, parent=None, children=None):
        self.name = name
        self.parent = parent
        if children:
            self.children = children
        self.machine = FSMFactory(self)
        self.last_successful_cmd = None
    
        
        self.is_included = True
        self.command_queue = Queue()
        self.command_executor_thread = Thread(target=self._execute_cmd_worker)
        self.command_executor_thread.start()
        

    def print_status(self, console:Console=None) -> int:
        table = Table(title=f"apps")
        table.add_column("name", style="blue")
        table.add_column("state", style="magenta")
        table.add_column("consistent")
        table.add_column("included", style="magenta")

        for pre, _, node in RenderTree(self):
            state = node.state if node.state[-3:] != "ing" else "[yellow]"+node.state+"[/yellow]"
            error = "yes" if node.is_consistent() else "[red]no[/red]"
            included = "yes" if node.is_included else "no"
            table.add_row(
                pre+node.name,
                state,
                error,
                included
            )

        console.print(table)
        
    def is_consistent(self):
        for child in self.children:
            if child.is_included:
                if not child.is_consistent():
                    return False
            
                if self.state != child.state:
                    return False

        return True
        
    def send_command(self, command):
        self.command_queue.put(command)
        
    def _execute_cmd_worker(self):
        while True:
            time.sleep(0.1)
            command = self.command_queue.get()
            if command:
                if command == "terminate": break
                else:
                    cmd = getattr(self, command, None)
                    if not cmd:
                        raise RuntimeError(f"I don't know of {command}")
                    print(f"Executing {self.name}.{command}")
                    cmd()
        
class DAQApp(DAQNode):
    def __init__(self, name:str, parent=None):
        super().__init__(name, parent)
        
    def is_consistent(self): return True



top = DAQNode(name="np04_vst")
s0  = DAQNode(name="daq"  , parent=top)
s0b = DAQApp (name="felix", parent=s0)
s0a = DAQApp (name="hsi"  , parent=s0)
s0c = DAQApp (name="tpg"  , parent=s0)
s0d = DAQApp (name="ru"   , parent=s0)
s1  = DAQNode(name="wibs", parent=top)
s1a = DAQApp (name="wibctrl0", parent=s1 )
s1b = DAQApp (name="wibctrl1", parent=s1 )
s1c = DAQApp (name="wibctrl2", parent=s1 )
s1d = DAQApp (name="wibctrl3", parent=s1 )

top.print_status(Console())
graphs = GraphMachine(model=top, states=states, transitions=transitions, initial="none")
top.get_graph().draw('my_state_diagram.png', prog='circo')
print("done drawing")

for cmd in [("boot","booted"),
            ("init","initialised"),
            ("conf", "configured"),
            ("start", "started"),
            ("stop", "configured"),
            ("scrap", "intialised"),
            ("terminate", "none")]:
    top.send_command(cmd[0])
    while(top.state != cmd[1]):
        time.sleep(1)
        top.print_status(Console())

exit(0)
