{
    'name': 'Tailor Management',
    'version': '1.0',
    'summary': 'Manage tailoring business operations',
    'description': 'Module to manage tailoring orders, users, and roles.',
    'author': 'Uwizeye Tresor',
    'category': 'Sales',
    'depends': ['base', 'sale', 'portal','mrp', 'website','stock','web'],  # <- sale and mrp are required
    'data': [
        'views/email.xml',
        'data/email_template.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/customer_documents_rules.xml',
        'security/tailor_order_rules.xml',

        'views/tailor_order_views.xml',
        'views/portal_tailor_orders.xml',
        'views/res_partner_views.xml',
        'views/mrp_production_tailor.xml',
        'views/sale_order_views.xml', # <- your sales order view



        "views/showroom_dashboard_views.xml",
        "views/production_dashboard_views.xml",
        "views/dashboard_actions.xml",
        "views/tailor_finance_reports_views.xml",
        'views/tailor_reports_views.xml',
        'views/message.xml',




    ],
    'assets':{
        'web.assets_backend': [
            'tailor_management/static/src/scss/tailor_form.scss',
            "tailor_management/static/src/js/executive_dashboard.js",
            "tailor_management/static/src/xml/executive_dashboard.xml",
            "tailor_management/static/src/scss/executive_dashboard.scss",
            "tailor_management/static/src/js/showroom_dashboard.js",
            "tailor_management/static/src/xml/showroom_dashboard.xml",
            "tailor_management/static/src/scss/showroom_dashboard.scss",
            "tailor_management/static/src/js/production_dashboard.js",
            "tailor_management/static/src/xml/production_dashboard.xml",
            "tailor_management/static/src/scss/production_dashboard.scss",
        ],
    },

    'i18n': [
        'i18n/ar.po',
        ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
