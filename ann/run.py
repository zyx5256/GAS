# Copyright (C) 2011-2018 Vas Vasiliadis                                                                              
# University of Chicago                                                                                               
##                                                                                                                    
__author__ = 'Yuxiao Zhu <zyx@uchicago.edu>'

import sys,json
import time
import driver
import os,subprocess,shutil,boto3
from flask import jsonify
from botocore.exceptions import ClientError
from flask import (abort, flash, redirect, render_template,
  request, session, url_for)
from boto3.dynamodb.conditions import Key, Attr
from config import Config
"""A rudimentary timer for coarse-grained profiling                                                                   
"""

# some global variable
input_bucket = Config.AWS_S3_INPUTS_BUCKET # gas-inputs
result_bucket = Config.AWS_S3_RESULTS_BUCKET # gas-results
region = Config.AWS_REGION_NAME # us-east-1
table_name = Config.AWS_DYNAMODB_ANNOTATIONS_TABLE # zyx_annotations
key_pre = Config.AWS_S3_KEY_PREFIX # zyx/
result_queue = Config.AWS_SQS_RESULT # zyx_job_results
archive_queue = Config.AWS_SQS_ARCHIVE # zyx_archive_results


class Timer(object):
    def __init__(self, verbose=True):
        self.verbose = verbose
    def __enter__(self):
        self.start = time.time()
        return self
    def __exit__(self, *args):
        self.end = time.time()
        self.secs = self.end - self.start
        if self.verbose:
            print("Total runtime: {0:.6f} seconds".format(self.secs))

if __name__ == '__main__':
    # Call the AnnTools pipeline
    if len(sys.argv) > 1:
        with Timer():
            driver.run(sys.argv[1], 'vcf')

            #_ /home/ubuntu/jobs/user/jobID/filename
            info=sys.argv[1].split("/")
            purename=info[6].split(".")
            purename=purename[0]

            #get user_info, user_info=[email, role]
            user_info=sys.argv[3].split('~')

            #upload results to S3
            try:
                s3 = boto3.resource('s3',region_name=region)
            except ClientError as e:
                print("error 500: fail to connect to boto3: "+ str(e))

            success=0
            log=sys.argv[1]+'.count.log'
            ann='/'+info[1]+'/'+info[2]+'/'+info[3]+'/'+info[4]+'/'+info[5]+'/'+purename+'.annot.vcf'
            prekey=key_pre+info[4]+'/'+info[5]+'/'+purename
            prekey_in=key_pre+info[4]+'/'+info[5]+'~'+purename
            logkey=prekey+'.vcf.count.log'
            annkey=prekey+'.annot.vcf'
            try:
                s3.meta.client.upload_file(Filename=ann, Bucket=result_bucket, Key=annkey)
                s3.meta.client.upload_file(Filename=log, Bucket=result_bucket, Key=logkey)
                success=1
            except ClientError as e:
                print("error 500,upload failed: "+str(e))
            except FileNotFoundError as ee:
                print("error 404, file not found: "+str(ee))
            except OSError as eee:
                print("error 404, path not found: "+ str(eee))

            # if uploaded successfully
            if success==1:

                #update DynamoDB
                try:
                    dynamoDB=boto3.resource('dynamodb', region_name=region)
                    ann_table=dynamoDB.Table(table_name)
                    try:
                        response_query=ann_table.query(KeyConditionExpression=Key('job_id').eq(info[5]))
                    except ClientError as e:
                        error(500, str(e))
                    response_query=response_query['Items'][0]


                    ann_table.update_item(
                      Key={'job_id': info[5]},
                      UpdateExpression="SET s3_results_bucket = :rb, s3_key_result_file = :rf, s3_key_log_file = :lf, complete_time = :ct, job_status = :ud",
                      ExpressionAttributeValues={                
                        ":rb": result_bucket,
                        ":rf": annkey,
                        ":lf": logkey,
                        ":ct": int(time.time()),
                        ':ud' : 'COMPLETED'},
                      ConditionExpression=Key('job_status').eq('RUNNING')
                   )
                except ClientError as e:
                    print("error 404: fail to update job status: "+str(e))

                #delete files on the instance
                try:
                    shutil.rmtree('/'+info[1]+'/'+info[2]+'/'+info[3]+'/'+info[4]+'/'+info[5])
                except shutil.Error as e:
                    print("error 500: fail to delete files: "+ str(e))

                try:
                    sns_client=boto3.client('sns', region_name=region)
                except ClientError as e:
                    print("error 500: fail to connect to boto3: "+ str(e))

                #publish job_complete_message
                myData={'job_id':info[5],'user_id':info[4], 
                'input_file_name': info[6], 's3_inputs_bucket': input_bucket, 
                's3_key_input_file':prekey_in+'.vcf','submit_time':int(sys.argv[2]),
                'complete_time':int(time.time()),'s3_results_bucket':result_bucket,
                's3_key_result_file':annkey,'s3_key_log_file':logkey,
                'job_status':'COMPLETED', 'user_email': user_info[0], 'user_role': user_info[1]}

                try:
                    sns_client.publish(Message=json.dumps({'default':json.dumps(myData)}), MessageStructure='json',TopicArn=Config.AWS_SNS_JOB_COMPLETE_TOPIC)
                except ClientError as e:
                    print( "error 500: fail to publish message: "+str(e))

                if user_info[1]=='free_user':
                    try:
                        sns_client.publish(Message=json.dumps({'default':json.dumps(myData)}), MessageStructure='json',TopicArn=Config.AWS_SNS_JOB_ARCHIVE_TOPIC)
                    except ClientError as e:
                        print( "error 500: fail to publish message: "+str(e))
    else:
        print("A valid .vcf file must be provided as input to this program.")
