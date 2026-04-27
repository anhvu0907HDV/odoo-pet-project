# -*- coding: utf-8 -*-
{
    'name': "Real Estate",
    'version': '1.0.0',
    'application': True,
    'summary': "Manage properties and offers",

    'description': """
Interview-ready real estate pet project:
- Property pipeline from listing to sold/cancelled
- Offer management with acceptance/refusal flow
- Search, filter and grouped views for quick analysis
    """,

    'author': "Pet Project",
    'website': "https://example.com",
    'category': 'Sales',

    'depends': ['base', 'mail'],

    'data': [
        'security/estate_security.xml',
        'security/ir.model.access.csv',
        'views/property_views.xml',
        'views/property_search.xml',
        'views/property_offer_views.xml',
        'views/menu.xml',
    ],
    'demo': [
        'demo/demo.xml',
    ],
}
