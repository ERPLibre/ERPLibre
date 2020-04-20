# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'ERPLibre base enterprise',
    'version': '0.1',
    'author': "ERPLibre",
    'website': 'https://erplibre.ca',
    'license': 'AGPL-3',
    'category': 'Human Resources',
    'summary': 'INSTALL my base enterprise',
    'description': """
ERPLibreBase
===============

""",
    'depends': [
        # Custom ERPLibre
        'erplibre_base',

        'hr_expense_associate_with_customer',
        'hr_expense_tip',

        'sale_order_line_limit',

        'res_partner_fix_group_by_company',
        'configure_quebec_tax',
        'crm_filter_all',
        'sale_degroup_tax',

        'helpdesk_mailing_list',

        # Odoo base
        'account',

        'board',

        'contacts',

        'crm',

        'portal',

        'payment',
        'payment_transfer',

        'project',

        'purchase',

        'hr',
        'hr_expense',
        'hr_org_chart',

        'website',
        'website_crm',

        'sale',
        'sale_management',
        'stock',

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
    ],
    'data': [],
    'installable': True,
}
