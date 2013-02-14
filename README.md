Check_Nexenta
=============

Check_Nexenta uses the Nexenta API to monitor system health and report performance data. 
It can also use SNMP for additional performance monitoring,
and SNMP extends for custom performance and/or health monitoring.

Getting Started
================
* Make sure you have Python 2.4 or greater installed (tested with python 2.4, 2.6 and 2.7)
* Download NET-SNMP and follow the instructions in the README of the python directory.
  (http://www.net-snmp.org/download.html)
* Enable SNMP on your Nexenta.
* Dowload check_nexenta.py and check_nexenta.cfg.
* Edit check_nexenta.cfg and add the relevant information.
* Run check_nexenta.py --help for more comprehensive information on what options are available.
* Start using check_nexenta.py either manually, from Nagios or another monitoring system you like.

