Firehose
--------

Firehose is an embedded MQTT broker that concentrates events from services
that are run within your Software Factory deployment.

See the :ref:`Firehose user documentation<firehose-user>` for more details.

Activating Firehose
^^^^^^^^^^^^^^^^^^^

In order to activate firehose within your deployment, simply add the "firehose"
role in your architecture file in /etc/software-factory/arch.yaml then invoke
the sfconfig.py script to apply the configuration changes.

The broker will then be available on firehose.fqdn on port 1883 (standard MQTT port).

Security
^^^^^^^^

Only the service user can publish events to the broker. All other accesses will be
read-only.
