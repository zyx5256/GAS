import boto3,json, sys
from config import Config
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

def update_DB(job_id):

  try:
    dynamoDB=boto3.resource('dynamodb', region_name=Config.AWS_REGION_NAME)
  except ClientError as e:
    print(str(e))
    return 0

  try:
    ann_table=dynamoDB.Table(Config.AWS_DYNAMODB_ANNOTATIONS_TABLE)
  except ClientError as e:
    print(str(e))
    return 0

  try:
    ann_table.update_item(
      Key={'job_id':job_id},
      UpdateExpression="REMOVE results_file_archive_id",
      ConditionExpression='attribute_exists(results_file_archive_id)'
    )
  except ClientError as e:
    print("error 500: fail to delete ArchiveId: "+str(e))
    return 0

  return 1

def send_email_ses(recipients=None, sender=None, subject=None, body=None):

  try:
    ses = boto3.client('ses', region_name=Config.AWS_REGION_NAME)
  except ClientError as e:
    print(str(e))
    return 0

  try:
    response = ses.send_email(
      Destination = {'ToAddresses': recipients},
      Message={
        'Body': {'Text': {'Charset': "UTF-8", 'Data': body}},
        'Subject': {'Charset': "UTF-8", 'Data': subject},
      },
      Source=sender)
  except:
    print(str(e))
    return 0
  return response['ResponseMetadata']['HTTPStatusCode']


if __name__ == '__main__':

  while True:

    try:
      sqs_client=boto3.client('sqs', region_name=Config.AWS_REGION_NAME)
    except ClientError as e:
      print(str(e))
      continue

    try:
      qURL_restore_complete=sqs_client.get_queue_url(QueueName=Config.AWS_SQS_RESTORE_COMPLETE)['QueueUrl']
    except ClientError as e:
      print(str(e))
      continue

    try:
      glacier = boto3.resource('glacier', region_name=Config.AWS_REGION_NAME)
    except ClientError as e:
      print(str(e))
      continue

    try:
      glacier_client=boto3.client('glacier', region_name=Config.AWS_REGION_NAME)
    except ClientError as e:
      print(str(e))
      continue

    try:
      s3 = boto3.resource('s3', region_name=Config.AWS_REGION_NAME)
    except ClientError as e:
      print(str(e))
      continue

    try:
      response_restore_complete=sqs_client.receive_message(QueueUrl=qURL_restore_complete,WaitTimeSeconds=Config.AWS_SCANNING_TIME,MaxNumberOfMessages=1)
    except ClientError as e:
      print(str(e))
      continue

    if len(response_restore_complete)>1:

      for m in response_restore_complete['Messages']:
        try:
          info_restore_complete=json.loads(json.loads(m['Body'])['Message'])
          restore_archive_id=info_restore_complete['ArchiveId']
          restore_job_id=info_restore_complete['JobId']
        except:
          print("need more information")
          continue

        # get the s3_key_result_file
        some_info=json.loads(info_restore_complete['JobDescription'])
        job_id=some_info['file_key'].split('/')[2]
        user_email=some_info['user_email']

        # get obj, upload to s3 results bucket, Key=s3_key_result_file
        try:
          job = glacier.Job('-', Config.AWS_GLACIER_VAULT, restore_job_id)
        except ClientError as e:
          print(str(e))
          continue

        try:
          output = job.get_output()
        except ClientError as e:
          print(str(e))
          continue

        try:
          results_bucket = s3.Bucket(Config.AWS_S3_RESULTS_BUCKET)
        except ClientError as e:
          print(str(e))
          continue

        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Bucket.upload_fileobj
        try:
          results_bucket.upload_fileobj(output['body'], some_info['file_key'])
          print("upload succeed!")

          # delete message
          sqs_client.delete_message(QueueUrl=qURL_restore_complete, ReceiptHandle=m['ReceiptHandle'])
          print('upload Message deleted!')
        except ClientError as e:
          print("upload failed!: "+str(e))
          continue

        # update database: delete 'results_file_archive_id'
        is_update=update_DB(job_id)

        if is_update==0:
          print('fail to update dynamoDB')
          continue

        # send email to the user: file has been restored
        email_body='You job '+str(job_id)+' has been restored! Please click '+Config.AWS_URL_PREFIX+'annotations/'+str(job_id)+' to see...'
        is_sent=send_email_ses(recipients=[user_email], sender=Config.MAIL_DEFAULT_SENDER, subject='Job Restored!', body=email_body)

        if is_sent==0:
          print('fail to send email')
          continue
        # delete archive
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.delete_archive
        try:
          delete_response=glacier_client.delete_archive(vaultName=Config.AWS_GLACIER_VAULT, archiveId=restore_archive_id)
          print('archive '+str(restore_archive_id)+" deleted!")
        except ClientError as e:
          print('fail to delete archive: '+str(e))
          continue