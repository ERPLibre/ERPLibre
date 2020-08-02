#!./.venv/bin/python
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
    arg_parser.add_argument('--db_name', required=False, default="postgres")
    arg_parser.add_argument('--timeout', type=int, default=10)

    args = arg_parser.parse_args()

    start_time = time.time()
    print("Try connection to postgres...")

    connected = False
    error = ''
    while ((time.time() - start_time) < args.timeout) or connected is True:
        try:
            conn = psycopg2.connect(user=args.db_user, host=args.db_host,
                                    port=args.db_port, password=args.db_password,
                                    dbname=args.db_name)
            break
        except psycopg2.OperationalError as e:
            error = e
            print(".")
            time.sleep(1)
        else:
            connected = True
            conn.close()
    if error:
        print("Database connection failure: %s" % error, file=sys.stderr)
        sys.exit(1)
