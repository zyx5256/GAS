#!/bin/bash                                                                                         
export WORKON_HOME=/home/ubuntu/.virtualenvs
source /usr/local/bin/virtualenvwrapper.sh
cd /home/ubuntu/
source /home/ubuntu/.env
workon mpcs
python annotator.py &