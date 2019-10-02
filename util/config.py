import os
import json
import boto3
import base64
from botocore.exceptions import ClientError

basedir = os.path.abspath(os.path.dirname(__file__))

class Config(object):
    AWS_REGION_NAME = 'us-east-1'
    GAS_LOG_LEVEL = os.environ['GAS_LOG_LEVEL'] if ('GAS_LOG_LEVEL' in os.environ) else 'INFO'
    GAS_LOG_FILE_PATH = basedir + (os.environ['GAS_LOG_FILE_PATH'] if ('GAS_LOG_FILE_PATH' in os.environ) else "/log")
    GAS_LOG_FILE_NAME = os.environ['GAS_LOG_FILE_NAME'] if ('GAS_LOG_FILE_NAME' in os.environ) else "gas.log"
    WSGI_SERVER = 'werkzeug'
    CSRF_ENABLED = True
    asm = boto3.client('secretsmanager', region_name=AWS_REGION_NAME)
    try:
        asm_response = asm.get_secret_value(SecretId='rds/accounts_database')
        rds_secret = json.loads(asm_response['SecretString'])
    except ClientError as e:
        print(f"Unable to retrieve RDS credentials from AWS Secrets Manager: {e}")
        raise e
    
    AWS_SCANNING_TIME = 15
    FREE_USER_DATA_RETENTION = 600 # time before free user results are archived (in seconds)
    MAIL_DEFAULT_SENDER = "zyx@ucmpcs.org"
    MAIL_DEFAULT_RECEIVER = '5256haha@gmail.com'
    AWS_SQS_JOB_COMPLETE = 'zyx_job_results'
    AWS_SQS_ARCHIVE_COMPLETE = 'zyx_archive_results'
    AWS_SQS_RESTORE = 'zyx_restore_results'
    AWS_SQS_RESTORE_COMPLETE = 'zyx_restore_complete'
    AWS_URL_PREFIX = 'https://zyx.ucmpcs.org/'

    AWS_SNS_JOB_RESTORE_COMPLETE_TOPIC = "arn:aws:sns:us-east-1:127134666975:zyx_restore_complete"

    AWS_S3_RESULTS_BUCKET= 'gas-results'
    AWS_GLACIER_VAULT = 'ucmpcs'
    AWS_DYNAMODB_ANNOTATIONS_TABLE = 'zyx_annotations'
