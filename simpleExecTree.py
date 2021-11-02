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
        self.config_json = config_json
        self.included = config_json.get("included")
        self.transitions = config_json.get("transitions")
        self.states = config_json.get("states")
    

class CommandSender(threading.Thread):
    '''
    A class to send command to the node
    '''
    STOP="COMMAND_QUEUE_STOP"

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
        self.command_sender = CommandSender(self)
        self.command_sender.start()
        self.status_receiver_queue = Queue()
        if children:
            self.children = children
            for child in self.children:
                child.status_receiver_queue = self.status_receiver_queue
        self.last_successful_cmd = None
        try:
            self.fsm_config = FSMConfig(fsm_config) if fsm_config else FSMConfig(parent.fsm_config.config_json)
        except Exception as e:
            print(f"Config error: {fsm_config}")
            raise KeyError(f"{self.name} hasn't been specified a proper configuration for FSM (need states and transitions)") from e


    def create_fsms(self):
        self.fsm = FSMFactory(self, self.fsm_config)
        print("Create_fsms on "+self.name)
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


    def print_fsm(self, console:Console=None):
        ## Some helper function on the FSM, to printout what we are allowed to do

        # If we are in between states, bail
        if len(self.state)>4 and self.state[-4:] == "_ing":
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
            state = node.state if node.state[-4:] != "_ing" else "[yellow]"+node.state+"[/yellow]"
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
        
    def is_consistent(self):
        ## Since I can't have children, I'm always consistent
        return True


def _construct_tree(config:dict, mother, console):
    ## Typical tree creation recursive function.
    ## All the leafs (without children) are ExecLeafs
    if not ("children" in config):
        return
    
    for child_name, value in config["children"].items():
        if child_name in ["states", "transitions"]: continue
        
        if isinstance(value, dict):
            fsm_config = copy.deepcopy(value)
            if "children" in fsm_config: del fsm_config["children"]
            child = ExecNode(name=child_name, parent=mother, fsm_config=fsm_config, console=console)
            _construct_tree(value, child, console)
            
        elif isinstance(value, str):
            child = ExecLeaf(name=child_name, parent=mother, fsm_config=None, console=console)
            
        else:
            raise RuntimeError(f"ERROR processing the tree \"{child_name}: {value}\" I don't know what that's supposed to mean?")


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

        ## TODO add order here!!
        still_to_exec.append(child) # a record of which children still need to finish their task
        child.send_command(trigger) # send the commands

    timeout=15 ## TODO: specify timeout in cfg
    failed = []
    for _ in range(timeout):
        if not cls.status_receiver_queue.empty():
            m = cls.status_receiver_queue.get()
            print(f"{cls.name} from queue: {m}")
            response = json.loads(m)
    
            for child in cls.children:
                if response["node"] == child.name:

                    still_to_exec.remove(child)
                    
                    if response["status"] != "success":
                        failed.append(response)
                    break

        if len(still_to_exec) == 0: # if all done, continue
            break 
        time.sleep(1)

    timeout = []
    if len(still_to_exec) > 0:
        cls.console.log(f"Sh*t the f*n... {cls.name} can't {trigger} {[child.name for child in still_to_exec]}")
        timeout = still_to_exec

    if len(failed) > 0:
        for fail in failed:
            cls.console.log(f"Sh*t the f*n... {fail['node']} threw an error {fail['trigger']}: {fail['status']}")

    status = "success"
    if len(timeout)>0:
        status = "timeout"
    if len(failed)>0:
        status = "failed"

    text = json.dumps({
        "state": cls.state,
        "trigger": cls.event.event.name,
        "node": cls.name,
        "timeout": ",".join([c.name for c in timeout]),
        "failed": failed,
        "status": status,
    })
    print(f"{cls.name} sending {text} to end_{cls.event.event.name}")
    # Initiate the transition on this node to say that we have finished
    finalisor = getattr(cls, "end_"+cls.event.event.name, None)
    finalisor(text)


def _on_enter(cls, _):
    user_code = getattr(cls, "user_on_enter_"+cls.state, None)
    finish_up = getattr(cls, "end_"+cls.event.event.name, None)
    
    if not user_code:
        raise RuntimeError(f"You need to define user_on_enter_{cls.state}!")
    
    try:
        user_code()
    except Exception as e:
        text = json.dumps({
            "status": "error running user code",
            "node": cls.name,
            "state": cls.state,
            "trigger": cls.event.event.name,
        })
        ## Hummmm where do we go if the transition failed??
        if cls.parent:
            cls.parent.status_receiver_queue.put(text)
        return
    text = json.dumps({
        "status": "success",
        "node": cls.name,
        "state": cls.state,
        "trigger": cls.event.event.name,
    })
    print(f"{cls.name} sending {text} to end_{cls.event.event.name}")
    finish_up(text)


def _on_exit(cls, eventdata):
    '''
    This one is an automated callback
    '''
    message = eventdata.args[0]
    print(f"{cls.name} _on_exit_{cls.state} (trigger: {eventdata.event.name}) answer: {type(message)}: \"{message}\"")
    if cls.parent:
        cls.parent.status_receiver_queue.put(message)


def FSMFactory(model, config=None):
    '''
    Construct an FSM from the config and the parent
    '''
    long_transition_to_add = []
    transition_state_to_add = []
    states_after_long_transition = []
    long_transition_to_remove = []
    # we need to loop over transitions, because if they are long, new states are added
    for transition in config.transitions:
        name = transition["trigger"]+"_ing"
        
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
        # remove the old direct transitions
        long_transition_to_remove.append(transition)

    ## Smart merging... most of this could be done with dict.update?
    states = config.states + transition_state_to_add

    for state in states:
        if len(state)<4 or state[-4:]!="_ing":
            continue
        
        # incredibly ugly code that is meant to:
        if isinstance(model, ExecLeaf):
            # use the correct callback on the execleaf
            function_name = 'on_enter_'+state
            print(f"{function_name} now in {model.name} from the on_enter_")
            setattr(model, function_name, _on_enter.__get__(model))
        elif isinstance(model, ExecNode):
            # use the correct callback on the execnode
            function_name = 'on_enter_'+state
            print(f"{function_name} now in {model.name} from the transition template")
            setattr(model, function_name, _transition_with_interm.__get__(model))
            

        # .. and  with the automated exit 
        function_name = 'on_exit_'+state
        setattr(model, function_name, _on_exit.__get__(model))

    initial = states[0]

    # Finally the macchinetta, after that model (i.e. the node) becomes an FSM (with only states)
    machine = Machine(model=model, states=states, initial=initial, auto_transitions=False, send_event=True)

    ## now we can add our transitions
    transition_to_include = config.transitions+long_transition_to_add
    
    for transition in transition_to_include:
        if transition in long_transition_to_remove:
            continue
        machine.add_transition(transition["trigger"], transition["source"], transition["dest"], before="_set_environment")

    # And we return the machine, although I'm not sure we actually need to
    return machine
