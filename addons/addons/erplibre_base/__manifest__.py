# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'ERPLibre base',
    'version': '0.1',
    'author': "ERPLibre",
    'website': 'https://erplibre.ca',
    'license': 'AGPL-3',
    'category': 'Human Resources',
    'summary': 'INSTALL my base',
    'description': """
ERPLibreBase
===============

""",
    'depends': [
        # Custom ERPLibre
        # OCA
        'web_responsive',

        # OCA server-brand
        'disable_odoo_online',
        'remove_odoo_enterprise',

        # OCA website
        'website_odoo_debranding',
        'website_no_crawler',

        # Server-tools
        'fetchmail_notify_error_to_sender',

        # Social
        'mail_debrand',

        # Partner
        'partner_quebec_tz',
    ],
    'data': [],
    'installable': True,
}
