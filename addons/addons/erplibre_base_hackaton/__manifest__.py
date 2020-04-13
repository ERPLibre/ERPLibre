# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'ERPLibre base hackaton',
    'version': '0.1',
    'author': "ERPLibre",
    'website': 'https://erplibre.ca',
    'license': 'AGPL-3',
    'category': 'Human Resources',
    'summary': 'INSTALL my base hackaton',
    'description': """
ERPLibreBase
===============

""",
    'depends': [
        # Custom ERPLibre
        'erplibre_base',

        'res_partner_fix_group_by_company',
        'crm_filter_all',

        'helpdesk_service_call',
        'website_helpdesk',
        'website_portal_contact',
        'website_portal_address',

        # Odoo base
        'account',

        'board',

        'contacts',

        'crm',

        'portal',

        'payment',
        'payment_transfer',

        'project',

        'website',
        'website_crm',

        # OCA
        'website_form_builder',
        'website_snippet_anchor',
        'partner_no_vat',

        # Numigi
        'project_chatter',
        # 'project_iteration',

        # Canada
        'l10n_ca',

        # Scrummer
        'project_agile_sale_timesheet',
        'scrummer',
        'scrummer_kanban',
        'scrummer_scrum',
        'scrummer_workflow_security',
        'scrummer_workflow_transition_by_project',
        'scrummer_workflow_transitions_by_task_type',

        # OCA helpdesk
        'helpdesk_mgmt',
    ],
    'data': [],
    'installable': True,
}
