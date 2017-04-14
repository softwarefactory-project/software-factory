#!/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License")
#
# This script render Heat template based on 'refarch'

import argparse
import os
import yaml

from jinja2 import FileSystemLoader
from jinja2.environment import Environment


def render_template(dest, template, data):
    with open(dest, "w") as out:
        loader = FileSystemLoader(os.path.dirname(template))
        env = Environment(trim_blocks=True, loader=loader)
        template = env.get_template(os.path.basename(template))
        out.write("%s\n" % template.render(data))
    print("[+] Created %s" % dest)


def render():
    arch["arch_raw"] = yaml.dump(arch_raw, default_flow_style=False)
    for host in arch["inventory"]:
        # TODO: remove default m1.medium and find flavor automatically
        host["flavor"] = "m1.medium"
    arch["fixed_ip"] = False
    render_template("%s.hot" % filename, "software-factory.hot.j2", arch)
    # Also generate fixed_ip version
    arch["fixed_ip"] = True
    render_template("%s-fixed-ip.hot" % filename, "software-factory.hot.j2",
                    arch)


def start():
    print "NotImplemented"
    # TODO: create keypair, get network id, upload image, start stack,
    #       wait for completion


def stop():
    print "NotImplemented"


parser = argparse.ArgumentParser()
parser.add_argument("--version")
parser.add_argument("--workspace", default="/var/lib/sf")
parser.add_argument("--domain", default="sftests.com")
parser.add_argument("--arch", default="../../refarch/allinone.yaml")
parser.add_argument("--output")
parser.add_argument("action", choices=[
    "init", "start", "stop", "restart", "render"], default="render")
args = parser.parse_args()

try:
    arch = yaml.load(open(args.arch).read())
    arch_raw = yaml.load(open(args.arch).read())
    filename = args.output
    if not filename:
        filename = "sf-%s" % os.path.basename(
            args.arch).replace('.yaml', '')
    if filename.endswith(".hot"):
        filename = filename[:-4]

except IOError:
    print "Invalid arch: %s" % args.arch
    exit(1)

# Process arch
arch["domain"] = args.domain
for host in arch["inventory"]:
    host["hostname"] = "%s.%s" % (host["name"], args.domain)
    if "gateway" in host["roles"]:
        arch["gateway_ip"] = host["ip"]
    if "install-server" in host["roles"]:
        arch["install"] = host["hostname"]

if args.action == "start":
    start()
elif args.action == "stop":
    stop()
elif args.action == "restart":
    stop()
    start()
elif args.action == "render":
    render()
