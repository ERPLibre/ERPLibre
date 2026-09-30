#!/usr/bin/env bash

import sys
import xmlrpc.client

import click


def get_db_list_xmlrpc(odoo_url):
    """
    Retrieves the list of Odoo databases using the XML-RPC API: the names,
    possibly none, or None when the server cannot list them, the reason
    then written on stderr.
    """
    try:
        common = xmlrpc.client.ServerProxy(f"{odoo_url}/xmlrpc/db")
        db_list = common.list()
        return db_list
    except xmlrpc.client.Fault as e:
        print(
            f"XML-RPC Error: {e.faultCode} - {e.faultString}", file=sys.stderr
        )
        return None
    except Exception as e:
        print(f"Connection Error: {e}", file=sys.stderr)
        return None


# --- CLI using Click ---
@click.command()
@click.option(
    "--odoo-url",
    default="http://localhost:8069",
    help="URL of the Odoo server.",
    show_default=True,
)
@click.option(
    "--raw",
    is_flag=True,
    help="Output one database per line, without extra formatting. Useful for scripting.",
)
def list_databases(odoo_url, raw=False):
    """
    This script lists all available databases on an Odoo server.
    """
    if not raw:
        click.echo(f"Attempting to connect to Odoo at: {odoo_url}")

    databases = get_db_list_xmlrpc(odoo_url)

    # A failure writes nothing on stdout and exits 1: a caller reads each
    # line of stdout as a database name, and could not tell an error line
    # from a database.
    if databases is None:
        if not raw:
            click.echo("Failed to retrieve the database list.", err=True)
        sys.exit(1)

    if not raw:
        click.echo("\nAvailable databases:")
    for db in databases:
        if not raw:
            click.echo(f"- {db}")
        else:
            click.echo(db)


# --- Script Execution ---
if __name__ == "__main__":
    list_databases()
