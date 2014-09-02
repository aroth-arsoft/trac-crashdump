import copy
from trac.util.compat import set, sorted
from trac.util.datefmt import from_utimestamp, to_utimestamp, utc, utcmax
from trac.ticket.model import Ticket

class CrashDumpTicketLinks(object):
    """A model for the ticket to crash links used TracCrashDump."""

    def __init__(self, env, tkt, db=None):
        self.env = env
        if not isinstance(tkt, Ticket):
            tkt = Ticket(self.env, tkt)
        self.tkt = tkt

        db = db or self.env.get_db_cnx()
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
            db = self.env.get_db_cnx()
            handle_commit = True
        cursor = db.cursor()

        new_crashes = set(int(n) for n in self.crashes)

        to_check = [
            # new, old, field
            (new_crashes, self._old_crashes, 'linked_crash', ('ticket', 'crash')),
        ]

        for new_ids, old_ids, field, sourcedest in to_check:
            for n in new_ids | old_ids:
                update_field = None
                if n in new_ids and n not in old_ids:
                    # New ticket added
                    cursor.execute('INSERT INTO crashdump_ticket (%s, %s) VALUES (%%s, %%s)'%sourcedest, (self.tkt.id, n))
                    update_field = lambda lst: lst.append(str(self.tkt.id))
                elif n not in new_ids and n in old_ids:
                    # Old ticket removed
                    cursor.execute('DELETE FROM crashdump_ticket WHERE %s=%%s AND %s=%%s'%sourcedest, (self.tkt.id, n))
                    update_field = lambda lst: lst.remove(str(self.tkt.id))

                if update_field is not None:
                    cursor.execute('SELECT value FROM ticket_custom WHERE ticket=%s AND name=%s',
                                   (n, str(field)))
                    old_value = (cursor.fetchone() or ('',))[0]
                    new_value = [x.strip() for x in old_value.split(',') if x.strip()]
                    update_field(new_value)
                    new_value = ', '.join(sorted(new_value, key=lambda x: int(x)))

                    cursor.execute('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                                   (n, when_ts, author, field, old_value, new_value))

                    if comment:
                        cursor.execute('INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue) VALUES (%s, %s, %s, %s, %s, %s)',
                                       (n, when_ts, author, 'comment', '', '(In #%s) %s'%(self.tkt.id, comment)))


                    print('UPDATE ticket_custom SET value=%s WHERE ticket=%s AND name=%s'%
                                   (new_value, n, field))
                    cursor.execute('UPDATE ticket_custom SET value=%s WHERE ticket=%s AND name=%s',
                                   (new_value, n, field))

                    if not cursor.rowcount:
                        print('INSERT INTO ticket_custom (ticket, name, value) VALUES (%s, %s, %s)'%
                                       (n, field, new_value))
                        cursor.execute('INSERT INTO ticket_custom (ticket, name, value) VALUES (%s, %s, %s)',
                                       (n, field, new_value))

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

