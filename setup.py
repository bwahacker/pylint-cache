#!/usr/bin/env python3
"""Setup script for pylint-cache."""

from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="pylint-cache",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="A smart caching wrapper for pylint that avoids re-running checks on unchanged files",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/pylint-cache",
    py_modules=["pylint_cache", "pylint_cache_monitor"],
    entry_points={
        "console_scripts": [
            "pylint-cache=pylint_cache:main",
            "pylint-cache-monitor=pylint_cache_monitor:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Quality Assurance",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.7",
    install_requires=[
        "pylint>=2.0.0",
    ],
)

