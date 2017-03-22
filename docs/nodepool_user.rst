.. _nodepool-user:

Nodepool configuration
======================

Build scripts, images and labels definition are done via the config repository of SF.

By default SF provides a build script called "base.sh" that is the minimal script to run
by Nodepool in order to prepare a working slave and attach it to Jenkins. Two yaml files
are also provided: labels.yaml and images.yaml.

Nodepool first needs to prepare snapshots of declared images before being able to spawn
Jenkins slaves. The following is the process to define an image for Nodepool.

Clone the config repository of SF from Gerrit and modify the file "config/nodepool/nodepool.yaml"
as below.

.. code-block:: yaml

    labels:
      - name: bare-centos-7
        image: bare-centos-7
        min-ready: 1
        providers:
          - name: default

    providers:
      - name: default
        cloud: cloud-name-from-sfconfig.yaml
        images:
          - name: bare-centos-7
            base-image: CentOS-7-cloud
            username: centos
            setup: base.sh
            min-ram: 2048


Basically here nodepool will start a VM on the provider you defined in sfconfig.yaml using
the Glance image "CentOS-7-cloud". Nodepool will connect on it using the username "centos".
Then Nodepool will use "base.sh" to configure the VM.
Finally Nodepool will snapshot and destroy the VM.

Note the "CentOS-7-cloud" image must be already available in Glance.

Above we tell Nodepool to spawn at least one slave on the default provider from the
"bare-centos-7" image snapshot. The slave will be identified via the label "bare-centos-7".

By committing this change on the config repository, SF will perform a file syntax
validation and will allow you (or not) to merge the change (by CR +2 and W +2). Once merged
the new configuration of nodepool will be loaded by the Nodepool service. And you should
see on the declared provider the following:

 * A VM is spawned (with the term "template" in its name)
 * After the run of the base.sh script, the VM is snapshoted
 * The VM is destroyed and the snapshot is available
 * At least one VM is spawned based on the snapshot
 * A floating ip is attached to the new VM
 * The new VM is attached to Jenkins as slave

Using the config repository, SF users can provide custom build scripts for Jenkins slave
as well as custom labels for their jobs' needs. As already said slaves are destroyed after
each job. This can have some advantages:

 * A clean VM for each job
 * A job have full system access (root)

CLI
===

The CLI utility *sfmanager* can be used to interact with nodes that are currently running. The
following actions are supported:

* list nodes, with status information like id, state, age, ip address, base image
* hold a specific node, so that it is not destroyed after it has been consumed for a job
* add a SSH public key to the list of authorized keys on the node, allowing a user to do
  remote operations on the node
* schedule a node for deletion
* list available images

These operations might require specific authorizations defined within SF's policy engine.

You can refer to sfmanager's contextual help for more details.
