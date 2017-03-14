#!/bin/bash

export OS_CLOUD=rcip-dev-sf-pre-upgrade

name=$1

for os_command in snapshot volume; do
    if openstack $os_command show $name >/dev/null 2>&1; then
        echo "delete $os_command $name"
        openstack $os_command delete $name >/dev/null 2>&1
    fi
done
