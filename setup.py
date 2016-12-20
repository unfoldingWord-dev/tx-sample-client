from setuptools import setup, find_packages
from codecs import open
from os import path

setup(
    name="tx-sample-client",
    version="1.0.0",
    description="Sample Client",
    long_description="Sample Client",
    url="https://github.com/unfoldingWord-dev/tx-sample-client",
    author="unfoldingWord",
    author_email="info@door43.org",
    license="MIT",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2.7",
    ],
    keywords=["client"],
    packages=find_packages(),
    install_requires=["future", "requests"],
    test_suite="tests"
)
