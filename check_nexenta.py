#!/usr/bin/python

#      Licensed to the Apache Software Foundation (ASF) under one
#      or more contributor license agreements.  See the NOTICE file
#      distributed with this work for additional information
#      regarding copyright ownership.  The ASF licenses this file
#      to you under the Apache License, Version 2.0 (the
#      "License"); you may not use this file except in compliance
#      with the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#      Unless required by applicable law or agreed to in writing,
#      software distributed under the License is distributed on an
#      "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#      KIND, either express or implied.  See the License for the
#      specific language governing permissions and limitations
#      under the License.

# ----------------------------------------------------------------
# 2012/09/25 v1.0.0 Brenn Oosterbaan - initial version
# 2012/10/03 v1.0.1 Brenn Oosterbaan - bug fix in API error handling
# 2012/10/08 v1.0.2 Brenn Oosterbaan - code optimization, bug fixes in
#                               space thresholds, added volume
#                               compression to performance data
#                               and extra support for HA clusters
# 2012/11/02 v1.0.3 Brenn Oosterbaan - python 2.4 compatible
# 2013/13/02 v1.0.4 Brenn Oosterbaan - added 2 retries for API connect
# 2013/14/02 v1.0.5 Patrick - added https and snmp v2 support
# 2013/15/02 v1.0.6 Brenn Oosterbaan - simplified snmp v2/v3 support
# 2013/16/02 v1.0.7 Brenn Oosterbaan - only lookup hostname once
# ----------------------------------------------------------------
# ----------------------------------------------------------------
# Schuberg Philis 2012
# ----------------------------------------------------------------
# Description:
#
# Script to provide performance data and monitor
# the health of Nexenta clusters and nodes.
# ----------------------------------------------------------------

import ConfigParser
import base64
import getopt
import os
import sys
import urllib2
import socket

try:
    import json
except ImportError:
    import simplejson as json

try:
    import netsnmp
except ImportError:
    pass


class CritError(Exception):
    def __init__(self, message):
        print "CRITICAL: %s" % message
        sys.exit(NagiosStates.CRITICAL)


class NagiosStates:
    RC = 0
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3

    # Only change RC if greater than previous value, with exceptions for state UNKNOWN.
    def __setattr__(self, name, value):
        if (name == "RC"):
            if (value != NagiosStates.UNKNOWN) and (NagiosStates.RC < value or NagiosStates.RC == NagiosStates.UNKNOWN):
                NagiosStates.__dict__[name] = value
            elif (value == NagiosStates.UNKNOWN) and (NagiosStates.RC == NagiosStates.OK):
                NagiosStates.__dict__[name] = value


class ReadConfig:
    # Check configfile for path, append script path if no path was given.
    # Default to <scriptname>.cfg if no configfile was given.
    def open_config(self, configfile):
        if not configfile:
            configfile = os.path.abspath(__file__).split(".")[0] + ".cfg"
        elif not os.path.dirname(configfile):
            configfile = os.path.join(os.path.dirname(__file__), configfile)

        ReadConfig.parse = ConfigParser.ConfigParser()
        try:
            ReadConfig.parse.readfp(open(configfile))
        except IOError:
            raise CritError("Can not open configuration file: %s" % configfile)

    # Get values from the config file.
    def get_option(self, section, option):
        try:
            return ReadConfig.parse.get(section, option)
        except ConfigParser.NoOptionError:
            return None
        except ConfigParser.NoSectionError:
            raise CritError("%s not defined in config file!" % section)

    # For 'known errors' we want to return the result if a option matches part of a string, or None.
    def known_errors(self, message):
        for known in self.parse.options('known_errors'):
            if known in message.lower():
                return self.parse.get('known_errors', known)
        return None


