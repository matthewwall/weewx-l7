#!/usr/bin/env python
# Copyright 2024 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)
"""
Collect data from Raddy L7 LoRa weather station.

The station console must be connected to a TCPIP network.  This driver polls
the station for data by making an http request to the station URL.

http://address/client?command=record

There is no time information in the station output, so we use the computer
clock for the timestamp.

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
{
  'sensor': [{
    'title': 'Indoor',
    'list': [
      ['Temperature', '57.4', '°F'],
      ['Humidity', '81', '%']
    ]}, {
    'title': 'Outdoor',
    'list': [
      ['Temperature', '54.7', '°F'],
      ['Humidity', '94', '%']
    ]}, {
    'title': 'Pressure',
    'list': [
      ['Absolute', '29.76', 'inhg'],
      ['Relative', '29.62', 'inhg']
    ]}, {
    'title': 'Wind Speed',
    'list': [
      ['Max Daily Gust', '5.1', 'mph'],
      ['Wind', '1.1', 'mph'],
      ['Gust', '1.6', 'mph'],
      ['Direction', '56', '°'],
      ['Wind Average 2 Minute', '1.3', 'mph'],
      ['Direction Average 2 Minute', '280', '°'],
      ['Wind Average 10 Minute', '1.3', 'mph'],
      ['Direction Average 10 Minute', '5', '°']
    ]}, {
    'title': 'Rainfall',
    'list': [
      ['Rate', '0.07', 'inch/hr'],
      ['Hour', '0.02', 'inch', '43'],
      ['Day', '0.02', 'inch', '44'],
      ['Week', '0.53', 'inch', '45'],
      ['Month', '0.56', 'inch', '46'],
      ['Year', '0.56', 'inch', '47'],
      ['Total', '0.56', 'inch', '48']
     ],
    'range': 'Range: 0inch to 393.7inch.'
    }, {
    'title': 'Solar',
    'list': [
      ['Light', '0.0', 'w/m²'],
      ['UVI', '0.0', '']
    ]}
  ],
  'battery': {
    'title': 'Battery',
    'list': ['All battery are ok']
  }
}
"""

from __future__ import with_statement
import socket
import time

try:
    # python3
    from urllib.request import urlopen
    from urllib.error import URLError, HTTPError
except ImportError:
    # python2
    from urllib2 import urlopen, URLError, HTTPError

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
        syslog.syslog(level, 'l7: %s' % msg)
    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)
    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)
    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)

DRIVER_NAME = 'L7'
DRIVER_VERSION = '0.2'

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
        print("Specify the IP address of the weather station console")
        settings['addr'] = self._prompt('addr', DEFAULT_ADDR)
        return settings


