#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

from trac.db import Table, Column, Index

name = 'crashdump'
schema_version = 13
schema = [
    Table('crashdump', key=('id'))[
        Column('id', type='int', auto_increment=True),
        Column('uuid', size=36),
        Column('type', size=32),
        Column('status'),
        Column('priority', size=32),
        Column('severity', size=32),
        Column('owner'),
        Column('reporter'),
        Column('cc'),
        Column('component'),
        Column('milestone'),
        Column('version'),
        Column('resolution'),
        Column('summary'),
        Column('description'),
        Column('keywords'),
        Column('crashtime', type='int64'),
        Column('reporttime', type='int64'),
        Column('uploadtime', type='int64'),
        Column('changetime', type='int64'),
        Column('closetime', type='int64'),
        Column('applicationname', size=128),
        Column('applicationfile', size=512),
        Column('uploadhostname', size=256),
        Column('uploadusername', size=64),
        Column('crashhostname', size=256),
        Column('crashusername', size=64),
        Column('productname', size=64),
        Column('productcodename', size=64),
        Column('productversion', size=32),
        Column('producttargetversion', size=32),
        Column('buildtype', size=16),
        Column('buildpostfix', size=4),
        Column('machinetype', size=16),
        Column('systemname', size=32),
        Column('osversion', size=32),
        Column('osrelease', size=32),
        Column('osmachine', size=32),

        Column('minidumpfile', size=256),
        Column('minidumpreporttextfile', size=256),
        Column('minidumpreportxmlfile', size=256),
        Column('minidumpreporthtmlfile', size=256),

        Column('coredumpfile', size=256),
        Column('coredumpreporttextfile', size=256),
        Column('coredumpreportxmlfile', size=256),
        Column('coredumpreporthtmlfile', size=256),
        Index(['id'], unique=True),
        Index(['uuid'], unique=True),
    ],
    Table('crashdump_change', key=('crash', 'time', 'field'))[
        Column('crash', type='int'),
        Column('time', type='int'),
        Column('author', size=256),
        Column('field', size=64),
        Column('oldvalue'),
        Column('newvalue'),
        Index(['crash', 'time', 'field'], unique=True)
    ],
    Table('crashdump_ticket', key=('crash', 'ticket'))[
        Column('crash', type='int'),
        Column('ticket', type='int'),
        Index(['crash', 'ticket'], unique=True)
    ],
    # version 13
    Table('crashdump_stack', key=('crash', 'threadid', 'frameno') )[
        Column('crash', type='int'),
        Column('threadid', type='int'),
        Column('frameno', type='int'),
        Column('module'),
        Column('function'),
        Column('funcoff', type='int'),
        Column('source'),
        Column('line', type='int'),
        Column('lineoff', type='int'),
        Index(['crash', 'frameno']),
        Index(['crash', 'threadid', 'frameno'], unique=True),
    ],
]

def get_current_schema_version(db):
    """Return the current schema version for this plugin."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT value
            FROM system
            WHERE name='%s'
    """ % (name + '_version'))
    row = cursor.fetchone()
    # The expected outcome for any up-to-date installation.
    return row and int(row[0]) or 0

# (table, (column1, column2), ((row1col1, row1col2), (row2col1, row2col2)))
def get_data(db):
    return (
            ('system',
                ('name', 'value'),
                    (
                        (name + '_version', str(schema_version)),
                    )
            ),
            ('report',
                ('title', 'QUERY', 'description'),
                    (
                        ('Active crashes', """
SELECT p.value AS __color__,
c.productname || " " || c.productversion || " (" || c.producttargetversion || ")" AS __group__,
   c.uuid AS _crash,
   c.crashtime AS crashtime,
   c.crashusername AS 'Crash user',
   c.crashhostname AS 'Crash hostname',
   c.status,
   c.priority,
   c.component,
   c.version,
   c.milestone,
   c.applicationname AS Application,
   c.machinetype || "/" || c.systemname AS 'System name',
   c.osversion AS 'OS Version',
   c.buildtype AS 'Build Type',
   (SELECT GROUP_CONCAT(ticket) from crashdump_ticket where crash=c.id) AS linked_tickets
FROM crashdump c
LEFT JOIN enum p ON p.name = c.priority AND p.type = 'priority'
WHERE c.status <> 'closed'
ORDER BY """ + db.cast('p.value', 'int') + """, c.crashtime
                        """, ' List all active crashes by priority'),
                    )
            ),
        )