class NexentaApi:
    # Get the connection info and build the api url.
    def __init__(self, nexenta):
        cfg = ReadConfig()
        username = cfg.get_option(nexenta['hostname'], 'api_user')
        password = cfg.get_option(nexenta['hostname'], 'api_pass')
        if not username or not password:
            raise CritError("No connection info configured for %s" % nexenta['hostname'])
        
        ssl = cfg.get_option(nexenta['hostname'], 'api_ssl')
        if ssl != "ON":
            protocol = 'http'
        else:
            protocol = 'https'
            
        port = cfg.get_option(nexenta['hostname'], 'api_port')
        if not port:
            port = 2000

        self.base64_string = base64.encodestring('%s:%s' % (username, password))[:-1]
        self.url = '%s://%s:%s/rest/nms/ <%s://%s:%s/rest/nms/>' % (protocol, nexenta['ip'], port, protocol, 
                                                                    nexenta['ip'], port)

    # Build the request and return the response.
    def get_data(self, obj, meth, par):
        data = {'object': obj, 'method': meth, 'params': par}
        data = json.dumps(data)
        request = urllib2.Request(self.url, data)
        request.add_header('Authorization', 'Basic %s' % self.base64_string)
        request.add_header('Content-Type' , 'application/json')

        # Try to connect max 2 times.
        tries = 2
        while tries:
            try:
                response = json.loads(urllib2.urlopen(request).read())
                break
            except urllib2.URLError:
                tries += -1
        if not tries:
            raise CritError("Unable to connect to API at %s" % (self.url))

        if response['error']:
            raise CritError("API error occured: %s" % response['error'])
        else:
            return response['result']


class SnmpRequest:
    # Read config file and build the NDMP session.
    def __init__(self, nexenta):
        cfg = ReadConfig()
        
        username = cfg.get_option(nexenta['hostname'], 'snmp_user')
        password = cfg.get_option(nexenta['hostname'], 'snmp_pass')
        community = cfg.get_option(nexenta['hostname'], 'snmp_community')
        port = cfg.get_option(nexenta['hostname'], 'snmp_port')
        if not port:
            port = 161

        # If username/password use SNMP v3, else use SNMP v2.
        if username and password:
            self.session = netsnmp.Session(DestHost='%s:%s' % (nexenta['ip'], port), Version=3, SecLevel='authNoPriv',
                                           AuthProto='MD5', AuthPass=password, SecName=username)            
        elif community:
            self.session = netsnmp.Session(DestHost='%s:%s' % (nexenta['ip'], port), Version=2, Community=community)
        else:
             raise CritError("Incorrect SNMP info configured for %s" % nexenta['hostname'])

    # Return the SNMP get value.
    def get_snmp(self, oid):
        value = netsnmp.VarList(netsnmp.Varbind(oid))

        if not self.session.get(value):
            return None
        else:
            return value[0].val

    # Return the SNMP walk values.
    def walk_snmp(self, oid):
        values = netsnmp.VarList(netsnmp.Varbind(oid))

        if not self.session.walk(values):
            return None
        else:
            return values


# Convert human readable to real numbers.
def convert_space(size):
    size_types = { "B": 1, "K": 1024, "M": 1048576, "G": 1073741824, "T": 1099511627776 }
    try:
        return (float(size[:-1]) * int(size_types[size[-1:]]))
    except (KeyError, ValueError):
        return 0


# Convert severity/description for known errors defined in config file.
def known_errors(result):
    cfg = ReadConfig()

    # Check if part of the message matches a string in the config file.
    description = cfg.known_errors(result['description'])
    if description:
        # Match found, return severity/description.
        try:
            severity, description = description.split(';')
        except ValueError:
            raise CritError("Error in config file at [known_errors], line: %s" % description)
    else:
        # No match found, append default if defined in the config file.
        description = cfg.get_option('known_errors', "DEFAULT")
        if description:
            try:
                severity, description = description.split(';')
            except ValueError:
                raise CritError("Error in config file at [known_errors], line: %s" % description)
            description = "%s %s" % (result['description'], description)
        else:
            severity = result['severity']
            description = result['description']

    if severity.upper() == "DEFAULT":
        severity = result['severity']

    return severity, description