class L7Driver(weewx.drivers.AbstractDevice):

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        addr = stn_dict.get('addr', DEFAULT_ADDR)
        loginf('station address: %s' % addr)
        self._poll_interval = stn_dict.get('poll_interval', 10) # seconds
        loginf('polling interval: %s' % self._poll_interval)
        self._last_rain_total = None
        self.collector = L7Collector(addr)

    def closePort(self):
        pass

    @property
    def hardware_name(self):
        return DRIVER_NAME

    def genLoopPackets(self):
        while True:
            data = self.collector.get_data()
            logdbg('data: %s' % data)
            pkt = self.data_to_packet(data, self._last_rain_total)
            rain_total = pkt.get('rain_total')
            if rain_total is not None:
                self._last_rain_total = rain_total
            logdbg('packet: %s' % pkt)
            if pkt:
                yield pkt
            time.sleep(self._poll_interval)

    @staticmethod
    def data_to_packet(data, last_rain_total):
        # map the json data into weewx packet format.  the station has a fixed
        # number of sensors, so this mapping is hard-coded.  however, not every
        # sensor will report in each query, so be ready for that.
        #
        # each sensor has a title and list.  each item in the list is a tuple
        # of label, value, units, and possibly a fourth value (see Rainfall).
        # see the example json output at the beginning of this file.
        #
        # FIXME: check units and do conversions if necessary (does the console
        # setting affect the units reported in the JSON?)
        packet = dict()
        packet['dateTime'] = int(time.time() + 0.5)
        packet['usUnits'] = weewx.US
        if not data:
            return packet
        sensor_list = data.get('sensor', [])
        for sensor in sensor_list:
            title = sensor.get('title')
            if title == 'Indoor':
                items = sensor.get('list')
                for item in items:
                    if item[0] == 'Temperature':
                        packet['inTemp'] = float(item[1])
                    elif item[0] == 'Humidity':
                        packet['inHumidity'] = int(item[1])
            elif title == 'Outdoor':
                items = sensor.get('list')
                for item in items:
                    if item[0] == 'Temperature':
                        packet['outTemp'] = float(item[1])
                    elif item[0] == 'Humidity':
                        packet['outHumidity'] = int(item[1])
            elif title == 'Pressure':
                items = sensor.get('list')
                for item in items:
                    if item[0] == 'Absolute':
                        packet['pressure'] = float(item[1])
            elif title == 'Wind Speed':
                items = sensor.get('list')
                for item in items:
                    if item[0] == 'Wind':
                        packet['windSpeed'] = float(item[1])
                    elif item[0] == 'Gust':
                        packet['windGuest'] = float(item[1])
                    elif item[0] == 'Direction Average 2 Minute':
                        packet['windDir'] = float(item[1])
            elif title == 'Rainfall':
                rain_total = None
                items = sensor.get('list')
                for item in items:
                    if item[0] == 'Rate':
                        packet['rain_rate'] = float(item[1])
                    elif item[0] == 'Hour':
                        packet['rain_hour'] = float(item[1])
                    elif item[0] == 'Day':
                        packet['rain_day'] = float(item[1])
                    elif item[0] == 'Week':
                        packet['rain_week'] = float(item[1])
                    elif item[0] == 'Month':
                        packet['rain_month'] = float(item[1])
                    elif item[0] == 'Year':
                        packet['rain_year'] = float(item[1])
                    elif item[0] == 'Total':
                        rain_total = float(item[1])
                        packet['rain_total'] = rain_total
                if rain_total is not None and last_rain_total is not None:
                    packet['rain'] = rain_total - last_rain_total
            elif title == 'Solar':
                for item in items:
                    if item[0] == 'Light':
                        packet['luminosity'] = float(item[1])
                    elif item[0] == 'UVI':
                        packet['UV'] = float(item[1])
        battery = data.get('battery', {})
        batteries = battery.get('list', [])
        if batteries:
            if batteries[0] == 'All battery are ok':
                packet['battery'] = 0
        return packet


class L7Collector(object):
    def __init__(self, addr=DEFAULT_ADDR):
        self._addr = addr
        self._url = "http://%s/client?command=record" % addr
        self._max_tries = 3 # how many times to retry connection
        self._retry_wait = 10 # seconds to wait before retry after failure
        logdbg("station url: %s" % self._url)
    def get_data(self):
        for tries in range(self._max_tries):
            try:
                resp = urlopen(self._url).read()
                data = json.loads(resp)
                return data
            except (socket.error, socket.timeout, URLError, HTTPError) as e:
                logerr("failed attempt %s of %s to get data: %s" %
                       (tries + 1, self._max_tries, e))
                time.sleep(self._retry_wait)
            else:
                logerr("failed to get data after %s attempts" %
                       self._max_tries)
        return None


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

    # FIXME: this is a weewx v5 thing, will not work with older versions
    weeutil.logger.setup('wee_l7', { 'debug': args.debug })

    loginf('looking for station at %s' % args.addr)
    collector = L7Collector(args.addr)
    while True:
        try:
            data = collector.get_data()
            print(data)
            pkt = L7Driver.data_to_packet(data, 0) # ignore rain totals
            print(pkt)
        except KeyboardInterrupt:
            break
        time.sleep(1)


if __name__ == '__main__':
    main()
