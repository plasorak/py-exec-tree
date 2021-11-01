from anytree import NodeMixin, RenderTree
import json
import copy
from transitions import Machine
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
    '''
    A class that holds all the FSM configuration stored on each node
    '''
    def __init__(self, config_json):
        self.config = config_json
        self.included = None
        self.initial = None # first state for the FSM
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
    '''
    A class to send command to the node
    '''
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
    '''
    A node that is just sending commands to its children nodes
    '''
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
        ## Annoyingly, this needs to be called _after_ the callbacks on_enter_blabla have been registered,
        ## so it can't go in the ctor
        self.fsm = FSMFactory(self, self.fsm_config)

        if self.children:
            for child in self.children:
                child.create_fsms()


    def _set_environment(self, event):
        ## A callback before the transition is executed
        ## So that we know which command has been sent in the on_enter_* method
        self.event = event


    def quit(self):
        ## Somehow I can't move this to the __del__?
        ## I don't know how to delete an anytree properly
        self.console.log(f"Killing me softly... {self.name}")
        self.command_sender.stop()
        for child in self.children:
            child.quit()


    def notify_on_success(self, command):
        ## This one is for the quick commands
        ## TODO merge the 2 methods: _notify_on_success is for the long transitions
        self.last_successful_cmd = command


    def print_fsm(self, console:Console=None):
        ## Some helper function on the FSM, to printout what we are allowed to do

        # If we are in between states, bail
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
                if self.last_successful_cmd and len(self.last_successful_cmd)>4 and self.last_successful_cmd[:4]=="end_":
                    last=self.last_successful_cmd[4:]
                else:
                    last=self.last_successful_cmd

                # Highlights the last command that was executed
                if transitions_in[i]["trigger"] == last:
                    ### Any way to make a better arrow?
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
        ## Usual status
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
        ## Fills the consistent flag (are my children in the same state as me?)
        for child in self.children:
            if child.fsm_config.included:
                if not child.is_consistent():
                    return False

                if self.state != child.state:
                    return False

        return True

    def send_command(self, command):
        ## Use the command_sender to send commands
        self.command_sender.add_command(command)


class ExecLeaf(ExecNode):
    '''
    A node that is can execute command, it can't have children, these are applications
    '''
    
    def __init__(self, name:str, parent=None, fsm_config=None, console=None):
        super().__init__(name=name, parent=parent, fsm_config=fsm_config, console=console)

    def register_command(self, name, method):
        ## A method to register the user's callbacks
        setattr(self, name, method.__get__(self))

    def is_consistent(self):
        ## Since I can't have children, I'm always consistent
        return True


def _construct_tree(config:dict, mother, console):
    ## Typical tree creation recursive function.
    ## All the leafs (without children) are ExecLeafs
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
    '''
    Load json string to the full blown tree+fsms
    '''
    
    config = json.loads(config)

    top = list(config.keys())
    if len(top)!= 1:
        raise RuntimeError("JSon should have exactly 1 key")
    top=top[0]

    fsm_config = copy.deepcopy(config[top])
    
    if "children" in fsm_config:
        # chucking the children nodes for the fsm configuration
        del fsm_config["children"]

    console.log(f"Creating topnode {top}")
    topnode = ExecNode(name=top, fsm_config=config[top], console=console)
    console.log(f"Constructing tree from {top}")
    _construct_tree(config[top], topnode, console)


    # A bit of useful printout for debugging
    for pre, _, node in RenderTree(topnode):
        console.print(f"{pre}{node.name}")

    return topnode


def loads(in_file:str, console):
    '''
    Load json file to the full blown tree+fsms
    '''
    print(f"Loading {in_file}")
    config = open(in_file, "r").read()
    return load(config, console)


def _transition_with_interm(cls, _):
    '''
    An internal function that is used in ExecNode, when the transition take some time
    '''
    trigger = cls.event.event.name # command name

    if len(trigger)>=4 and trigger[0:4] == "end_":
        return
    
    if not cls.children: # "that should never happen"
        raise RuntimeError(f"{cls.name} doesn't have children to send commands to")

    still_to_exec = []
    for child in cls.children:
        cls.console.log(f"{cls.name} is sending '{trigger}' to {child.name}")
        # Just a quick check that the user has defined the callback, similar to the one in pytransition
        # Otherwise, the transitions never timeout
        mname = "on_enter_"+trigger+"-ing"
        if not hasattr(child, mname):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")
        if not inspect.ismethod(getattr(child, mname)):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")

        ## TODO add order here!!
        still_to_exec.append(child) # a record of which children still need to finish their task
        child.send_command(trigger) # send the commands

    timeout=30 ## TODO: specify timeout in cfg
    for _ in range(timeout):
        for child in cls.children:

            if child in still_to_exec and child.last_successful_cmd == "end_"+trigger:
                still_to_exec.remove(child) # Bin this child that is done
                
        if len(still_to_exec) == 0: # if all done, continue
            break 
        time.sleep(1)

    if len(still_to_exec) > 0:
        cls.console.log(f"Shit hit the fan... {cls.name} can't {trigger} {[child.name for child in still_to_exec]}")
        return

    # Initiate the transition on this node to say that we have finished
    finalisor = getattr(cls, "end_"+trigger, None)
    finalisor()

    
