#!/usr/bin/env bash

import xmlrpc.client
import sys
import click


def get_db_list_xmlrpc(odoo_url):
    """
    Retrieves the list of Odoo databases using the XML-RPC API.
    """
    try:
        common = xmlrpc.client.ServerProxy(f'{odoo_url}/xmlrpc/db')
        db_list = common.list()
        return db_list
    except xmlrpc.client.Fault as e:
        print(f"XML-RPC Error: {e.faultCode} - {e.faultString}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Connection Error: {e}", file=sys.stderr)
        return []

# --- CLI using Click ---
@click.command()
@click.option(
    '--odoo-url',
    default='http://localhost:8069',
    help='URL of the Odoo server.',
    show_default=True
)
@click.option(
    '--raw',
    is_flag=True,
    help='Output one database per line, without extra formatting. Useful for scripting.'
)
def list_databases(odoo_url, raw=False):
    """
    This script lists all available databases on an Odoo server.
    """
    if not raw:
        click.echo(f"Attempting to connect to Odoo at: {odoo_url}")

    databases = get_db_list_xmlrpc(odoo_url)

    if databases:
        if not raw:
            click.echo("\nAvailable databases:")
        for db in databases:
            if not raw:
                click.echo(f"- {db}")
            else:
                click.echo(db)
    else:
        if not raw:
            click.echo("Failed to retrieve the database list.")


# --- Script Execution ---
if __name__ == '__main__':
    list_databases()