# Check volume space usage.
def check_spaceusage(nexenta):
    cfg = ReadConfig()
    errors = []

    # Only check space usage if space thresholds are configured in the config file.
    thresholds = cfg.get_option(nexenta['hostname'], 'space_threshold')
    if thresholds:
        api = NexentaApi(nexenta)
        rc = NagiosStates()

        # Get a list of all volumes and add syspool.
        volumes = api.get_data(obj='folder', meth='get_names', par=[''])
        volumes.extend(["syspool"])

        for vol in volumes:
            # Skip this volume if no match and no default in thresholds.
            if not vol + ";" in thresholds and not "DEFAULT;" in thresholds:
                continue

            for threshold in thresholds.split('\n'):
                if not threshold:
                    continue

                # Check/extend the thresholds.
                if len(threshold.split(';')) == 3:
                    threshold += ";IGNORE;IGNORE"
                elif len(threshold.split(';')) != 5:
                    raise CritError("Error in config file at [%s]:space_threshold, line %s" % (nexenta['hostname'], threshold))

                # Get the thresholds, or fall back to the default tresholds.
                if vol + ";" in thresholds:
                    if threshold.split(';')[0] == vol:
                        volwarn, volcrit, snapwarn, snapcrit = threshold.split(';')[1:]
                elif "DEFAULT;" in thresholds:
                    if threshold.split(';')[0] == "DEFAULT":
                        volwarn, volcrit, snapwarn, snapcrit = threshold.split(';')[1:]

            # Get volume properties.
            volprops = api.get_data(obj='folder', meth='get_child_props', par=[vol, ''])

            # Get used/available space.
            available = volprops.get('available')
            snapused = volprops.get('usedbysnapshots')
            volused = convert_space(volprops.get('used'))

            snapusedprc = (convert_space(snapused) / (volused + convert_space(available))) * 100
            volusedprc = (volused / (volused + convert_space(available))) * 100

            # Check if a snapshot threshold has been met.
            snaperror = ""
            if snapwarn[:-1].isdigit():
                if '%' in snapwarn:
                    if int(snapwarn[:-1]) <= snapusedprc:
                        rc.RC = NagiosStates.WARNING
                        snaperror = "WARNING: %s%% of %s used by snaphots" % (int(snapusedprc), vol)
                elif convert_space(snapwarn) <= convert_space(snapused):
                        rc.RC = NagiosStates.WARNING
                        snaperror = "WARNING: %s of %s used by snaphots" % (snapused, vol)

            if snapcrit[:-1].isdigit():
                if '%' in snapcrit:
                    if int(snapcrit[:-1]) <= snapusedprc:
                        rc.RC = NagiosStates.CRITICAL
                        snaperror = "CRITICAL: %s%% of %s used by snaphots" % (int(snapusedprc), vol)
                elif convert_space(snapcrit) <= convert_space(snapused):
                        rc.RC = NagiosStates.CRITICAL
                        snaperror = "CRITICAL: %s of %s used by snaphots" % (snapused, vol)

            if snaperror:
                errors.append(snaperror)

            # Check if a folder threshold has been met.
            if volcrit[:-1].isdigit():
                if '%' in volcrit:
                    if int(volcrit[:-1]) <= volusedprc:
                        rc.RC = NagiosStates.CRITICAL
                        errors.append("CRITICAL: %s %s%% full!" % (vol, int(volusedprc)))
                        continue
                elif convert_space(volcrit) >= convert_space(available):
                    rc.RC = NagiosStates.CRITICAL
                    errors.append("CRITICAL: %s %s available!" % (vol, available))
                    continue

            if volwarn[:-1].isdigit():
                if '%' in volwarn:
                    if int(volwarn[:-1]) <= volusedprc:
                        rc.RC = NagiosStates.WARNING
                        errors.append("WARNING: %s %s%% full" % (vol, int(volusedprc)))
                elif convert_space(volwarn) >= convert_space(available):
                    rc.RC = NagiosStates.WARNING
                    errors.append("WARNING: %s %s available" % (vol, available))

    return (errors)


