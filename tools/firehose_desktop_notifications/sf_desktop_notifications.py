#!/usr/bin/env python

# SF desktop notifications from firehose

import paho.mqtt.client as mqtt
import gi
gi.require_version('Notify', '0.7')  # noqa
from gi.repository import Notify
from gi.repository import GdkPixbuf
import argparse
import logging
import re
import yaml
import json
import sys
import os


LOGGER = logging.getLogger('SF_desktop_notifications')
LOGGER.setLevel(logging.DEBUG)


# Get some icons
NOTIFICATION_ICONS = {}
script_dir = os.path.dirname(__file__)
_heart_red = os.path.join(script_dir, 'icons/heart_red.png')
NOTIFICATION_ICONS['heart_red'] = GdkPixbuf.Pixbuf.new_from_file(_heart_red)
_heart_green = os.path.join(script_dir, 'icons/heart_green.png')
hg = GdkPixbuf.Pixbuf.new_from_file(_heart_green)
NOTIFICATION_ICONS['heart_green'] = hg
_yes = os.path.join(script_dir, 'icons/yes.png')
NOTIFICATION_ICONS['yes'] = GdkPixbuf.Pixbuf.new_from_file(_yes)
_no = os.path.join(script_dir, 'icons/no.png')
NOTIFICATION_ICONS['no'] = GdkPixbuf.Pixbuf.new_from_file(_no)
_cog = os.path.join(script_dir, 'icons/cog.png')
NOTIFICATION_ICONS['cog'] = GdkPixbuf.Pixbuf.new_from_file(_cog)


NOTIFICATION_ICONS['default'] = NOTIFICATION_ICONS['yes']


def flatten_dict(dic):
    newdic = {}
    for key in dic:
        if isinstance(dic[key], dict):
            for _key in dic[key]:
                newdic['%s.%s' % (key, _key)] = dic[key][_key]
        else:
            newdic[key] = dic[key]
    if dic == newdic:
        return newdic
    else:
        return flatten_dict(newdic)


class Filter:
    def __init__(self, topic, keyvals, sf_username,
                 msg_format=None, icon=None,
                 title_format=None):
        self.topic = topic
        self.criterias = {}
        self.sf_username = sf_username
        if not icon or icon not in NOTIFICATION_ICONS:
            self.icon = NOTIFICATION_ICONS['default']
        else:
            self.icon = NOTIFICATION_ICONS[icon]
        if not msg_format:
            self.msg_format = '%r'
        else:
            self.msg_format = msg_format
        if not title_format:
            self.title_format = 'Software Factory'
        else:
            self.title_format = title_format
        for k, v in keyvals.items():
            try:
                v = v.replace('_me_', self.sf_username)
                self.criterias[k] = re.compile(v, re.IGNORECASE)
            except Exception:
                raise Exception("Error parsing regular expression %s" % v)

    def check(self, topic, msg):
        if self.topic not in topic:
            return False
        flat_msg = flatten_dict(msg)
        if not all(k in flat_msg for k in self.criterias):
            LOGGER.debug("missing criterias %s" % [k for k in self.criterias
                                                   if k not in flat_msg])
            return False
        for k in self.criterias:
            value = flat_msg[k].replace('\n', '\t')
            if not self.criterias[k].search(value):
                m = "failing regexp: %r on '%s'" % (self.criterias[k].pattern,
                                                    flat_msg[k])
                LOGGER.debug(m)
                return False
        return True

    def format(self, topic, msg):
        flat_msg = flatten_dict(msg)
        flat_msg.update({'topic': topic})
        return self.title_format % flat_msg, self.msg_format % flat_msg


# Assign a callback for connect
def on_connect(client, userdata, flags, rc):
    LOGGER.info("MQTT: Connected with result code "+str(rc))
    client.subscribe("#")


# Send a notification after a new message has arrived
def on_message(filters):
    def _on_message(client, userdata, msg):
        message = msg.payload + ' \n(Topic: ' + msg.topic + ')'
        LOGGER.debug(message)
        try:
            jmsg = json.loads(msg.payload)
        except:
            LOGGER.error('could not translate %s' % msg.payload)
            return
        n = None
        if not filters:
            Notify.init('Software Factory message')
            n = Notify.Notification.new(
                'Software Factory',
                message)
            n.set_icon_from_pixbuf(NOTIFICATION_ICONS['default'])
            n.set_image_from_pixbuf(NOTIFICATION_ICONS['default'])
            n.show()
            return
        for filter in sorted(filters.keys()):
            LOGGER.debug('checking %s...' % filter)
            if filters[filter].check(msg.topic, jmsg):
                try:
                    title, message = filters[filter].format(msg.topic,
                                                            flatten_dict(jmsg))
                except KeyError as e:
                    LOGGER.debug('[%s] %s missing key %s' % (filter, jmsg, e))
                Notify.init('Software Factory message')
                n = Notify.Notification.new(
                    title,
                    message)
                n.set_icon_from_pixbuf(filters[filter].icon)
                n.set_image_from_pixbuf(filters[filter].icon)
                n.show()
                return
    return _on_message


def main():
    console = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    LOGGER.addHandler(console)

    parser = argparse.ArgumentParser(description="SF desktop notifier")
    parser.add_argument('--config-file', '-c', metavar='/PATH/TO/CONF',
                        help='The path to the configuration file to use.')
    parser.add_argument('--verbose', '-v', default=False, action='store_true',
                        help='Run in debug mode')

    args = parser.parse_args()
    if args.verbose:
        console.setLevel(logging.DEBUG)
    else:
        console.setLevel(logging.INFO)
    if not args.config_file:
        sys.exit('Please provide a configuration file with option -c.')
    if not os.path.isfile(args.config_file):
        sys.exit('%s not found.' % args.config_file)
    with open(args.config_file, 'r') as raw_conf:
        conf = yaml.load(raw_conf)

    broker = conf['host']
    port = conf['port']
    sf_username = conf.get('sf_username')
    filters = {}
    if 'filters' in conf:
        for filter in conf['filters']:
            topic = conf['filters'][filter]['topic']
            keyvals = conf['filters'][filter]
            del keyvals['topic']
            icon = keyvals.get('icon')
            if icon:
                del keyvals['icon']
            msg_format = keyvals.get('notification_message')
            if msg_format:
                del keyvals['notification_message']
            title_format = keyvals.get('notification_title')
            if title_format:
                del keyvals['notification_title']
            filters[filter] = Filter(topic, keyvals, sf_username,
                                     msg_format, icon,
                                     title_format)

    # Setup the MQTT client
    client = mqtt.Client()
    client.connect(broker, port, 60)

    # Callbacks
    client.on_connect = on_connect
    client.on_message = on_message(filters)

    # Loop the client forever
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        LOGGER.info('Manual interruption, bye!')
        sys.exit(2)


if __name__ == '__main__':
    main()
