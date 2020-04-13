# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'ERPLibre base entreprise MRP',
    'version': '0.1',
    'author': "ERPLibre",
    'website': 'https://erplibre.ca',
    'license': 'AGPL-3',
    'category': 'Human Resources',
    'summary': 'INSTALL my base entreprise MRP',
    'description': """
ERPLibreBase
===============

""",
    'depends': [
        # Custom ERPLibre
        'erplibre_base',

        'res_partner_fix_group_by_company',
        'crm_filter_all',

        'website_helpdesk',
        'website_portal_contact',
        'website_portal_address',
        'product_manufacturer_model',
        'helpdesk_mailing_list',
        'helpdesk_join_team',

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
        'helpdesk_mgmt',
        'helpdesk_service_call',
        'helpdesk_supplier',

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

        # OCA manufacture
        'mrp_auto_assign',
        'mrp_bom_component_menu',
        'mrp_bom_line_sequence',
        'mrp_bom_location',
        'mrp_bom_tracking',
        'mrp_multi_level',
        'mrp_multi_level_estimate',
        'mrp_production_putaway_strategy',
        'mrp_production_request',
        'mrp_production_auto_post_inventory',
        'mrp_production_grouped_by_product',
        'mrp_stock_orderpoint_manual_procurement',
        'mrp_unbuild_tracked_raw_material',
        'mrp_workorder_sequence',
        'repair_refurbish',

        # OCA stock-logistics-warehouse
        'mrp_warehouse_calendar',
        'stock_available_mrp',
        'stock_orderpoint_mrp_link',

        # OCA contract
        'agreement_mrp',

        # OCA account-analytic
        'mrp_analytic',

        # ODOO S.A.
        'mrp',
        'helpdesk_mrp',
        'mrp_byproduct',
        'mrp_workcenters_machines',
        'product_mrp_info',
        'purchase_mrp',
        'sale_mrp',
        'mrp_bom_cost',
        'res_partner_supplier_own_mrp_work_centers',

    ],
    'data': [],
    'installable': True,
}