# Check Nexenta runners for faults.
def check_triggers(nexenta):
    cfg = ReadConfig()
    rc = NagiosStates()
    errors = []

    # Check all triggers, if skip_triggers is not set to 'on' in the config file.
    skip = cfg.get_option(nexenta['hostname'], 'skip_trigger')
    if skip != "ON":
        api = NexentaApi(nexenta)

        triggers = api.get_data(obj='reporter', meth='get_names_by_prop', par=['type', 'trigger', ''])
        for trigger in triggers:
            results = api.get_data(obj='trigger', meth='get_faults', par=[trigger])
            for result in results:
                result = results[result]

                # Convert severity/description.
                severity, description = known_errors(result)
                if severity == "CRITICAL":
                    rc.RC = NagiosStates.CRITICAL
                else:
                    rc.RC = NagiosStates.WARNING
                errors.append("%s:%s: %s" % (trigger, severity, description))

    return (errors)


# Get snmp extend data and write to Output and/or Perfdata.
def collect_extends(nexenta):
    cfg = ReadConfig()
    rc = NagiosStates()
    output = []
    perfdata = []

    # Collect snmp extend data, if snmp_extend is configured in the config file for this Nexenta.
    extend = cfg.get_option(nexenta['hostname'], 'snmp_extend')
    if extend == "ON":
        # Check for dependancy net-snmp-python.
        try:
            netsnmp
        except NameError:
            rc.RC = NagiosStates.WARNING
            return ("WARNING: net-snmp-python not available, SNMP Extend Data will be skipped.", "")
        else:
            snmp = SnmpRequest(nexenta)

        # Snmp walk through all extends and collect the data.
        extends = snmp.walk_snmp('NET-SNMP-EXTEND-MIB::nsExtendOutLine')
        if extends:
            for data in extends:
                if "PERFDATA:" in data.val:
                    perfdata.append(data.val.split("PERFDATA:")[1])
                elif "OUTPUT:" in data.val:
                    output.append(data.val.split("OUTPUT:")[1])

                    if "CRITICAL" in data.val:
                        rc.RC = NagiosStates.CRITICAL
                    elif "WARNING" in data.val:
                        rc.RC = NagiosStates.WARNING

    return (output, perfdata)


# Collect Nexenta performance data.
def collect_perfdata(nexenta):
    cfg = ReadConfig()
    rc = NagiosStates()
    perfdata = []
    output = []

    # Collect SNMP performance data, if snmp is configured in the config file for this Nexenta.
    if cfg.get_option(nexenta['hostname'], 'snmp_user') or cfg.get_option(nexenta['hostname'], 'snmp_community'):
        # Check for dependancy net-snmp-python.
        try:
            netsnmp
        except NameError:
            rc.RC = NagiosStates.WARNING
            output.append("WARNING: net-snmp-python not available, SNMP Performance Data will be skipped.")
        else:
            snmp = SnmpRequest(nexenta)

            # Get CPU usage.
            cpu_info = snmp.walk_snmp('HOST-RESOURCES-MIB::hrProcessorLoad')
            if cpu_info:
                for cpu_id, cpu_load in enumerate(cpu_info):
                    perfdata.append("'CPU%s used'=%s%%" % (cpu_id, cpu_load.val))

            # Get Network Traffic.
            interfaces = snmp.walk_snmp('IF-MIB::ifName')
            if interfaces:
                for interface in interfaces:
                    intraffic = snmp.get_snmp('IF-MIB::ifHCInOctets.%s' % interface.iid)
                    outtraffic = snmp.get_snmp('IF-MIB::ifHCOutOctets.%s' % interface.iid)
                    intraffic = int(intraffic) * 8
                    outtraffic = int(outtraffic) * 8

                    perfdata.append("'%s Traffic in'=%sc" % (interface.val, intraffic))
                    perfdata.append("'%s Traffic out'=%sc" % (interface.val, outtraffic))

    # Collect API performance data, if api is configured in the config file for this Nexenta.
    if cfg.get_option(nexenta['hostname'], 'api_user') and cfg.get_option(nexenta['hostname'], 'api_pass'):
        api = NexentaApi(nexenta)
        volumes = []

        # Get perfdata for all volumes, or only for syspool if skip_folderperf is set to 'on'.
        skip = cfg.get_option(nexenta['hostname'], 'skip_folderperf')
        if skip != "ON":
            volumes.extend(api.get_data(obj='folder', meth='get_names', par=['']))

        volumes.extend(["syspool"])

        for vol in volumes:
            # Get volume properties.
            volprops = api.get_data(obj='folder', meth='get_child_props', par=[vol, ''])

            # Get volume used, free and snapshot space.
            used = convert_space(volprops.get('used')) / 1024
            free = convert_space(volprops.get('available')) /1024
            snap = convert_space(volprops.get('usedbysnapshots')) / 1024

            perfdata.append("'/%s used'=%sKB" % (vol, int(used)))
            perfdata.append("'/%s free'=%sKB" % (vol, int(free)))
            perfdata.append("'/%s snapshots'=%sKB" % (vol, int(snap)))

            # Get compression ratio, if compression is enabled.
            compression = volprops.get('compression')
            if compression == "on":
                ratio = volprops.get('compressratio')

                perfdata.append("'/%s compressratio'=%s" % (vol, ratio[:-1]))

        # Get memory used, free and paging.
        memstats = api.get_data(obj='appliance', meth='get_memstat', par=[''])

        perfdata.append("'Memory free'=%sMB" % (memstats.get("ram_free")))
        perfdata.append("'Memory used'=%sMB" % (memstats.get("ram_total") - memstats.get("ram_free")))
        perfdata.append("'Memory paging'=%sMB" % (memstats.get("ram_paging")))

    return (output, perfdata)


