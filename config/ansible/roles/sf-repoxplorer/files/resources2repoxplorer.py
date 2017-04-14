#!/bin/env python

import os
import sys
import yaml
import shutil
import requests

REPOXPLORER_DEFAULT_FILE = "/etc/repoxplorer/default.yaml"

if __name__ == "__main__":
    default = yaml.safe_load(file(REPOXPLORER_DEFAULT_FILE).read())
    resources = requests.get("http://managesf:20001/resources/").json()
    resources = resources['resources']
    for project, data in resources['projects'].items():
        default['projects'][project] = {}
        for repo in data['source-repositories']:
            default['projects'][project][repo] = {'template': 'default'}
    for group, data in resources['groups'].items():
        grp = {}
        grp['description'] = data['description']
        grp['emails'] = dict((member, None) for member in data['members'])
        default['groups'][group] = grp
        
    if len(sys.argv) > 1 and sys.argv[1] == 'apply':
        shutil.copy(REPOXPLORER_DEFAULT_FILE,
                    REPOXPLORER_DEFAULT_FILE + 'save')
        yaml.safe_dump(default,
                       file(REPOXPLORER_DEFAULT_FILE, 'w'),
                       default_flow_style=False)
    else:
        print default
        print
        print "Run with 'apply' as first argument to apply"
