# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.

from trac.db import Table, Column, Index

name = 'crashdump'
schema_version = 11
schema = [
    Table('crashdump', key=('id'))[
        Column('id', type='int', auto_increment=True),
        Column('uuid', type='string', size=36),
        Column('type', type='string', size=32),
        Column('status', type='string'),
        Column('priority', type='string', size=32),
        Column('severity', type='string', size=32),
        Column('owner', type='string'),
        Column('reporter', type='string'),
        Column('cc', type='string'),
        Column('component', type='string'),
        Column('milestone', type='string'),
        Column('version', type='string'),
        Column('resolution', type='string'),
        Column('summary', type='string'),
        Column('description', type='string'),
        Column('keywords', type='string'),
        Column('crashtime', type='int'),
        Column('reporttime', type='int'),
        Column('uploadtime', type='int'),
        Column('changetime', type='int'),
        Column('closetime', type='int'),
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
        Index(['id'], unique=True),
        Index(['uuid'], unique=True),
    ],
    Table('crashdump_change', key=('crash', 'time'))[
        Column('crash', type='int'),
        Column('time', type='int'),
        Column('author', type='string', size=256),
        Column('field', type='string', size=64),
        Column('oldvalue', type='string'),
        Column('newvalue', type='string'),
        Index(['crash', 'time'], unique=True)
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
   c.uuid AS _crash,
   c.crashtime as crashtime,
   c.applicationname as Application,
   c.priority,
   c.component
FROM crashdump c
LEFT JOIN enum p ON p.name = c.priority AND p.type = 'priority'
WHERE c.status <> 'closed'
ORDER BY CAST(p.value AS integer), c.crashtime
                        """, ' List all active crashes by priority'),
                    )
            ),
        )

