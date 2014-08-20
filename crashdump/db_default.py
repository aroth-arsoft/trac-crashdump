# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.

from trac.db import Table, Column

name = 'crashdump'
version = 4
tables = [
    Table('crashdump', key=('id'))[
        Column('id', type='int'),
        Column('uuid', type='string', size=36),
        Column('crashtime', type='int'),
        Column('reporttime', type='int'),
        Column('uploadtime', type='int'),
        Column('applicationname', type='string', size=128),
        Column('applicationfile', type='string', size=512),
        Column('uploadhostname', type='string', size=256),
        Column('uploadusername', type='string', size=64),
        Column('crashhostname', type='string', size=256),
        Column('crashusername', type='string', size=64),
        Column('productname', type='string', size=64),
        Column('productcodename', type='string', size=64),
        Column('productversion', type='string', size=32),
        Column('producttargetversion', type='string', size=32),
        Column('buildtype', type='string', size=16),
        Column('buildpostfix', type='string', size=4),
        Column('machinetype', type='string', size=16),
        Column('systemname', type='string', size=32),
        Column('osversion', type='string', size=32),
        Column('osrelease', type='string', size=32),
        Column('osmachine', type='string', size=32),

        Column('minidumpfile', type='string', size=256),
        Column('minidumpreporttextfile', type='string', size=256),
        Column('minidumpreportxmlfile', type='string', size=256),
        Column('minidumpreporthtmlfile', type='string', size=256),

        Column('coredumpfile', type='string', size=256),
        Column('coredumpreporttextfile', type='string', size=256),
        Column('coredumpreportxmlfile', type='string', size=256),
        Column('coredumpreporthtmlfile', type='string', size=256),
    ]
]

#def convert_to_int(data):
    #"""Convert both source and dest in the mastertickets table to ints."""
    #rows = data['mastertickets'][1]
    #for i, (n1, n2) in enumerate(rows):
        #rows[i] = [int(n1), int(n2)]

migrations = [
]
