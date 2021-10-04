#!/usr/bin/python3
#
# coding=utf-8
# DuckDNS updates with MQTT status reporting

# Press ⌃R to execute it or replace it with your code.

import os
import socket
import requests
from datetime import datetime
from datetime import timedelta
import logging.handlers
import time
import json
import platform
import paho.mqtt.client as mqtt

LOG_FILENAME = '/var/log/duckdns/duckdns.log'
HA_ICON = "mdi:duck"

UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "5"))
DUCKDNS_FORCE_UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "900"))

DUCKDNS_DOMAINS = os.getenv("DUCKDNS_DOMAINS", "my-domain")
DUCKDNS_TOKEN = os.getenv("DUCKDNS_TOKEN", "token-uuid")

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt.local")
MQTT_USER = os.getenv("MQTT_USER", "mqtt")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "password")
MQTT_BASE_TOPIC = "duckdns"

externalIp = None
duckdnsOk = False
lastProblemTime = None

def getOurIp():
    try:
        r = requests.get('https://api.ipify.org/?format=json')
        if r.status_code == 200:
            log.debug("IPIFY: Got our external IP {ip}".format(ip=r.json()['ip']))
            return r.json()['ip']
    except:
        pass

    log.warning("IPIFY: Failed getting our external IP")
    return None

def updateDuckDns():
    log.info("DuckDNS: Updating DuckDNS")
    try:
        url = "https://www.duckdns.org/update?domains={domains}&token={token}&ip=".format(
            domains=DUCKDNS_DOMAINS, token=DUCKDNS_TOKEN)
        r = requests.get(url)
        if r.status_code == 200:
            if r.content == b'OK':
                return True
            else:
                log.error("DuckDNS: Update failed - check domains and token")
                return False
    except:
        pass

    log.error("DuckDNS: failed to access DuckDNS API")
    return None

# The callback for when the client receives a CONNACK response from the server.
def onConnect(client, userdata, flags, rc):
    log.info("MQTT: Connected to broker with result code " + str(rc))

    client.publish(MQTT_BASE_TOPIC + "/status", payload="online", retain=True)
    client.will_set(MQTT_BASE_TOPIC + "/status", payload="offline", retain=True)
    client.subscribe(MQTT_BASE_TOPIC + "/last-problem-time")

    # update discovery each time we connect
    publishHomeAssistantDiscovery(client)

def on_message(client, userdata, msg):
    global lastProblemTime
    payload = str(msg.payload, "UTF-8").strip()
    log.debug("MQTT: Message " + msg.topic + " = " + payload)
    if "/last-problem-time" in msg.topic:
        log.info("MQTT: received last problem time {dt}".format(dt=payload))
        dt = datetime.fromisoformat(payload)
        if dt != lastProblemTime:
            lastProblemTime = dt

def recordProblemTime(client, time):
    '''Update last problem time and publish to MQTT'''
    global lastProblemTime

    lastProblemTime = time
    client.publish(MQTT_BASE_TOPIC + "/last-problem-time", payload=str(lastProblemTime.isoformat()), retain=True)

def publishStatus(client, externalIp, duckdnsStatusOk):
    '''Publish the DuckDNS status to MQTT'''
    log.info("MQTT: Publishing DuckDNS status for {ip} as {state}".format(
        ip=externalIp, state='OK' if duckdnsStatusOk else 'Not OK'))
    client.publish(MQTT_BASE_TOPIC + "/ipv4", payload=externalIp, retain=True)
    client.publish(MQTT_BASE_TOPIC + "/published-entry-problem", payload='off' if duckdnsStatusOk else 'on', retain=True)

