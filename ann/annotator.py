#I'm using sublime baby!
import ast,datetime,boto3,uuid,subprocess,os,shutil,json
from flask import jsonify
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr
from config import Config

# some global variable
input_bucket = Config.AWS_S3_INPUTS_BUCKET # gas-inputs
result_bucket = Config.AWS_S3_RESULTS_BUCKET # gas-results
region = Config.AWS_REGION_NAME # us-east-1
table_name = Config.AWS_DYNAMODB_ANNOTATIONS_TABLE # zyx_annotations
key_pre = Config.AWS_S3_KEY_PREFIX # zyx/
request_queue = Config.AWS_SQS_REQUEST # zyx_job_requests

def anno(info):
  
  job_id=info['job_id']
  user_id=info['user_id']
  input_file_name=info['input_file_name']
  submit_time=info['submit_time']
  user_info=info['user_email']+'~'+info['user_role']

  cType=input_file_name.split(".")
  cType=cType[1]
  if cType=='vcf':
    cType="text/x-vcard"
  else:
    cType="invalid/not vcf"

  #if the job already exists
  if os.path.exists("/home/ubuntu/jobs/"+user_id+'/'+job_id):
    return job(user_id,job_id,cType)

  try:
    s3=boto3.resource('s3',region_name=region)
  except ClientError as e:
    return error(500, "fail to connect to s3: "+str(e))

  try:
    input_bucketObj=s3.Bucket(input_bucket)
  except ClientError as e:
    return error(500, "fail to connect to s3: "+str(e))

  # if the 'user/' folder exists, create folder 'user/jobID', else create one and then create 'user/jobID'
  if os.path.exists("/home/ubuntu/jobs/"+user_id):
    os.mkdir('jobs/'+user_id+'/'+job_id)
  else:
    os.mkdir('jobs/'+user_id)
    os.mkdir('jobs/'+user_id+'/'+job_id)
  filename='/home/ubuntu/jobs/'+user_id+'/'+job_id+'/'+input_file_name

  # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Bucket.download_file
  try:
    input_bucketObj.download_file(key_pre+user_id+'/'+job_id+'~'+input_file_name,filename)
  except ClientError as e:
    return error(404, "fail to download the file: "+str(e))

  os.chdir('/home/ubuntu/anntools')

  try:
    subprocess.Popen('python run.py '+filename+' '+str(submit_time)+' '+user_info, shell=True)
  except OSError as e:
    return error(500,"fail to execute the job: "+str(e))

  os.chdir('/home/ubuntu')

  #update job status
  is_update=update_item(job_id)

  if is_update==0:
    return job(user_id,job_id,cType)
  else:
    return error('fail to update dynamoDB')

#update item in dynamoDB
def update_item(job_id):

  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    return error(500, "fail to connect to dynamoDB: "+str(e))

  try:
    ann_table=dynamoDB.Table(table_name)
  except ClientError as e:
    return error(404, "Table not found: "+str(e))

  try:
    response=ann_table.query(KeyConditionExpression=Key('job_id').eq(job_id))
  except ClientError as e:
    return error(500, "fail to query the table: "+str(e))

  if len(response['Items'])==0:
    return error(404, "job not found")

  try:
    ann_table.update_item(
        Key={'job_id': job_id},
        UpdateExpression="SET job_status = :ud",
        ExpressionAttributeValues={':ud' : 'RUNNING'},
      ConditionExpression=Key('job_status').eq('PENDING')
    )
  except ClientError as e:
    return error(500,"fail to update job status in the target table: "+str(e))

  return 0

def job(user_id,job_id, cType):

  files=[]
  
  try:
    files=os.listdir('/home/ubuntu/jobs/'+user_id+'/'+job_id)
  except OSError as e:
    return error(404, "user "+user_id+" doesn't exist: "+str(e))

  if len(files)==0:
    return error(404, "Job not downloaded")

  logfile=None
  flag=0

  for f in files:
    if f.endswith('.log'):
      logfile=f
      flag=1

  if flag==0:
    return str({"code":200,"data":{"job_id":job_id,"Content-Type":cType,"job_status":"initializing or it's done"}})

  if len(files)==3:
    log=open('/home/ubuntu/jobs/'+user_id+'/'+job_id+'/'+logfile,"r").read()
    return str({"code":200,"data":{"job_id":job_id,"Content-Type":cType,"job_status":"complete","log":log}})
  else:
    return str({"code":200,"data":{"job_id":job_id,"Content-Type":cType,"job_status":"running"}})

def error(e, string):
  code=e
  status='error'
  message=string
  return str({'code':code,'status':status,'message':message})

if __name__ == '__main__':

  while True:

    try:
      client=boto3.client('sqs', region_name=region)
    except ClientError as e:
      print(error(500, 'fail to connect to boto3: '+ str(e)))
      continue

    try:
      qURL=client.get_queue_url(QueueName=request_queue)['QueueUrl']
    except ClientError as e:
      print(error(500, 'fail to get queue url: '+ str(e)))
      continue

    try:
      response=client.receive_message(QueueUrl=qURL,WaitTimeSeconds=15,MaxNumberOfMessages=1)
    except ClientError as e:
      print(error(500, 'fail to pull message: '+ str(e)))
      continue

    if len(response)==1:
      continue;

    else:
      for m in response['Messages']:

        # get request message
        info=json.loads(json.loads(m['Body'])['Message'])

        try:
          dynamoDB=boto3.resource('dynamodb', region_name=region)
        except ClientError as e:
          print(error(500, 'fail to connect to boto3: '+ str(e)))
          continue

        try:
          ann_table=dynamoDB.Table(table_name)
        except ClientError as e:
          print(error(500, 'fail to connect to the table: '+ str(e)))
          continue

        try:
          response=ann_table.query(KeyConditionExpression=Key('job_id').eq(info['job_id']))
        except ClientError as e:
          print(error(500, 'fail to query from table: '+ str(e)))
          continue

        status=0

        # get job_status if there're jobs to do
        if len(response['Items'])>0:
          status=response['Items'][0]['job_status']
        else:
          print('404, Job not found')

          # delete this bad message
          try:
            client.delete_message(QueueUrl=qURL, ReceiptHandle=m['ReceiptHandle'])
            print('Message deleted. Probably bad massage')
          except ClientError as e:
            error(500, 'fail to delete message')

        # if job is pending
        if status=='PENDING':
          anno(info)

        # if job is done, delete request message
        elif status=='COMPLETED':

          try:
            client.delete_message(QueueUrl=qURL, ReceiptHandle=m['ReceiptHandle'])
            print('Message deleted: '+info['job_id'])
          except ClientError as e:
            error(500, 'fail to delete message')
        
