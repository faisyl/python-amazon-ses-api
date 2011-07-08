#!/usr/bin/env python

try:
    from setuptools import setup
except ImportError, excp:
    from distutils.core import setup
                    
import amazon_ses
import os

setup(  name='amazon-ses',
        description = 'Python API for Amazon Simple Email Service',
        author= 'Vladimir Pankratiev',
        url = 'http://tagmask.com/vladimir/profile',
        download_url = 'https://github.com/kbandla/python-amazon-ses-api',
        platforms = ['any'],
        py_modules = ['amazon_ses'] 
        )