def _transition_no_interm(cls, _):
    trigger = cls.event.event.name # command name

    if not cls.children: # "that should never happen"
        raise RuntimeError(f"{cls.name} doesn't have children to send commands to")

    still_to_exec = []
    for child in cls.children:
        cls.console.log(f"{cls.name} is sending '{trigger}' to {child.name}")
        ## Pfffff to get the callback name, we need to get the transition's destination...
        ## Probably better way to do that
        dest=""
        for t in child.fsm_config.transitions:
            if t["trigger"] == trigger:
                dest = t["dest"]
                break
        if dest == "":
            raise RuntimeError(f"No transition found for {trigger} on {child.name}")
        mname = "on_enter_"+dest
        # Just a quick check that the user has defined the callback, similar to the one in pytransition
        # Otherwise, the transitions never timeout
        if not hasattr(child, mname):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")
        if not inspect.ismethod(getattr(child, mname)):
            raise RuntimeError(f"{child.name} doesn't have {mname} registered")

        ## TODO add order here!!
        still_to_exec.append(child) # a record of which children still need to finish their task
        child.send_command(trigger) # send the commands
        
    timeout=30  ## TODO: specify timeout in cfg
    for _ in range(timeout):
        for child in cls.children:
            if child in still_to_exec and child.last_successful_cmd == trigger:
                still_to_exec.remove(child) # Bin this child that is done

        if len(still_to_exec) == 0:
            break
        time.sleep(0.1) # TODO different from the _transition_with_interm which is a confusing

    if len(still_to_exec) > 0:
        cls.console.log(f"Shit hit the fan... {cls.name} can't {trigger} {[child.name for child in still_to_exec]}")
        return

    ## Direclty notify
    cls.notify_on_success(trigger)

def _notify_on_success(cls, _):
    '''
    This one is a automated callback for the long transitions
    '''
    trigger = cls.event.event.name
    cls.last_successful_cmd = trigger


def FSMFactory(model, config=None):
    '''
    Construct an FSM from the config and the parent
    '''
    
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
            # we need to loop over transitions, because if they are long, new states are added
            my_transitions = config.transitions
            for transition in my_transitions:
                name = transition["trigger"]+"-ing"
                
                if long_transitions or transition.get("conf") == "long":
                    transition_state_to_add.append(name)
                    # add these new states
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
                    # ... and remove the old direct transitions
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
        # now we do evertything again but with the parent node's FSM
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
                # ... more of the same
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

    ## Smart merging... most of this could be done with dict.update?
    if len(my_states) == 0:
        my_states = parent_states + transition_state_to_add
        config.states = parent_states
    else:
        my_states += transition_state_to_add

    for state in my_states:
        # incredibly ugly code that is meant to:
        if not isinstance(model, ExecLeaf):
            if len(state)>=4 and state[-4:]=="-ing":
                # use the correct callback on the execnode
                function_name = 'on_enter_'+state
                setattr(model, function_name, _transition_with_interm.__get__(model))
            elif not state in states_after_long_transition:
                # ... depending if it's long or short
                function_name = 'on_enter_'+state
                setattr(model, function_name, _transition_no_interm.__get__(model))

        if len(state)>=4 and state[-4:]=="-ing":
            # .. and  with the automated exit 
            function_name = 'on_exit_'+state
            setattr(model, function_name, _notify_on_success.__get__(model))

    if my_initial == "": # declaring a initial state
        my_initial = my_states[0]
        config.initial = my_initial

    # Finally the macchinetta, after that model (i.e. the node) becomes an FSM (with only states)
    machine = Machine(model=model, states=my_states, initial=my_initial, auto_transitions=False, send_event=True)

    ## now we can add our transitions
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
        machine.add_transition(transition["trigger"], transition["source"], transition["dest"], before="_set_environment")

    # And we return the machine, although I'm not sure we actually need to
    return machine
