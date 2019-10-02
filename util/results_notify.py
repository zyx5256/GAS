import boto3,json,subprocess
from config import Config

def send_email_ses(recipients=None,
  sender=None, subject=None, body=None):
  try:
    ses = boto3.client('ses', region_name=Config.AWS_REGION_NAME)
  except ClientError as e:
    print('error: '+str(e))
    return 0

  try:
    response = ses.send_email(
      Destination = {'ToAddresses': recipients},
      Message={
        'Body': {'Text': {'Charset': "UTF-8", 'Data': body}},
        'Subject': {'Charset': "UTF-8", 'Data': subject},
      },
      Source=sender)
  except ClientError as e:
    print('error: '+str(e))
    return 0
  return response['ResponseMetadata']['HTTPStatusCode']

if __name__ == '__main__':

  while True:
    # keep polling messages from 3 queues: job_complete, archive_job, and restore_job
    try:
      client=boto3.client('sqs', region_name=Config.AWS_REGION_NAME)
    except ClientError as e:
      print('error: '+str(e))
      continue

    try:
      qURL=client.get_queue_url(QueueName=Config.AWS_SQS_JOB_COMPLETE)['QueueUrl']
    except ClientError as e:
      print('error: '+str(e))
      continue

    try:
      response=client.receive_message(QueueUrl=qURL,WaitTimeSeconds=Config.AWS_SCANNING_TIME,MaxNumberOfMessages=1)
    except ClientError as e:
      print('error: '+str(e))
      continue

    # send email when job is completed
    if len(response)>1:
      for m in response['Messages']:
        info=json.loads(json.loads(m['Body'])['Message'])
        url_job_page=Config.AWS_URL_PREFIX+'annotations/'+info['job_id']

        # https://stackoverflow.com/questions/28527712/how-to-add-key-value-pair-in-the-json-object-already-declared/28527898
        info.update({'job_page': url_job_page})
        is_send=send_email_ses(recipients=[info['user_email']], sender=Config.MAIL_DEFAULT_SENDER, subject="JOB COMPLETED!", body=str(info))
        
        if is_send!=0:
          print("EMAIL SENT!")
        else:
          print('fail to send email')
          continue

        try:
          client.delete_message(QueueUrl=qURL, ReceiptHandle=m['ReceiptHandle'])
          print('Message deleted!')
        except ClientError as e:
          print('error: '+str(e))
          continue
