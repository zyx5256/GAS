# views.py
#
# Copyright (C) 2011-2018 Vas Vasiliadis
# University of Chicago
#
# Application logic for the GAS
#
##
__author__ = 'Yuxiao Zhu <zyx@uchicago.edu>' # it's me now !

import uuid
import time
import json
import stripe
from datetime import datetime

import boto3,botocore
from botocore.client import Config
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from flask import (abort, flash, redirect, render_template, 
  request, session, url_for, jsonify)

from gas import app, db
from decorators import authenticated, is_premium
from auth import get_profile, update_profile


"""Start annotation request
Create the required AWS S3 policy document and render a form for
uploading an annotation input file using the policy document
"""

# some global variable
input_bucket = app.config['AWS_S3_INPUTS_BUCKET'] # gas-inputs
result_bucket = app.config['AWS_S3_RESULTS_BUCKET'] # gas-results
region = app.config['AWS_REGION_NAME'] # us-east-1
table_name = app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'] # zyx_annotations
key_pre = app.config['AWS_S3_KEY_PREFIX'] # zyx/

#### attack this page
@app.route('/attack', methods=['GET'])
def attack_me():
  return "come on, show me what you got!"

# cancel premium
@app.route('/free', methods=['GET'])
@authenticated
def free():
  update_profile(identity_id=session['primary_identity'], role='free_user')

  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    return error(500, "fail to connect to dynamoDB: "+str(e))
  try:
    ann_table=dynamoDB.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])
  except ClientError as e:
    return error(404, "Table not found: "+str(e))

  try:
    response_from_table=ann_table.query(IndexName='user_id_index', KeyConditionExpression=Key('user_id').eq(session['primary_identity']))
  except ClientError as e:
    error(500, str(e))

  for item in response_from_table['Items']:

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.update_item
    try:
      ann_table.update_item(
          Key={'job_id': item['job_id']},
          UpdateExpression="SET user_role = :ud",
          ExpressionAttributeValues={':ud' : 'free_user'},
        ConditionExpression=Key('user_role').eq('premium_user')
      )
    except ClientError as e:
      return error(500,"fail to update job status in the target table: "+str(e))

  return render_template('free.html')


#upload files to S3
@app.route('/annotate', methods=['GET'])
@authenticated
def annotate():

  # Create a session client to the S3 service
  try:
    s3 = boto3.client('s3', 
    region_name=region,
    config=Config(signature_version='s3v4'))
  except ClientError as e:
    error(500,str(e))

  user_id = session['primary_identity']

  # Generate unique ID to be used as S3 key (name)
  key_name = key_pre + session['primary_identity'] + '/' + str(uuid.uuid4()) + '~${filename}'

  # Create the redirect URL
  redirect_url = str(request.url) + '/job'

  # Define policy fields/conditions
  encryption = app.config['AWS_S3_ENCRYPTION']
  acl = app.config['AWS_S3_ACL']
  fields = {
    "success_action_redirect": redirect_url,
    "x-amz-server-side-encryption": encryption,
    "acl": acl
  }
  conditions = [
    ["starts-with", "$success_action_redirect", redirect_url],
    {"x-amz-server-side-encryption": encryption},
    {"acl": acl}
  ]

  # Generate the presigned POST call
  # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.generate_presigned_post
  try:
    presigned_post = s3.generate_presigned_post(
      Bucket=input_bucket, 
      Key=key_name,
      Fields=fields,
      Conditions=conditions,
      ExpiresIn=app.config['AWS_SIGNED_REQUEST_EXPIRATION'])
  except ClientError as e:
    return jsonify({'code': 500, 'status': 'error',
      'message': f'Failed to generate presigned post: {e}'})

  # Render the upload form which will parse/submit the presigned POST
  return render_template('annotate.html', s3_post=presigned_post)


"""Fires off an annotation job
Accepts the S3 redirect GET request, parses it to extract 
required info, saves a job item to the database, and then
publishes a notification for the annotator service.
"""