# Main
def main(argv):
    # Parse command line arguments.
    try:
        opts, args = getopt.getopt(argv, "H:DTPEhVf:", ["hostname", "help", "version"])
    except getopt.GetoptError:
        raise CritError("Invalid arguments, usage: -H <hostname>, [-D(space usage)], "
                        "[-T(triggers)], [-P(perfdata)], [-E(extends)], [-f(config file)], "
                        "[-h(help)], [-V(version)]")

    configfile = ""
    for opt, arg in opts:
        if opt in ("-H", "--hostname"):
            nexenta = arg
        elif opt == "-f":
            configfile = arg
        elif opt in ("-h", "--help"):
            print_usage()
        elif opt in ("-V", "--version"):
            print_version()

    try:
        nexenta = { 'hostname': nexenta, 'ip': socket.getaddrinfo(nexenta,None)[0][4][0] }
    except NameError:
        raise CritError("Invalid arguments, no hostname specified!")
    except socket.gaierror:
        raise CritError("No IP address found for %s!" % nexenta)
        
    # If only -H is passed execute default checks.
    if len(opts) == 1:
        opts.extend([("-D", ""), ("-T", "")])

    # Open the configfile for use and start the checks.
    cfg = ReadConfig()
    cfg.open_config(configfile)

    output = []
    perfdata = []
    for opt, arg in opts:
        if opt == "-D":
            # Check spage usage.
            result = check_spaceusage(nexenta)
            if result:
                output.extend(result)
        elif opt == "-T":
            # Check fault triggers.
            result = check_triggers(nexenta)
            if result:
                output.extend(result)
        elif opt == "-E":
            # Run SNMP extend scripts and collect output/performance data.
            out, perf = collect_extends(nexenta)
            if out:
                output.extend(out)
            if perf:
                perfdata.extend(perf)
        elif opt == "-P":
            # Collect performance data.
            out, perf = collect_perfdata(nexenta)
            if out:
                output.extend(out)
            if perf:
                perfdata.extend(perf)

    if NagiosStates.RC == NagiosStates.OK:
        output.append("Nexenta check OK")

    # Append performance data if collected and print output.
    if perfdata:
        return "%s|%s" % ("<br>".join(output), " ".join(perfdata))
    else:
        return ("<br>".join(output))

