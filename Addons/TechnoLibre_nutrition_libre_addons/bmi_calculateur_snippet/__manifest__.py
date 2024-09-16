
{
    'name': 'BMI Calculateur Snippet',
    "version": "16.0.1.0.1",
    'summary': 'Calculateur de IMC et Percentile',
    'description': """Ce bout de code ajoute une fonctionnalité à votre site web : un calculateur d'IMC et de percentiles pour enfants..""",
    'category': 'Website',
    'author': 'Adil',
    'website': 'http://www.votre-website.com',
    'depends': ['website'], # Assure-toi que le module 'website' est installé
    'data': [
        'views/assets.xml',  # Chemin des assets pour le CSS et JS
        'views/snippet_templates.xml',  # Fichier template pour les snippets
    ],
    'assets': {
        'web.assets_frontend': [
            # Utilisation des chemins complets pour CSS et JS
            'bmi_calculateur_snippet/static/src/css/snippet_style.css',
            'bmi_calculateur_snippet/static/src/js/bmi_calculator.js',
        ],
    },
    'application': True,  # Si tu veux que ce soit une application visible
    'installable': True,
    'license': 'LGPL-3',
}