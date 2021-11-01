from anytree import NodeMixin, RenderTree
import json
import copy
from transitions import Machine
# from core import Machine
from transitions.extensions import GraphMachine
import inspect
from rich.segment import Segment
from rich.console import Console
from rich.table import Table
import os
import signal
import threading
from queue import Queue
import threading as th
import time
    
class FSMConfig():
    def __init__(self, config_json):
        self.config = config_json
        self.included = None
        self.initial = None
        self.transitions = None
        self.transition_conf = None
        self.states = None
        self.state_conf = None
        if not config_json: return
        self.included = config_json.get("included")
        self.initial = config_json.get("initial")
        self.transitions = config_json.get("transitions")
        self.transition_conf = config_json.get("transition-conf")
        self.states = config_json.get("states")
        self.state_conf = config_json.get("state-conf")

class CommandSender(threading.Thread):
    STOP="RESPONSE_QUEUE_STOP"


    def __init__(self, node):
        threading.Thread.__init__(self, name=f"command_sender_{node.name}")
        self.node = node
        self.queue = Queue()


    def add_command(self, cmd):
        self.queue.put(cmd)


    def run(self):
        while True:
            command = self.queue.get()
            if command == self.STOP:
                break
            if command:
                cmd = getattr(self.node, command, None)
                if not cmd:
                    raise RuntimeError(f"ERROR: {self.node.name}: I don't know of '{command}'")
                self.node.console.log(f"{self.node.name} Ack: executing '{command}'")
                cmd()
                self.node.console.log(f"{self.node.name} Finished '{command}'")


    def stop(self):
        self.queue.put_nowait(self.STOP)
        self.join()

    
class ExecNode(NodeMixin):
    def set_environment(self, event):
        self.event = event


    def __init__(self, name:str,
                 fsm_config=None, parent=None, children=None, console=None):
        self.console = console
        self.name = name
        self.parent = parent
        if children:
            self.children = children
        self.last_successful_cmd = None
        self.command_sender = CommandSender(self)
        self.command_sender.start()
        self.fsm_config = FSMConfig(fsm_config)


    def create_fsms(self):
        self.fsm = FSMFactory(self, self.fsm_config)

        if self.children:
            for child in self.children:
                child.create_fsms()

    def quit(self):
        self.console.log(f"Killing me softly... {self.name}")
        self.command_sender.stop()
        for child in self.children:
            child.quit()

    def notify_on_success(self, command):
        self.last_successful_cmd = command

    def print_fsm(self, console:Console=None):

        if len(self.state)>4 and self.state[-4:] == "-ing":
            self.console.print(f"Can't send command, node is {self.state}")
            return
        
        table = Table(title=f"{self.name} commands")
        table.add_column("Previous",justify='left')
        table.add_column("Current",justify='center')
        table.add_column("Next",justify='left')
        transitions_in = []
        transitions_out = []
        now_state = self.state
        for transition in self.fsm_config.transitions:
            if transition['dest']   == now_state:
                transitions_in .append(transition)
            if transition['source'] == now_state:
                transitions_out.append(transition)

        n_t_in, n_t_out = len(transitions_in), len(transitions_out)
        n_lines = max(n_t_in, n_t_out)

        for i in range(n_lines):
            text = []
            if i<n_t_in:
                ### Any way to make a better arrow?
                if self.last_successful_cmd and len(self.last_successful_cmd)>4 and self.last_successful_cmd[:4]=="end_":
                    last=self.last_successful_cmd[4:]
                else:
                    last=self.last_successful_cmd
                
                if transitions_in[i]["trigger"] == last:
                    text += ["[blue]"+transitions_in[i]["source"]+"[/blue]──[[green]"+transitions_in[i]["trigger"]+"[/green]]──>" ]
                else:
                    text += ["[blue]"+transitions_in[i]["source"]+"[/blue]──\["+transitions_in[i]["trigger"]+"]──>" ]
            else: 
                text += ["", ""]
                
            if i+1==int((n_lines+1)/2):
                text += ["[magenta]"+now_state+"[/magenta]"]
            else:
                text += [""]
            
            if i<n_t_out:
                text += ["──\["+transitions_out[i]["trigger"]+"]──>[blue]"+transitions_out[i]["dest"]+"[/blue]"]
            else: 
                text += ["", ""]
            table.add_row(*text)
        console.print(table)


    def print_status(self, console:Console=None):
        table = Table(title=f"apps")
        table.add_column("name", style="blue")
        table.add_column("state", style="magenta")
        table.add_column("consistent")
        table.add_column("included", style="magenta")

        for pre, _, node in RenderTree(self):
            state = node.state if node.state[-3:] != "ing" else "[yellow]"+node.state+"[/yellow]"
            error = "yes" if node.is_consistent() else "[red]no[/red]"
            included = "yes" if node.fsm_config.included else "no"
            table.add_row(
                pre+node.name,
                state,
                error,
                included
            )

        console.print(table)

    def is_consistent(self):
        for child in self.children:
            if child.fsm_config.included:
                if not child.is_consistent():
                    return False
            
                if self.state != child.state:
                    return False

        return True

    def send_command(self, command):
        self.command_sender.add_command(command)


