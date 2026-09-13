{
    'name': 'Hide Enterprise Modules',
    'version': '1.0',
    'category': 'Hidden',
    'summary': 'Hide enterprise modules from Apps menu',
    'description': '''
    This module hides enterprise modules (to_buy=True) from the Apps menu
    while keeping the enterprise flag for grouping purposes.
    ''',
    'depends': ['base'],
    'data': [
        'views/ir_module_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
