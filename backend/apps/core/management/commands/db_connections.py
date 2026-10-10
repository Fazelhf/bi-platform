"""
Who is holding PostgreSQL's connection slots?

    python manage.py db_connections

When the server answers 500 with «remaining connection slots are reserved for
non-replication superuser connections», the database has hit max_connections.
On a shared cPanel host that limit is shared with every other account, so the
first question is whose connections they are: this site's, an old process of
this site that never let go, or another account entirely.
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Count PostgreSQL connections by user, database and state."

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            cur.execute("show max_connections")
            limit = cur.fetchone()[0]
            cur.execute("show superuser_reserved_connections")
            reserved = cur.fetchone()[0]
            cur.execute("select current_user, current_database()")
            me, db = cur.fetchone()
            cur.execute(
                """
                select coalesce(usename, '-'), coalesce(datname, '-'),
                       coalesce(state, '-'), count(*),
                       max(now() - coalesce(state_change, backend_start))
                from pg_stat_activity
                group by 1, 2, 3
                order by 4 desc
                """
            )
            rows = cur.fetchall()
            # Our own connections in detail: an «idle in transaction» or a
            # very old one points at a process that is stuck, not at load.
            cur.execute(
                """
                select pid, coalesce(state, '-'), coalesce(application_name, ''),
                       coalesce(client_addr::text, 'local'),
                       now() - backend_start, now() - coalesce(state_change, backend_start)
                from pg_stat_activity
                where usename = current_user and pid <> pg_backend_pid()
                order by backend_start
                """
            )
            mine = cur.fetchall()

        total = sum(r[3] for r in rows)
        self.stdout.write(
            f"max_connections={limit} (superuser reserved {reserved}) · in use now={total}"
        )
        self.stdout.write(f"this site: user={me} db={db}\n")
        self.stdout.write(f"{'user':<20} {'database':<24} {'state':<22} {'count':>5}  oldest")
        for user, dbname, state, count, oldest in rows:
            mark = "  ← this site" if user == me else ""
            self.stdout.write(
                f"{user:<20} {dbname:<24} {state:<22} {count:>5}  {oldest}{mark}"
            )
        self.stdout.write(f"\nthis site's own connections ({len(mine)}):")
        for pid, state, app, addr, age, idle in mine:
            self.stdout.write(f"  pid={pid} {state:<20} age={age} in-state={idle} {app} {addr}")