class ExecLeaf(ExecNode):
    def __init__(self, name:str, parent=None, fsm_config=None, console=None):
        super().__init__(name=name, parent=parent, fsm_config=fsm_config, console=console)


    def register_command(self, name, method):
        # print(f"Registering {name} on the {self.name}")
        setattr(self, name, method.__get__(self))
        
    def is_consistent(self):
        return True


def _construct_tree(config:dict, mother, console):
    if not ("children" in config):
        return
    
    for child_name, value in config["children"].items():
        if isinstance(value, dict):
            child = ExecNode(name=child_name, parent=mother, fsm_config=value, console=console)
            _construct_tree(value, child, console)
        elif isinstance(value, str):
            child = ExecLeaf(name=child_name, parent=mother, fsm_config=None, console=console)
        else:
            raise RuntimeError(f"ERROR processing the tree {child_name}: {value} I don't know what that's supposed to mean?")


def load(config:dict, console):
    config = json.loads(config)

    top = list(config.keys())
    if len(top)!= 1:
        raise RuntimeError("JSon should have exactly 1 key")
    top=top[0]
    
    fsm_config = copy.deepcopy(config[top])
    
    if "children" in fsm_config:
        del fsm_config["children"]
    console.log(f"Creating topnode {top}")
    topnode = ExecNode(name=top, fsm_config=config[top], console=console)
    console.log(f"Constructing tree from {top}")
    _construct_tree(config[top], topnode, console)
    for pre, _, node in RenderTree(topnode):
        console.print(f"{pre}{node.name}")

    return topnode


def loads(in_file:str, console):
    print(f"Loading {in_file}")
    config = open(in_file, "r").read()
    return load(config, console)


def _transition_with_interm(cls, _):
    trigger = cls.event.event.name
    
    if len(trigger)>=4 and trigger[0:4] == "end_":
        return
    
    if not cls.children:
        return
    
    still_to_exec = []
    for child in cls.children:
        cls.console.log(f"{cls.name} is sending '{trigger}' to {child.name}")
        mname = "on_enter_"+trigger+"-ing"
        if not hasattr(child, mname):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")
        if not inspect.ismethod(getattr(child, mname)):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")
            
        still_to_exec.append(child)
        child.send_command(trigger)
        
    timeout=30
    for _ in range(timeout):
        for child in cls.children:
            
            if child in still_to_exec and child.last_successful_cmd == "end_"+trigger:
                
                still_to_exec.remove(child)
                
        if len(still_to_exec) == 0:
            break
        time.sleep(1)

    if len(still_to_exec) > 0:
        cls.console.log(f"Shit hit the fan... {cls.name} can't {trigger} {[child.name for child in still_to_exec]}")
        return
    
    finalisor = getattr(cls, "end_"+trigger, None)
    finalisor()
    
def _transition_no_interm(cls, _):
    trigger = cls.event.event.name
    # print(f"{cls.name} Trigger was {trigger}")
    
    if not cls.children:
        return
    
    still_to_exec = []
    for child in cls.children:
        cls.console.log(f"{cls.name} is sending '{trigger}' to {child.name}")
        dest=""
        for t in child.fsm_config.transitions:
            if t["trigger"] == trigger:
                dest = t["dest"]
                break
        if dest == "":
            raise RuntimeError(f"No transition found for {trigger} on {child.name}")
        mname = "on_enter_"+dest
        if not hasattr(child, mname):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")
        if not inspect.ismethod(getattr(child, mname)):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")
            

        still_to_exec.append(child)
        child.send_command(trigger)
        
    timeout=30
    for _ in range(timeout):
        # print(f"Still to exec on {cls.name}: {len(still_to_exec)} processes")
        for child in cls.children:
            
            # print(f"Child: {child.name} thinks {child.last_successful_cmd} is his last successful cmd, last sent cmd {trigger}")
            if child in still_to_exec and child.last_successful_cmd == trigger:
                # print(f"Chuking {child.name} from the waiting list.")
                still_to_exec.remove(child)
                
        if len(still_to_exec) == 0:
            break
        time.sleep(0.1)

    if len(still_to_exec) > 0:
        cls.console.log(f"Shit hit the fan... {cls.name} can't {trigger} {[child.name for child in still_to_exec]}")
        return
    cls.notify_on_success(trigger)

