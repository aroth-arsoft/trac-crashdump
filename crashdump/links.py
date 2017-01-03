#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import copy
from trac.util.compat import set, sorted
from trac.util.datefmt import from_utimestamp, to_utimestamp, utc, utcmax
from trac.ticket.model import Ticket
from datetime import datetime

class CrashDumpTicketLinks(object):
    """A model for the ticket to crash links used TracCrashDump."""

    def __init__(self, env, tkt, db):
        self.env = env
        if not isinstance(tkt, Ticket):
            tkt = Ticket(self.env, tkt)
        self.tkt = tkt

        cursor = db.cursor()

        cursor.execute('SELECT crash FROM crashdump_ticket WHERE ticket=%s ORDER BY crash', (self.tkt.id,))
        self.crashes = set([int(num) for num, in cursor])
        self._old_crashes = copy.copy(self.crashes)

    def save(self, author, comment='', when=None, db=None):
        """Save new links."""
        if when is None:
            when = datetime.now(utc)
        when_ts = to_utimestamp(when)

        handle_commit = False
        if db is None:
            raise RuntimeError("need to pass db parameter")
            handle_commit = True
        cursor = db.cursor()

        new_crashes = set(int(n) for n in self.crashes)

        to_check = [
            # new, old, field
            (new_crashes, self._old_crashes, 'linked_crash', ('ticket', 'crash')),
        ]

        #print('_old_crashes=%s' % self._old_crashes)
        #print('new_crashes=%s' % new_crashes)

        for new_ids, old_ids, field, sourcedest in to_check:
            for n in new_ids | old_ids:
                update_field = None
                if n in new_ids and n not in old_ids:
                    # New ticket added
                    #print('INSERT INTO crashdump_ticket (%s, %s) VALUES (%%s, %%s)'%sourcedest, (self.tkt.id, n))
                    cursor.execute('INSERT INTO crashdump_ticket (%s, %s) VALUES (%%s, %%s)'%sourcedest, (self.tkt.id, n))
                    update_field = lambda lst: lst.add(n)
                elif n not in new_ids and n in old_ids:
                    # Old ticket removed
                    #print('DELETE FROM crashdump_ticket WHERE %s=%%s AND %s=%%s'%sourcedest, (self.tkt.id, n))
                    cursor.execute('DELETE FROM crashdump_ticket WHERE %s=%%s AND %s=%%s'%sourcedest, (self.tkt.id, n))
                    update_field = lambda lst: lst.discard(n)

                if update_field is not None:
                    cursor.execute('SELECT value FROM ticket_custom WHERE ticket=%s AND name=%s',
                                   (n, str(field)))
                    old_value_org = (cursor.fetchone() or ('',))[0]
                    if old_value_org is None:
                        old_value_org = ''
                    old_value = set([int(x.strip()) for x in old_value_org.split(',') if x.strip()])
                    new_value = old_value
                    #print('old_value=%s' % old_value)
                    #print('new_value=%s' % new_value)
                    update_field(new_value)
                    
                    if old_value != new_value:
                        old_value = old_value_org
                        if len(new_value) == 0:
                            new_value = None
                        else:
                            new_value = ', '.join(str(x) for x in sorted(new_value))
                    
                        #print('new_value_sorted=%s' % new_value)

                        #print('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                        #            (n, when_ts, author, field, old_value, new_value))
                        cursor.execute('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                                    (n, when_ts, author, field, old_value, new_value))

                        if comment:
                            #print('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                            #            (n, when_ts, author, 'comment', '', '(In #%s) %s'%(self.tkt.id, comment)))
                            cursor.execute('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                                        (n, when_ts, author, 'comment', '', '(In #%s) %s'%(self.tkt.id, comment)))

                        if new_value is not None:
                            cursor.execute('UPDATE ticket_custom SET value=%s WHERE ticket=%s AND name=%s',
                                        (new_value, n, field))

                            if not cursor.rowcount:
                                cursor.execute('INSERT INTO ticket_custom (ticket, name, value) VALUES (%s, %s, %s)',
                                            (n, field, new_value))
                        else:
                            cursor.execute('DELETE FROM ticket_custom WHERE ticket=%s AND name=%s',
                                        (n, field))

                    # refresh the changetime to prevent concurrent edits
                    cursor.execute('UPDATE ticket SET changetime=%s WHERE id=%s', (when_ts,n))

        # cursor.execute('DELETE FROM mastertickets WHERE source=%s OR dest=%s', (self.tkt.id, self.tkt.id))
        # data = []
        # for tkt in self.blocking:
        #     if isinstance(tkt, Ticket):
        #         tkt = tkt.id
        #     data.append((self.tkt.id, tkt))
        # for tkt in self.blocked_by:
        #     if isisntance(tkt, Ticket):
        #         tkt = tkt.id
        #     data.append((tkt, self.tkt.id))
        #
        # cursor.executemany('INSERT INTO mastertickets (source, dest) VALUES (%s, %s)', data)

        if handle_commit:
            db.commit()

    @staticmethod
    def tickets_for_crash(db, crashid):
        cursor = db.cursor()

        #print('tickets_for_crash db=%s, crashid=%s %s' % (db, crashid, type(crashid)))

        cursor.execute('SELECT ticket FROM crashdump_ticket WHERE crash=%s ORDER BY ticket', (crashid,))
        return set([int(num) for num, in cursor])

    def __repr__(self):
        def l(arr):
            arr2 = []
            for tkt in arr:
                if isinstance(tkt, Ticket):
                    tkt = tkt.id
                arr2.append(str(tkt))
            return '[%s]'%','.join(arr2)

        return '<crashdump.model.CrashDumpTicketLinks #%s crashes=%s>'% \
               (self.tkt.id, l(getattr(self, 'crashes', [])))

