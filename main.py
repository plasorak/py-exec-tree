import executabletrees as ET
from anytree import Node, search
from rich.console import Console
from random import randrange
import time

c = Console()

exectree = ET.loads("top_config.json", c)
wibnodes = []
wibnodes += search.findall_by_attr(exectree, "wib1", name="name")
# wibnodes += search.findall_by_attr(exectree, "wib2", name="name")
# wibnodes += search.findall_by_attr(exectree, "wib3", name="name")
# wibnodes += search.findall_by_attr(exectree, "wib4", name="name")
# print([node.name for node in wibnodes])

def booting_wib(cls, _):
    s = randrange(1,6,1)
    # print(f"{cls.name} responsing to cmd {cls.event.event.name}, now in state {cls.state}, this is going to take {s} sec")
    time.sleep(s)
    # print(f"Finish up booting {cls.name}")
    cls.end_boot()
    # print(f"Finish up booting {cls.name}, now state is {cls.state}")
    return

def boot_wib(cls, _):
    print(f"{cls.name} responding to cmd {cls.event.event.name} (but state is already {cls.state}), this is going to be fast")
    # print(f"Finish up booting {cls.name}, now state is {cls.state}")
    cls.notify_on_success("boot")
    return


def init_wib(cls, _):
    print(f"{cls.name} responding to cmd {cls.event.event.name} (but state is already {cls.state}), this is going to be fast")
    # print(f"Finish up booting {cls.name}, now state is {cls.state}")
    cls.notify_on_success("init")
    return

for wibnode in wibnodes:
    # wibnode.register_command("on_enter_booted", boot_wib)
    wibnode.register_command("on_enter_boot-ing", booting_wib)
    wibnode.register_command("on_enter_initialised", init_wib)

exectree.create_fsms()
exectree.print_status(c)
exectree.print_fsm(c)
exectree.send_command("boot")
time.sleep(10)
exectree.print_fsm(c)
exectree.send_command("init")
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
