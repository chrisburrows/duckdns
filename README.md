# duckdns

Simple python script to maintain an external IP address with DuckDNS.

The script also maintains four sensors for Home Assistant via MQTT:

- an availability sensor to show if the script itself is running
- a sensor with the external IPv4 address
- a sensor for the state of the DuckDNS dynamic DNS name. This sensor has the HA device class of "problem" so indicates if there is an issue with updating the DuckDNS domain
- a sensor with the time the last problem occurred

Home Assistant auto-discovery is supported for these sensors.
