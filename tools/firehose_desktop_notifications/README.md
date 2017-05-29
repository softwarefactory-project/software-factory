# Software Factory Firehose desktop notifications

This script can be used within a GTK desktop environment to display notifications
whenever specific messages appear on the firehose.

## Dependencies

The following libraries are needed:

* paho-mqtt
* pyyaml
* pyGTKObject

The embedded icons come from https://prothemedesign.com/tools/circular-icons/
(released under the GPL).

## Usage

```bash
python sf_desktop_notifications.py -c /path/to/config.yaml
```

## Configuration file

**host** and **port** refer to the Firehose host and port to connect to.

### Filters

Basic filtering can be set in the config file:

```yaml
filters:
  filter_name:
    topic: firehose_topic
    key_from_the_message: regexp_value
    icon: heart_red
```

Possible icon values:

* cog
* yes
* no
* heart_green
* heart_red