#redirection after uploading:
@app.route('/annotate/job', methods=['GET'])
@authenticated
def create_annotation_job_request():

  # Get bucket name, key, and job ID from the S3 redirect URL
  keys = str(request.args.get('key'))
  if keys is None:
    return error(404, "parameters not found")
  
  # Extract the job_id and fname from the S3 key                         
  jID=keys.split('/')[2].split("~")
  job_id=jID[0]
  fname=jID[1]
  user_id=session['primary_identity']
  request_topic=app.config['AWS_SNS_JOB_REQUEST_TOPIC']

  # if not .vcf file                                  
  cType=fname.split(".")
  cType=cType[1]
  if cType=='vcf':
    cType="text/x-vcard"
  else:
    cType="invalid/not vcf"
    return render_template('annotate_confirm.html', job_id=None)
    
  # Persist job to database
  myData={'job_id':job_id,'user_id': user_id, 
  'input_file_name': fname, 's3_inputs_bucket': input_bucket, 
  's3_key_input_file': keys,'submit_time':int(time.time()),
  'job_status':'PENDING', 'user_role': get_profile(identity_id=session['primary_identity']).role}

  # check the length of the job
  try:
    s3_resource=boto3.resource('s3', region_name=app.config['AWS_REGION_NAME'])
  except ClientError as e:
    error(500, str(e))

  try:
    obj_check = s3_resource.Object(input_bucket, keys)
  except ClientError as e:
    error(500, str(e))

  # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Object.content_length
  length_check=obj_check.content_length

  if length_check>app.config['AWS_JOB_LIMIT'] and get_profile(identity_id=session['primary_identity']).role=='free_user':
    return render_template('please_upgrade.html')

  # connect to database and retrieve data
  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    error(500, str(e))

  try:
    ann_table=dynamoDB.Table(table_name)
  except ClientError as e:
    error(500, str(e))

  try:
    myItems=ann_table.query(IndexName='user_id_index',KeyConditionExpression=Key('user_id').eq(user_id))
  except ClientError as e:
    error(500, str(e))

  myItems=myItems['Items']

  # update dynamoDB
  if myItems==None:
  
    try:
      ann_table.put_item(Item=myData)
    except ClientError as e:
      error(500, str(e))
  
  else:
    myItem=0
    for i in myItems:
      if len(i)>0:
        if i['job_id']==job_id:
          myItem=i

    # if the job id is unique
    if myItem==0:
      try:
        ann_table.put_item(Item=myData)
      except botocore.exceptions.ClientError as e:
        return error(500,"fail to put items in the target table: "+str(e))

    # already a job with the same id in the database
    else:
      return error(500,"job id already exist")

  # Send message to request queue
  try:
    client=boto3.client('sns', region_name=region)
  except botocore.exceptions.ClientError as e:
    return error(500, "fail to connect to boto3 server: "+str(e))

  # update myData, add some inofmation of users
  user_profile=get_profile(identity_id=user_id)
  myData.update({'user_name': str(user_profile.name)})
  myData.update({'user_email': str(user_profile.email)})
  myData.update({'user_role': str(user_profile.role)})

  #publish message
  try:
    client.publish(Message=json.dumps({'default':json.dumps(myData)}), MessageStructure='json',TopicArn=request_topic)
  except botocore.exceptions.ClientError as e:
    return error(500, "fail to publish message: "+str(e))
  return render_template('annotate_confirm.html', job_id=job_id)


"""List all annotations for the user
"""
@app.route('/annotations', methods=['GET'])
@authenticated
def annotations_list():
  # Get list of annotations to display
  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    error(500, str(e))

  try:
    ann_table=dynamoDB.Table(table_name)
  except ClientError as e:
    error(500, str(e))

  try:
    response=ann_table.query(IndexName='user_id_index', KeyConditionExpression=Key('user_id').eq(session['primary_identity']))
  except ClientError as e:
    error(500, str(e))

  for job in response['Items']:
    job.update({'submit_time': time.strftime("%Y-%m-%d %H:%M",time.localtime(job['submit_time']))})
  return render_template('annotations.html', annotations=response)


