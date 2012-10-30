import os
from setuptools import setup, find_packages

version='0.3.3'

install_requires = [
    'gevent',
    'gevent-websocket',
]

tests_require = install_requires + ['nose']

def read(f):
    return open(os.path.join(os.path.dirname(__file__), f)).read().strip()

setup(name='sockjs-gevent',
      version=version,
      description=('gevent base sockjs server'),
      long_description='\n\n'.join((read('README.md'), read('CHANGES.txt'))),
      classifiers=[
          "Intended Audience :: Developers",
          "Programming Language :: Python",
          "Programming Language :: Python :: 2.6",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: Implementation :: CPython",
          "Topic :: Internet :: WWW/HTTP",
          'Topic :: Internet :: WWW/HTTP :: WSGI'],
      author='Nick Joyce',
      author_email='nick@boxdesign.co.uk',
      url='https://github.com/sdiehl/sockjs-gevent',
      license='MIT',
      packages=find_packages(),
      install_requires = install_requires,
      tests_require = tests_require,
      test_suite = 'nose.collector',
      include_package_data = True,
      zip_safe = False,
      entry_points = {
          'console_scripts': [
              'sockjs-server = gevent_sockjs.server:main',
              ],
          },
      )
