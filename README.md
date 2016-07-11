Check_Nexenta
=============

Check_Nexenta uses the Nexenta API to monitor system health and report performance data. 
It can also use SNMP for additional performance monitoring,
and SNMP extends for custom performance and/or health monitoring.

Features
========
* Report all warnings and criticals the Nexenta runners report (failed hardware, cluster issues, memory low, cpu high etc).
* Report performance data for CPU, Memory, Network, Volumes, Folders, Snapshots and Compression.
* Report warnings, criticals and performance data supplied by your own custom SNMP extend scripts.
* Warn on Volume and Folder available free space in % or MB/GB/TB.
* Warn on Snapshot used space in % or MB/GB/TB.
* Convert descriptions and warning levels of known errors.

Supports
========
* NexentaStor 3.1.2/3.1.3/3.1.3.5/3.1.4/3.1.4.1/3.1.5/4.0.X
* HTTP and HTTPS
* SNMPv2 and SNMPv3
* Python 2.4/2.6/2.7

Getting Started
===============
* Make sure you have Python 2.4 or greater installed (tested with python 2.4, 2.6 and 2.7)
* Download NET-SNMP and follow the instructions in the README of the python directory (http://www.net-snmp.org/download.html).
* Enable SNMP on your Nexenta.
* Enable log rotation for nmv.log on your Nexenta (see http://www.cupfighter.net/index.php/2013/03/default-nexenta-zfs-settings-you-want-to-change-part-2/).
* Download check_nexenta.py and check_nexenta.cfg.
* Edit check_nexenta.cfg and add the relevant information.
* Run check_nexenta.py --help for more comprehensive information on what options are available.
* Start using check_nexenta.py either manually, from Nagios or any another monitoring system you like.
