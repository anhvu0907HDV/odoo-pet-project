# -*- coding: utf-8 -*-
{
    'name': "Real Estate",
    'version': '1.1.0',
    'application': True,
    'summary': "Manage properties and offers",

    'description': """
Interview-ready real estate pet project:
- Property pipeline from listing to sold/cancelled
- Offer management with acceptance/refusal flow
- Search, filter and grouped views for quick analysis
- Property type/tag master data and analytics dashboards
- Role-based access matrix and interview-oriented UX polish
    """,

    'author': "Pet Project",
    'website': "https://example.com",
    'category': 'Sales',

    'depends': ['base', 'mail'],

    'data': [
        'security/estate_security.xml',
        'security/ir.model.access.csv',
        'data/mail_templates.xml',
        'data/cron.xml',
        'views/property_type_views.xml',
        'views/property_views.xml',
        'views/property_search.xml',
        'views/property_offer_views.xml',
        'views/property_report_views.xml',
        'views/report_export_views.xml',
        'views/report_pdf_templates.xml',
        'views/res_config_settings_views.xml',
        'views/menu.xml',
    ],
    'demo': [
        'demo/demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'estate/static/src/scss/estate_kanban.scss',
        ],
    },
}
