import os
import sys
from setuptools import setup, find_packages

version='0.3.3'


def get_package_manifest(filename):
    packages = []

    with open(filename) as package_file:
        for line in package_file.readlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith('#'):
                # comment
                continue

            if line.startswith('-e '):
                # not a valid package
                continue

            packages.append(line)

    return packages


def get_install_requires():
    """
    :returns: A list of packages required for installation.
    """
    return get_package_manifest('requirements.txt')


def get_tests_requires():
    """
    :returns: A list of packages required for running the tests.
    """
    packages = get_package_manifest('requirements_dev.txt')

    try:
        from unittest import mock
    except ImportError:
        packages.append('mock')

    if sys.version_info[:2] < (2, 7):
        packages.append('unittest2')

    return packages


def read(f):
    with open(os.path.join(os.path.dirname(__file__), f)) as f:
        return f.read().strip()


setup(
    name='sockjs-gevent',
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
        'Topic :: Internet :: WWW/HTTP :: WSGI'
    ],
    author='Nick Joyce',
    author_email='nick.joyce@realkinetic.com',
    url='https://github.com/njoyce/sockjs-gevent',
    license='MIT',
    install_requires=get_install_requires(),
    tests_require=get_tests_requires(),
    setup_requires=['nose>=1.0'],
    test_suite='nose.collector',
    include_package_data = True,
    packages=find_packages(exclude=["examples", "tests"]),
    zip_safe = False,
)
