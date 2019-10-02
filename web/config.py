# auth.py
#
# Copyright (C) 2011-2018 Vas Vasiliadis
# University of Chicago
#
# Set GAS configuration options based on environment
#
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import os
import json
import boto3
import base64
from botocore.exceptions import ClientError

basedir = os.path.abspath(os.path.dirname(__file__))

class Config(object):  
  GAS_LOG_LEVEL = os.environ['GAS_LOG_LEVEL'] if ('GAS_LOG_LEVEL' in os.environ) else 'INFO'
  GAS_LOG_FILE_PATH = basedir + (os.environ['GAS_LOG_FILE_PATH'] if ('GAS_LOG_FILE_PATH' in os.environ) else "/log")
  GAS_LOG_FILE_NAME = os.environ['GAS_LOG_FILE_NAME'] if ('GAS_LOG_FILE_NAME' in os.environ) else "gas.log"

  WSGI_SERVER = 'werkzeug'
  
  CSRF_ENABLED = True
  SECRET_KEY = os.environ['SECRET_KEY']
  SSL_CERT_PATH = os.environ['SSL_CERT_PATH'] if ('SSL_CERT_PATH' in os.environ) else "../ssl/server_dev.crt"
  SSL_KEY_PATH = os.environ['SSL_KEY_PATH'] if ('SSL_KEY_PATH' in os.environ) else "../ssl/server_dev.key"

  GAS_HOST_IP = os.environ['GAS_HOST_IP']
  GAS_HOST_PORT = int(os.environ['GAS_HOST_PORT'])
  GAS_APP_HOST = os.environ['GAS_APP_HOST']
  GAS_SERVER_NAME = os.environ['GAS_HOST_IP'] + ":" + os.environ['GAS_HOST_PORT']
  
  GAS_CLIENT_ID = os.environ['GAS_CLIENT_ID']
  GAS_CLIENT_SECRET = os.environ['GAS_CLIENT_SECRET']
  GLOBUS_AUTH_LOGOUT_URI = 'https://auth.globus.org/v2/web/logout'

  AWS_PROFILE_NAME = os.environ['AWS_PROFILE_NAME'] if ('AWS_PROFILE_NAME' in  os.environ) else None
  AWS_REGION_NAME = os.environ['AWS_REGION_NAME'] if ('AWS_REGION_NAME' in  os.environ) else "us-east-1"

  # Get RDS secret from AWS Secrets Manager and construct database URI
  asm = boto3.client('secretsmanager', region_name=AWS_REGION_NAME)
  try:
    asm_response = asm.get_secret_value(SecretId='rds/accounts_database')
    rds_secret = json.loads(asm_response['SecretString'])
  except ClientError as e:
    print(f"Unable to retrieve RDS credentials from AWS Secrets Manager: {e}")
    raise e

  SQLALCHEMY_DATABASE_TABLE = os.environ['ACCOUNTS_DATABASE_TABLE']
  SQLALCHEMY_DATABASE_URI = "postgresql://" + rds_secret['username'] + ':' + rds_secret['password'] + \
    '@' + rds_secret['host'] + ':' + str(rds_secret['port']) + '/' + SQLALCHEMY_DATABASE_TABLE
  SQLALCHEMY_TRACK_MODIFICATIONS = True

  AWS_SIGNED_REQUEST_EXPIRATION = 300  # validity of pre-signed POST requests (in seconds)

  AWS_S3_INPUTS_BUCKET = "gas-inputs"
  AWS_S3_RESULTS_BUCKET = "gas-results"
  # Set the S3 key (object name) prefix to your CNetID
  # Keep the trailing '/' if using my upload code in views.py
  AWS_S3_KEY_PREFIX = "zyx/"
  AWS_S3_ACL = "private"
  AWS_S3_ENCRYPTION = "AES256"

  AWS_GLACIER_VAULT = "ucmpcs"

  # Change the ARNs below to reflect your SNS topics
  AWS_SNS_JOB_REQUEST_TOPIC = "arn:aws:sns:us-east-1:127134666975:zyx_job_requests"
  AWS_SNS_JOB_COMPLETE_TOPIC = "arn:aws:sns:us-east-1:127134666975:zyx_job_results"
  AWS_SNS_JOB_RESTORE_TOPIC = "arn:aws:sns:us-east-1:127134666975:zyx_restore_results"
  AWS_JOB_LIMIT = 150000

  # Change the table name to your own
  AWS_DYNAMODB_ANNOTATIONS_TABLE = "zyx_annotations"
  AWS_URL_PREFIX = 'https://zyx.ucmpcs.org/'

  # Stripe API keys
  STRIPE_PUBLIC_KEY = "pk_test_vQM07vzFhfRFbVdRAplA3a9I00YlASsK0F"
  STRIPE_SECRET_KEY = "sk_test_22PA8yyXXlxaZVsAErDxt2BT00yXFamUpy"

  # Change the email address to your username
  MAIL_DEFAULT_SENDER = "zyx@ucmpcs.org"

  FREE_USER_DATA_RETENTION = 600 # time before free user results are archived (in seconds)

class DevelopmentConfig(Config):
  DEBUG = True
  GAS_LOG_LEVEL = 'DEBUG'

class ProductionConfig(Config):
  DEBUG = False
  GAS_LOG_LEVEL = 'INFO'
  WSGI_SERVER = 'gunicorn.error'
  SSL_CERT_PATH = os.environ['SSL_CERT_PATH'] if ('SSL_CERT_PATH' in os.environ) else "/usr/local/src/ssl/ucmpcs.org.crt"
  SSL_KEY_PATH = os.environ['SSL_KEY_PATH'] if ('SSL_KEY_PATH' in os.environ) else "/usr/local/src/ssl/ucmpcs.org.key"

class StagingConfig(Config):
  STAGING = True

class TestingConfig(Config):
  TESTING = True

### EOF