"""Display details of a specific annotation job
"""
@app.route('/annotations/<id>', methods=['GET'])
@authenticated
def annotation_details(id):

  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    error(500, str(e))

  try:
    ann_table=dynamoDB.Table(table_name)
  except ClientError as e:
    error(500, str(e))
  
  try:
    response=ann_table.query(KeyConditionExpression=Key('job_id').eq(id))
  except ClientError as e:
    error(500, str(e))

  info=response['Items'][0]
  user_role=get_profile(identity_id=session['primary_identity']).role

  # check if the current user owns the job
  if info['user_id']!=session['primary_identity']:
    return error(403, "Access denied")

  # check if the user is authorized to download
  download_indicator=1
  restoring_indicator=0
  if int(time.time())-info['submit_time']>app.config['FREE_USER_DATA_RETENTION'] and user_role=='free_user':
    download_indicator=0

  if ('results_file_archive_id' in info) and user_role == 'premium_user':
    restoring_indicator=1

  # transform time format
  info['submit_time']=time.strftime("%Y-%m-%d %H:%M",time.localtime(info['submit_time']))

  # if job has't complete yet
  if info['job_status']!='COMPLETED':
    return render_template('annotation.html', information=info)

  # if job is completed
  info['complete_time']=time.strftime("%Y-%m-%d %H:%M",time.localtime(info['complete_time']))
  result_file=info['s3_key_result_file']

  #generate download url if download is allowed
  download_url=""
  if download_indicator==1:
    s3_client = boto3.client('s3', region_name=region)
    
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.generate_presigned_url
    try:
      download_url = s3_client.generate_presigned_url('get_object',Params={'Bucket': result_bucket,'Key': result_file},ExpiresIn=app.config['AWS_SIGNED_REQUEST_EXPIRATION'])
    except ClientError as e:
      logging.error(e)


  #update information
  info['s3_key_result_file']=info['input_file_name'].split('.')[0]+'.annot.vcf'
  info['s3_key_log_file']=info['input_file_name']+'.count.log'
  info.update({'download_url': download_url})
  info.update({'upgrade_url':app.config['AWS_URL_PREFIX']+'subscribe'})
  info.update({'download': download_indicator})
  info.update({'restoring': restoring_indicator})
  return render_template('annotation.html', information=info)


"""Display the log file for an annotation job
"""
@app.route('/annotations/<id>/log', methods=['GET'])
@authenticated
def annotation_log(id):

  #display everything in <id>
  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    error(500, str(e))

  try:
    ann_table=dynamoDB.Table(table_name)
  except ClientError as e:
    error(500, str(e))

  try:
    response=ann_table.query(KeyConditionExpression=Key('job_id').eq(id))
  except ClientError as e:
    error(500, str(e))

  info=response['Items'][0]

  # check if the current user owns the job
  if info['user_id']!=session['primary_identity']:
    return error(403, "Access denied")

  if info['job_status']=='COMPLETED':
    info['complete_time']=time.strftime("%Y-%m-%d %H:%M",time.localtime(info['complete_time']))
  result_file=info['s3_key_result_file']

  #generate downlaod url  
  try:
    s3_client = boto3.client('s3', region_name=region)
  except ClientError as e:
    error(500, str(e))

  # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.generate_presigned_url
  try:
    pre_url = s3_client.generate_presigned_url('get_object',Params={'Bucket': result_bucket,'Key': result_file},ExpiresIn=app.config['AWS_SIGNED_REQUEST_EXPIRATION'])
  except ClientError as e:
    logging.error(e)

  #get log info
  try:
    s3_resource=boto3.resource('s3',region_name=region)
  except ClientError as e:
    error(500, str(e))

  try:
    obj = s3_resource.Object(result_bucket, info['s3_key_log_file'])
  except ClientError as e:
    error(500, str(e))

  log=obj.get()['Body'].read().decode('utf-8').replace('\n','<br>')
  
  #update information                                                                                                                                                          
  info['s3_key_result_file']=info['input_file_name'].split('.')[0]+'.annot.vcf'
  info['s3_key_log_file']=info['input_file_name']+'.count.log'
  info.update({'url':pre_url})
  info.update({'log':log})
  return render_template('annotation_log.html', information=info)

