Firehose
========

Firehose is an embedded MQTT broker that concentrates
events from services run within a Software Factory
deployment, making it easy for external processes to
consume these events and act upon them.

It is not possible to publish messages on the firehose outside of
the predefined services, however anyone is allowed to subscribe
anonymously to the feed by using the MQTT protocol.

Services supported
------------------

================= ============= ================
  Service           Topic         Source
================= ============= ================
 Gerrit             gerrit        `germqtt`_
 Jenkins [1]_       zuul_jobs     `MQTT notification plugin`_
                                  "firehose-zuul" predefined publisher
 Nodepool           nodepool      `ochlero`_
 Zuul               zuul          `ochlero`_
================= ============= ================ 

.. [1] For jobs managed through the config repository.
.. _germqtt: http://git.openstack.org/cgit/openstack-infra/germqtt/
.. _`MQTT notification plugin`: https://wiki.jenkins-ci.org/display/JENKINS/MQTT+Notification+Plugin
.. _ochlero: https://pypi.python.org/pypi/ochlero

Events published
----------------

Events are published in JSON format. The payload is specific to each event.

Gerrit
......

Every patchset-related events are published.

Jenkins
.......

An event is published whenever a Zuul build ends. It publishes the result of the
build, and the Zuul parameters it was launched with.

Nodepool
........

The following events are published:

* node creation
* node ready
* node ready in Jenkins
* node deleted
* node deleted in Jenkins

Zuul
....

The following events are published:

* Job moved to any pipeline
* Job launched
* Build started
* Build result

Subscribing to events
---------------------

Simple CLI example
..................

The mosquitto project provides a CLI subscriber client that can be used to easily
subscribe to any topic and receive the messages. On debian based distributions it
is included in the **mosquitto-clients** package; on Fedora or CentOS it can be found
in the **mosquitto** package.
For example, to subscribe to every topic on the firehose you would run::

    mosquitto_sub -h firehose.fqdn --topic '#'

You can adjust the value of the topic parameter to make what you're subscribing
to more specific.
