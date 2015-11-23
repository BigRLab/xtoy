import sh
import re

commit_count = sh.git('rev-list', ['--all']).count('\n')

with open('setup.py') as f:
    setup = f.read()

setup = re.sub("MICRO_VERSION = '[0-9]+'", "MICRO_VERSION = '{}'".format(commit_count), setup)

major = re.search("MAJOR_VERSION = '([0-9]+)'", setup).groups()[0]
minor = re.search("MINOR_VERSION = '([0-9]+)'", setup).groups()[0]
micro = re.search("MICRO_VERSION = '([0-9]+)'", setup).groups()[0]
version = '{}.{}.{}'.format(major, minor, micro)

with open('setup.py', 'w') as f:
    f.write(setup)

with open('xtoy/__init__.py') as f:
    init = f.read()

with open('xtoy/__init__.py', 'w') as f:
    f.write(re.sub('__version__ = "[0-9.]+"', '__version__ = "{}"'.format(version), init))

print(sh.python3('setup.py', ['bdist_wheel', 'upload']))

sh.cd('../')

sh.pip3('install', ['-U', 'xtoy'])
