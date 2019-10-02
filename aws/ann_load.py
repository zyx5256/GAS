import time
import json
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

if __name__ == '__main__':

  # count the fake messages sent
  message_num=0
  
  while True:
    
    try:
      sns_client = boto3.client('sns', region_name='us-east-1')
    except ClientError as e:
      print('500, fail to connect to boto3')
      continue

    # send fake messages
    try:
      sns_response = sns_client.publish(
          TopicArn='arn:aws:sns:us-east-1:127134666975:zyx_job_requests',    
          Message=json.dumps({
                            "job_id": '1',
                            "user_id": '2',
                            "input_file_name": '3',
                            "s3_inputs_bucket": 'gas-inputs',
                            "s3_key_input_file": '4',
                            "s3_results_bucket": "gas-results",
                            "submit_time": int(time.time()),
                            "job_status": "5",
                            "user_email": '5256haha@gmail.com',
                            "user_role": 'premium_user'
                          })
        )

      # when and how many messages sent
      sleep=2
      time.sleep(sleep)
      message_num+=1
      minute=int(message_num*sleep/60)
      second=message_num*sleep-minute*60
      print('the '+str(message_num)+'th message sent at '+str(minute)+' min '+str(second)+' sec')

    except ClientError as e:
      print('500, fail to sent fake message')
