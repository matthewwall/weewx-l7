#!/usr/bin/env python
# Copyright 2024 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)
"""
Collect data from Raddy L7 LoRa weather station.

Output from console that is not bound to a sensor cluster:

{"sensor":[
  {
   "title":"Indoor",
   "list":[
     ["Temperature","69.3","F"],
     ["Humidity","38","%"]
   ]},
  {
   "title":"Pressure",
   "list":[
     ["Absolute","30.04","inhg"],
     ["Relative","29.91","inhg"]
   ]}
]}

Output from console that is bound to a sensor cluster:

{"sensor":[{
  "title":"Indoor",
    "list":[
      ["Temperature","68.9","F"],
      ["Humidity","38","%"]
    ]},{
  "title":"Outdoor",
    "list":[
      ["Temperature","61.7","F"],
      ["Humidity","29","%"]
    ]},{
  "title":"Pressure",
    "list":[
      ["Absolute","26.76","inhg"],
      ["Relative","29.84","inhg"]
    ]},{
  "title":"Wind Speed",
    "list":[
      ["Max Daily Gust","5.1","mph"],
      ["Wind","1.1","mph"],
      ["Gust","1.6","mph"],
      ["Direction","123",""],
      ["Wind Average 2 Minute","0.4","mph"],
      ["Direction Average 2 Minute","111",""],
      ["Wind Average 10 Minute","1.3","mph"],
      ["Direction Average 10 Minute","134",""]
    ]},{
  "title":"Rainfall",
    "list":[
      ["Rate","0.0","inch/hr"],
      ["Hour","0.0","inch","43"],
      ["Day","0.0","inch","44"],
      ["Week","0.0","inch","45"],
      ["Month","0.0","inch","46"],
      ["Year","5.72","inch","47"],
      ["Total","10.65","inch","48"]
    ],
    "range":"Range: 0inch to 393.7inch."},{
  "title":"Solar",
    "list":[
      ["Light","261.36","w/"],
      ["UVI","1.2",""]
    ]}
  ],
  "battery":{
    "title":"Battery",
    "list":[
      "All battery are ok"
    ]
  }
}
"""

from __future__ import with_statement
import os
import subprocess
import threading

try:
    # Python 3
    import queue
except ImportError:
    # Python 2:
    import Queue as queue

try:
    import cjson as json
    setattr(json, 'dumps', json.encode)
    setattr(json, 'loads', json.decode)
except (ImportError, AttributeError):
    try:
        import simplejson as json
    except ImportError:
        import json

import weewx.drivers

try:
    # logging for weewx v4+
    import weeutil.logger
    import logging
    log = logging.getLogger(__name__)
    def logdbg(msg):
        log.debug(msg)
    def loginf(msg):
        log.info(msg)
    def logerr(msg):
        log.error(msg)
except ImportError:
    # logging for weewx v3
    import syslog
    def logmsg(level, msg):
        syslog.syslog(level, 'l7: %s: %s' %
                      (threading.currentThread().getName(), msg))
    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)
    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)
    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)

DRIVER_NAME = 'L7'
DRIVER_VERSION = '0.1'

def loader(config_dict, _):
    return L7Driver(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return L7ConfigurationEditor()


DEFAULT_ADDR = '192.168.5.1'

class L7ConfigurationEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[L7]
    # This section is for the Raddy L7 LoRa weather station
    driver = user.l7
    # IP address of the weather station console
    addr = %s
""" % DEFAULT_ADDR

    def prompt_for_settings(self):
        settings = dict()
        print "Specify the IP address of the weather station console"
        settings['addr'] = self._prompt('addr', DEFAULT_ADDR)
        return settings


class L7Driver(weewx.drivers.AbstractDevice):

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        addr = stn_dict.get('addr', DEFAULT_ADDR)
        loginf('station address: %s' % addr)
        self._sensor_map = stn_dict.get('sensor_map', DEFAULT_MAP)
        self.collector = L7Collector(addr)
        self.collector.startup()

    def closePort(self):
        self.collector.shutdown()

    @property
    def hardware_name(self):
        return DRIVER_NAME

    def genLoopPackets(self):
        while True:
            try:
                data = self.collector.queue.get(True, 10)
                logdbg('data: %s' % data)
                pkt = self.data_to_packet(data)
                logdbg('packet: %s' % pkt)
                if pkt:
                    yield pkt
            except queue.Empty:
                pass

    def data_to_packet(self, data):
        packet = dict()
        packet['dateTime'] = int(time.time() + 0.5)
        packet['usUnits'] = weewx.METRIC
        for n in self._sensor_map:
            label = self._find_match(self._sensor_map[n], data.keys())
            if label:
                packet[n] = data.get(label)
        return packet


class L7Collector(object):
    queue = queue.Queue()
    def __init__(self, addr=DEFAULT_ADDR):
        self._addr = addr
    def startup(self):
        pass
    def shutdown(self):
        pass


def main():
    import argparse
    import sys

    description = """Direct interface to the %s driver.
""" % DRIVER_NAME

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--version', action='store_true',
                        help='display driver version')
    parser.add_argument('--debug', action='store_true',
                        help='display diagnostic information while running')
    parser.add_argument('--addr', default=DEFAULT_ADDR,
                        help='address of the weather station console')

    args = parser.parse_args()

    if args.version:
        print("l7 driver version %s" % DRIVER_VERSION)
        sys.exit(0)

#    syslog.openlog('l7', syslog.LOG_PID | syslog.LOG_CONS)
#    syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))
#    if args.debug:
#        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))

    collector = L7Collector(args.addr)
    collector.startup()
    while True:
        try:
            data = collector.queue.get(True, 10)
            logdbg('data: %s' % data)
            pkt = data_to_packet(data)
            logdbg('packet: %s' % pkt)
            if pkt:
                print(pkt)
        except queue.Empty:
            pass
    collector.shutdown()


if __name__ == '__main__':
    main()
