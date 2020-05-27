#!/usr/bin/env python3
import argparse
import psycopg2
import sys
import time


if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--db_host', required=True)
    arg_parser.add_argument('--db_port', required=True)
    arg_parser.add_argument('--db_user', required=True)
    arg_parser.add_argument('--db_password', required=True)
    # arg_parser.add_argument('--db_name', required=True)
    arg_parser.add_argument('--timeout', type=int, default=5)

    args = arg_parser.parse_args()

    start_time = time.time()
    print("Try connection to postgres...")

    connected = False
    error = ''
    while ((time.time() - start_time) < args.timeout ) or connected is True:
        try:

            conn = psycopg2.connect(user=args.db_user, host=args.db_host, port=args.db_port, password=args.db_password, dbname="odoo")

            break
        except psycopg2.OperationalError as e:
            error = e
        else:
            connected = True
            conn.close()
        print(".")
        time.sleep(1)

    if error:
        print("Database connection failure: %s" % error, file=sys.stderr)
        sys.exit(1)
