import os
from pecan.deploy import deploy

application = deploy('/etc/cauth/config.py')