def print_usage():
    print "usage: check_nexenta.py -H <arg> [options]"
    print "Options and arguments (defaults to [-D, -T] if only -H is given):"
    print "-H arg : Nexenta to check. Can be hostname or IP adress. Must be configured in"
    print "         the config file. Short for --hostname."
    print "-D     : Check space usage of volumes. Thresholds are configured in the config"
    print "         file."
    print "-T     : Check fault triggers."
    print "-P     : Report SNMP performance data. Must be configured in the config file."
    print "         Reports data for CPU, Disk, Snapshot, Memory and Network."
    print "-E     : Report SNMP extend data. Must be configured in the config file."
    print "       : See help below on snmp_extend for more info."
    print "-f     : Config file to use. Defaults to <scriptname>.cfg if not given."
    print "-V     : Show version information. Short for --version."
    print "-h     : Show help information. Short for --help."
    print ""
    print "Config file sections and options:"
    print "[<hostname>]    : Nexenta to check. Should match argument passed to -H."
    print "                  Config file can contain multiple sections of [<hostname>]."
    print "api_user        : Username which has API rights on the Nexenta"
    print "api_pass        : Password for the user with API rights."
    print "api_ssl         : Use HTTP-SSL (https://) for connection."
    print "api_port        : Port used for API connection to the Nexenta. Defaults to"
    print "                  standard NMV port (2000) if not set."
    print "snmp_user       : SNMP username with ro rights on the Nexenta. Only needed"
    print "                  for SNMP v3."
    print "snmp_pass       : Password for the SNMP user. Only needed for SNMP v3."
    print "snmp_community  : SNMP ro community. Only needed for SNMP v2. Will not be"
    print "                  used if snmp_user and snmp_pass are configured."
    print "snmp_port       : Port used for SNMP connection to the Nexenta. Defaults to"
    print "                  standard SNMP port (161) if not set."
    print "snmp_extend     : If set to ON, query SNMP extend for data. SNMP extend on a"
    print "                  Nexenta can be multiple scripts. Each line of output from a"
    print "                  extend script must start with PERFDATA: followed by any"
    print "                  performance data you wish to collect, or OUTPUT: followed"
    print "                  by either WARNING or CRITICAL and the message to report."
    print "                  Two examples of output extend scripts could generate:"
    print "                  PERFDATA:'ARC hit'=75% 'ARC miss'=17%"
    print "                  OUTPUT:WARNING: ARC hit ratio below 80%!"
    print "skip_trigger    : If set to ON, do not check fault triggers. Usefull to "
    print "                  prevent double fault reporting when checking a virtual node"
    print "                  of a Nexenta HA cluster."
    print "skip_folderperf : If set to ON, do not return performance data for folders."
    print "                  Usefull to prevent double performance reporting when checking"
    print "                  a virtual node of a Nexenta HA cluster."
    print "space_threshold : Thresholds for the folder space usage check. Can be multiple"
    print "                  lines formatted as <folder>;<vol-warning>;<vol-critical>;"
    print "                  <snap-warning>;<snap-critical>."
    print "                  <folder> can be a specific volume or DEFAULT."
    print "                  Volume thresholds can be a percentage of space used(%),"
    print "                  amount of free space([M,G,T]) or IGNORE."
    print "                  Snapshot thresholds can be a percentage of space used(%),"
    print "                  amount of space used([M,G,T]) or IGNORE."
    print "                  DEFAULT thresholds are applied to all folders not specified."
    print "[known_errors]  : Convert severity and/or description of known error messages."
    print "                  Can consist of multiple options(error messages) formatted as"
    print "                  <error message> = <severity>;<description>."
    print "                  <error message> can be a part of a error message or DEFAULT."
    print "                  <severity> can be DEFAULT, NOTICE, WARNING or CRITICAL."
    print "                  DEFAULT severity does not change the original severity level."
    print "                  <description> is the description to which the error message"
    print "                  will be changed. If no match is found the DEFAULT description"
    print "                  will be appended to the orignial error message(if a DEFAULT"
    print "                  has been configured)."
    sys.exit()

def print_version():
    print "Version 1.0.7"
    sys.exit()

if __name__ == '__main__':
    print main(sys.argv[1:])
    sys.exit(NagiosStates.RC)