"""Subscription management handler
"""
import stripe

@app.route('/subscribe', methods=['GET'])
@authenticated
def subscribe_get():
  return render_template('subscribe.html')

@app.route('/subscribe', methods=['POST'])
@authenticated
def subscribe():

  # get stripe token
  # https://stripe.com/docs/api
  if request.get_data() is None:
    return error(404, "parameters not found!!!")
  info=request.get_data()
  info=info.decode('utf-8')
  stripe_token=info.split('=')[1]

  # create new customer
  try:
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
    response=stripe.Customer.create(
      description=key_pre,
      source=stripe_token # obtained with Stripe.js
    )
  except:
    return error(500, 'fail to upgrade...')

  # update user role
  update_profile(identity_id=session['primary_identity'], role='premium_user')

  try:
    dynamoDB=boto3.resource('dynamodb', region_name=region)
  except ClientError as e:
    return error(500, "fail to connect to dynamoDB: "+str(e))
  try:
    ann_table=dynamoDB.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])
  except ClientError as e:
    return error(404, "Table not found: "+str(e))

  try:
    response_from_table=ann_table.query(IndexName='user_id_index', KeyConditionExpression=Key('user_id').eq(session['primary_identity']))
  except ClientError as e:
    error(500, str(e))

  for item in response_from_table['Items']:
    try:
      ann_table.update_item(
          Key={'job_id': item['job_id']},
          UpdateExpression="SET user_role = :ud",
          ExpressionAttributeValues={':ud' : 'premium_user'},
        ConditionExpression=Key('user_role').eq('free_user')
      )
    except ClientError as e:
      return error(500,"fail to update job status in the target table: "+str(e))

  user_email=get_profile(identity_id=session['primary_identity']).email
  
  # send job_restore_request
  try:
    client=boto3.client('sns', region_name=region)
  except ClientError as e:
    error(500, str(e))

  user_info={'user_id': session['primary_identity'], 'user_email': user_email}
  
  try:
    client.publish(Message=json.dumps({'default':json.dumps(user_info)}), MessageStructure='json',TopicArn=app.config['AWS_SNS_JOB_RESTORE_TOPIC'])
  except ClientError as e:
    error(500, str(e))

  return render_template('subscribe_confirm.html', stripe_id=response['id'])

#general error handler
def error(code, message):
  return render_template('error.html',
    title=str(code), alert_level='Oops...',
    message=message)

"""DO NOT CHANGE CODE BELOW THIS LINE
*******************************************************************************
"""

"""Home page
"""
@app.route('/', methods=['GET'])
def home():
  return render_template('home.html')

"""Login page; send user to Globus Auth
"""
@app.route('/login', methods=['GET'])
def login():
  app.logger.info('Login attempted from IP {0}'.format(request.remote_addr))
  # If user requested a specific page, save it to session for redirect after authentication
  if (request.args.get('next')):
    session['next'] = request.args.get('next')
  return redirect(url_for('authcallback'))

"""404 error handler
"""
@app.errorhandler(404)
def page_not_found(e):
  return render_template('error.html', 
    title='Page not found', alert_level='warning',
    message="The page you tried to reach does not exist. Please check the URL and try again."), 404

"""403 error handler
"""
@app.errorhandler(403)
def forbidden(e):
  return render_template('error.html',
    title='Not authorized', alert_level='danger',
    message="You are not authorized to access this page. If you think you deserve to be granted access, please contact the supreme leader of the mutating genome revolutionary party."), 403

"""405 error handler
"""
@app.errorhandler(405)
def not_allowed(e):
  return render_template('error.html',
    title='Not allowed', alert_level='warning',
    message="You attempted an operation that's not allowed; get your act together, hacker!"), 405

"""500 error handler
"""
@app.errorhandler(500)
def internal_error(error):
  return render_template('error.html',
    title='Server error', alert_level='danger',
    message="The server encountered an error and could not process your request."), 500

### EOF
