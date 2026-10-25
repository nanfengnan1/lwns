"""Sphinx configuration for the lwns user and developer guides."""
from pathlib import Path
import re


def _get_release():
    version_file = Path(__file__).resolve().parent / '.version'
    value = version_file.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value):
        raise ValueError('Invalid or empty docs/.version')
    return value


project = 'lwns 文档'
author = 'lwns 项目组'
copyright = '2026, lwns 项目组'
release = _get_release()
version = release
language = 'zh_CN'
root_doc = 'index'

extensions = ['sphinx_rtd_theme']
html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'navigation_depth': 3,
    'collapse_navigation': True,
}
exclude_patterns = [
    'html', 'pdf', '_build', 'versions', '_scripts', '.venv',
    '**/__pycache__', 'Thumbs.db', '.DS_Store',
]
html_static_path = ['_static']
templates_path = ['_templates']
html_js_files = ['version-config.js', 'version-switch.js', 'reading.js']
html_css_files = ['version-switch.css', 'reading.css']

latex_engine = 'xelatex'
latex_documents = [
    ('user/index', 'lwns-user.tex', 'lwns 用户指南', author, 'manual'),
    ('developer/index', 'lwns-dev.tex', 'lwns 开发指南', author, 'manual'),
]
