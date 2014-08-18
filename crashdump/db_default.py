# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.

from trac.db import Table, Column

name = 'crashdump'
version = 2
tables = [
    Table('crashdump', key=('uuid'))[
        Column('uuid', type='string'),
        Column('timestamp', type='timestamp'),
        Column('applicationname', type='string'),
        Column('applicationfile', type='string'),
        Column('clienthostname', type='string'),
        Column('clientusername', type='string'),
    ]
]

#def convert_to_int(data):
    #"""Convert both source and dest in the mastertickets table to ints."""
    #rows = data['mastertickets'][1]
    #for i, (n1, n2) in enumerate(rows):
        #rows[i] = [int(n1), int(n2)]

migrations = [
]