def _notify_on_success(cls, _):
    trigger = cls.event.event.name
    cls.last_successful_cmd = trigger


def FSMFactory(model, config=None):
    my_states = []
    my_state_conf = ''
    my_transitions = []
    my_transition_conf = ''
    my_initial = ''
    my_included = None
    
    transition_state_to_add = []
    long_transition_to_add = []
    long_transition_to_remove = []
    states_after_long_transition = []
    
    if config:
        if config.transition_conf:
            long_transitions = "long" in config.transition_conf

        if config.transitions:
            my_transitions = config.transitions
            for transition in my_transitions:
                name = transition["trigger"]+"-ing"

                if long_transitions or transition.get("conf") == "long":
                    transition_state_to_add.append(name)
                    
                    long_transition_to_add.append({
                        "trigger":transition["trigger"],
                        "source": transition["source"],
                        "dest": name
                    })
                    
                    long_transition_to_add.append({
                        "trigger":"end_"+transition["trigger"],
                        "source": name,
                        "dest": transition["dest"]
                    })
                    states_after_long_transition.append(transition["dest"])
                    long_transition_to_remove.append(transition)

        if config.states:
            my_states = config.states
            
        if config.state_conf:
            my_state_conf = config.state_conf

        if config.initial:
            my_initial = config.initial
            
    parent_states = []
    parent_state_conf = ''
    parent_transitions = []
    parent_transition_conf = ''
    parent_initial = ""
    
    if model.parent:
        # print(f"Inheriting config from {model.parent.name}")
        parent_config = model.parent.fsm_config
        if parent_config:
            parent_states = parent_config.states
            parent_state_conf = parent_config.state_conf
            parent_transitions = parent_config.transitions
            parent_transition_conf = parent_config.transition_conf
            
            if parent_transition_conf:
                long_transitions = "long" in parent_transition_conf
            
            for transition in parent_transitions:
                name = transition["trigger"]+"-ing"

                if long_transitions or transition.get("conf") == "long":
                    transition_state_to_add.append(name)
                    
                    long_transition_to_add.append({
                        "trigger":transition["trigger"],
                        "source": transition["source"],
                        "dest": name
                    })
                    
                    long_transition_to_add.append({
                        "trigger":"end_"+transition["trigger"],
                        "source": name,
                        "dest": transition["dest"]
                    })
                    
                    states_after_long_transition.append(transition["dest"])
                    long_transition_to_remove.append(transition)
            parent_initial = parent_config.initial

    ### Merging
    if len(my_states) == 0:
        my_states = parent_states + transition_state_to_add
        config.states = parent_states
    else:
        my_states += transition_state_to_add

    for state in my_states:
        if not isinstance(model, ExecLeaf):
            if len(state)>=4 and state[-4:]=="-ing":
                function_name = 'on_enter_'+state
                setattr(model, function_name, _transition_with_interm.__get__(model))
            elif not state in states_after_long_transition:
                function_name = 'on_enter_'+state
                setattr(model, function_name, _transition_no_interm.__get__(model))
                
        if len(state)>=4 and state[-4:]=="-ing":
            function_name = 'on_exit_'+state
            setattr(model, function_name, _notify_on_success.__get__(model))

    if my_initial == "":
        my_initial = my_states[0]
        config.initial = my_initial


    # print(f"Node {model.name} will have states: {my_states}, initial state: {my_initial}")
    machine = Machine(model=model, states=my_states, initial=my_initial, auto_transitions=False, send_event=True)
    # print(f"Node {model.name} state: {model.state}")

    transition_to_include = []
    if config:
        if config.transitions:
            transition_to_include = config.transitions+long_transition_to_add
            
    if not config.transition_conf:
        config.transition_conf = parent_config.transition_conf
        
    if len(transition_to_include) == 0:
        transition_to_include = model.parent.fsm_config.transitions+long_transition_to_add
        config.transitions = model.parent.fsm_config.transitions
        
    for transition in transition_to_include:
        if transition in long_transition_to_remove: continue
        # print(f"Adding transition {transition['trigger']} on {model.name}")
        machine.add_transition(transition["trigger"], transition["source"], transition["dest"], before="set_environment")

    return machine