def publishHomeAssistantDiscovery(client):
    '''Publish discovery for the two sensors'''
    log.info("MQTT: Publishing Home Assistant discovery data")
    payload = {
        "name": "DuckDNS IPv4",
        "state_topic": "{base}/ipv4".format(base=MQTT_BASE_TOPIC),
        "availability_topic": "{base}/status".format(base=MQTT_BASE_TOPIC),
        "payload_available": "online",
        "payload_not_available": "offline",
        "unique_id": "{host}-duckdns-ipv4".format(host=platform.node()),
        "icon": HA_ICON
    }
    discovery_topic = "homeassistant/sensor/duckdns-ipv4/config"
    client.publish(discovery_topic, payload=json.dumps(payload), retain=True)

    payload = {
        "name": "DuckDNS Last Problem Time",
        "state_topic": "{base}/last-problem-time".format(base=MQTT_BASE_TOPIC),
        "availability_topic": "{base}/status".format(base=MQTT_BASE_TOPIC),
        "payload_available": "online",
        "payload_not_available": "offline",
        "unique_id": "{host}-last-problem-time".format(host=platform.node()),
        "icon": "mdi:clock-outline"
    }
    discovery_topic = "homeassistant/sensor/duckdns-last-problem-time/config"
    client.publish(discovery_topic, payload=json.dumps(payload), retain=True)

    payload = {
        "name": "DuckDNS Entry",
        "state_topic": "{base}/published-entry-problem".format(base=MQTT_BASE_TOPIC),
        "availability_topic": "{base}/status".format(base=MQTT_BASE_TOPIC),
        "payload_available": "online",
        "payload_not_available": "offline",
        "device_class": "problem",
        "unique_id": "{host}-duckdns-published-entry-problem".format(host=platform.node()),
        "icon": HA_ICON
    }
    discovery_topic = "homeassistant/binary_sensor/duckdns-published-entry/config"
    client.publish(discovery_topic, payload=json.dumps(payload), retain=True)

def dnsLookup():
    try:
        return set([str(i[4][0]) for i in socket.getaddrinfo(DUCKDNS_DOMAINS, 80)])
    except:
        return None

def setupMqtt():
    client = mqtt.Client(client_id="duckdns")
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = onConnect
    client.on_message = on_message
    client.max_queued_messages_set(10)
    client.connect_async(MQTT_BROKER, 1883, keepalive=60)
    client.loop_start()
    return client

def update():
    global lastProblemTime

    while True:
        try:
            client = setupMqtt()

            ourIp = getOurIp()
            log.info("External IP is {ip}".format(ip=ourIp))

            status = updateDuckDns()
            publishStatus(client, ourIp, status)

            iterationsPerForcedUpdate = int(DUCKDNS_FORCE_UPDATE_INTERVAL / UPDATE_INTERVAL)

            while True:
                for i in range(iterationsPerForcedUpdate):
                    ourIp = getOurIp()
                    dnsIps = dnsLookup()

                    if ourIp is not None and dnsIps is not None:
                        lastProblemTime = None
                        if ourIp not in dnsIps:
                            log.info("External IP address changed to {ip}".format(ip=ourIp))
                            status = updateDuckDns()
                            publishStatus(client, ourIp, status)
                            if not status:
                                recordProblemTime(client, datetime.now())
                    else:
                        # problem with an API call
                        if lastProblemTime is None:
                            recordProblemTime(client, datetime.now())

                    time.sleep(UPDATE_INTERVAL)

                status = updateDuckDns()
                publishStatus(client, ourIp, status)
                time.sleep(UPDATE_INTERVAL)

        except KeyboardInterrupt:
            log.info("Interrupted... shutting down")

        except Exception as e:
            log.error(str(e))
            client.publish(MQTT_BASE_TOPIC + "/status", payload="offline", retain=True).wait_for_publish()
            log.info("MQTT: disconnecting")
            client.loop_stop()
            client.disconnect()

# Press the green button in the gutter to run the script.
if __name__ == '__main__':

    # setup logging
    log = logging.getLogger()
    handler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME, when='midnight', backupCount=7)
    formatter = logging.Formatter('{asctime} {levelname:8s} {message}', style='{')

    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    log.info("+=========================+")
    log.info("|       Starting up       |")
    log.info("+=========================+")

    update()

