# Publishing a new version:
#
# 1. Update the version tag in this file.
# 2. Remove the `dist/` and the `machetli.egg-info` directories
# 3. Run the following steps (needs `pip install build twine`):
#
#     $ python3 -m build
#     $ python3 -m twine upload dist/*
#
# 4. Enter the API token

from setuptools import setup, find_packages

with open("README.rst", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="machetli",
    version="0.9.1337",
    description="Locate bugs in your program",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    author="Lucas Galery Käser",
    author_email="lucas.galerykaeser@gmail.com",
    url="https://github.com/aibasel/machetli",
    license="GPL3+",
    project_urls={
        "Documentation": "https://machetli.readthedocs.io/",
    },
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Scientific/Engineering",
    ],
    packages=find_packages(),
    python_requires=">=3.7",
    include_package_data=True,
    package_data={
        "machetli": ["templates/slurm-array-job.template"],
    },
)
