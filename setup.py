import sys
import tomllib
from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f.read().splitlines() if line.strip()]

SKIP_MYPYC = any(
    cmd in sys.argv
    for cmd in ("sdist", "egg_info", "--name", "--version", "--help", "--help-commands")
)

if SKIP_MYPYC:
    ext_modules = []
else:
    from mypyc.build import mypycify

    with (this_directory / "pyproject.toml").open("rb") as config_file:
        mypyc_args = tomllib.load(config_file)["tool"]["mypyc"]["files"]

    ext_modules = mypycify(mypyc_args, group_name="ypricemagic")


setup(
    name="ypricemagic",
    packages=find_packages(exclude=["tests", "tests.*"]),
    use_scm_version={
        "root": ".",
        "relative_to": __file__,
        "local_scheme": "no-local-version",
        "version_scheme": "python-simplified-semver",
    },
    description="Use this tool to extract historical on-chain price data from an archive node. Shoutout to @bantg and @nymmrx for their awesome work on yearn-exporter that made this library possible.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="BobTheBuidler",
    author_email="bobthebuidlerdefi@gmail.com",
    url="https://github.com/BobTheBuidler/ypricemagic",
    license="MIT",
    python_requires=">=3.11,<3.14",
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: Implementation :: CPython",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries",
    ],
    setup_requires=["setuptools_scm"],
    install_requires=requirements,
    package_data={"y": ["py.typed"]},
    include_package_data=True,
    entry_points={"console_scripts": ["ypricemagic=y.cli:main"]},
    ext_modules=ext_modules,
    zip_safe=False,
)
