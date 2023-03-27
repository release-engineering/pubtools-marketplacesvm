# SPDX-License-Identifier: GPL-3.0-or-later
from setuptools import setup, find_packages


def get_description():
    return "Publishing tools for various Cloud Marketplaces"


def get_long_description():
    with open("README.md") as f:
        text = f.read()

    # Long description is everything after README's initial heading
    idx = text.find("\n\n")
    return text[idx:]


def get_requirements():
    with open("requirements.txt") as f:
        return f.read().splitlines()


setup(
    name="pubtools-marketplacesvm",
    version="0.1.1",
    packages=find_packages(exclude=["tests"]),
    url="https://gitlab.cee.redhat.com/stratosphere/pubtools-marketplacesvm",
    license="GPLv3+",
    description=get_description(),
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    install_requires=get_requirements(),
    entry_points={
        "console_scripts": [
            "pubtools-marketplacesvm-push = pubtools._marketplacesvm.tasks.push:entry_point",
        ]
    },
    zip_safe=False,
)
