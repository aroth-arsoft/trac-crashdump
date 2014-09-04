from trac.db import Table, Column, Index, DatabaseManager

schema = [
    Table('crashdump_stack', key=('crash', 'threadid', 'frameno') )[
        Column('crash', type='int'),
        Column('threadid', type='int'),
        Column('frameno', type='int'),
        Column('function'),
        Column('source'),
        Column('line', type='int'),
        Index(['crash', 'frameno']),
    ]
]

def do_upgrade(env, ver, cursor):
    """adds the table crashdump_stack
    """
    
    connector = DatabaseManager(env)._get_connector()[0]
    for table in schema:
        for stmt in connector.to_sql(table):
            cursor.execute(stmt)
