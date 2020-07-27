from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="yet_another_oracle_doc_gen",
    version="1.0.0",
    packages=find_packages(),

    # Project uses reStructuredText, so ensure that the docutils get
    # installed or upgraded on the target machine
    install_requires=["cx_oracle>=7.3.0"],

    package_data={
        "": ["*.py", "*.lng"],
    },

    # metadata to display on PyPI
    author="Andrew Kuskov",
    author_email="qvant86@gmail.com",
    description="This is an yet another Oracle schema documentation generator/",
    keywords="Oracle documentation generator",
    url="https://github.com/qvant/yet_another_oracle_doc_gen",   # project home page, if any
    project_urls={
        "Bug Tracker": "https://github.com/qvant/yet_another_oracle_doc_gen/issues",
        "Documentation": "https://docs.example.com/HelloWorld/",
        "Source Code": "https://github.com/qvant/yet_another_oracle_doc_gen",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent"
    ],
    python_requires='>=3.6',
    long_description=long_description,
    long_description_content_type="text/markdown"

)