# Submission
1. File run_ann.sh is submitted in ann/, as I think it's of "e. Any other files necessary for your GAS to run";
2. Template 'please_upgrade.html' is added. When a free user trys to upload files larger than 150KB, it will redirect the user to this page;
3. Template 'free.html' is added. When a premium user click 'cancel my premium plan' in profile page, it will redirect user to this page and cancel user's premium role;
4. Template 'annotation_log.html' is added. To show log content when user wants to review log file;


# Code Review

## E7

### Workflow
1. Creating a job_archive topic and a delay Queue named job_archive_results with 10-minute delay of visibility after a message is received;
2. When a job is completed, check the user role. If it's free user, not only send a job_complete_message to the job_complete_queue, but also send a job_archive_message to the delay queue;
3. Then in results_archive.py, when it receives a job_archive_message, it also checks if the user is still free user and if more than 10 minutes has passed. If true, archive the job and delete the message, else do nothing.

### In detail
1. In run.py, when a job is completed, check the user role. If it's free user, send a job_archive_message to job_archive_results;
2. In results_archive.py, Loop:
3. Connect to boto3, keep polling messages from the job_archive_results. If connection or polling fails, go to step 8;
4. Check the messages polled from the queue, get job_id and query the DynamoDB:
	If the user_role is still free_user
	
	And

	it is more than 10 minutes passed
	:

	go to step 5; 
	Else if it's a premimum, delete the message; 
	Else if it's less than 10 minutes, go to step 8(Double Check);

5. Begin to archive the job. If succeed, got to step 6; Else go to the end;
6. Get the archiveID and update the DynamoDB; If succeed, got to step 7; Else go to step 8;
7. Delete the archive message from the Queue; If succeed, got to step 7; Else go to step 8;
8. End Loop;

### Reason
1. Using delay queue is more elegant and efficient. After a message was received, we don't need to get in to a while-loop for 10 minutes before processing it;
2. Using delay queue is more robust. If using looping, we may encounter an instance crash and lose the time we've count;
3. In results_archive.py, we also need to check if more than 10 minutes has passed after job completion. Just in case;
4. We also need to check the user role again before starting to archive, this is important, because a free user may upgrade to premium after the archive message is sent, but before the 10-minute free-download time period expired;
5. The message deletion is the last step. Only if all goes well can we delete the archive message, otherwise we need to re-read the message do it all over again;


## E9

### Workflow
1. Creating another two Queue named job_restore_requests and restore_complete_results;
2. When a free user upgrade to premium, send a message to this queue;
3. In result_restore.py, when it receives a job_restore_message, query the DynamoDB and restore all the jobs that belong to this user;
4. After a restore job is completed, Glacier will send a message to the restore_complete_results Queue;
5. In result_thaw.py, when it receives a restore_complete_message, it read the job body and upload to S3 bucket, then delete the archive in Glacier, then update the DynamoDB, and then send an email to user informing restore completion, and finally delete the message;

### In detail
1. In view.py, when a user successfully upgrade to premium user, it first update the user role in DynamoDB for all jobs that belong to this user;
2. Then, it publish a message to job_restore_requests with the user_id;
3. In results_restore.py, it keeps polling from job_restore_requests Queue;
4. When a restoration message received, results_restore.py query the DynamoDB and start restoration for all the jobs belonging to this user that has been archived, using archiveID stored in DynamoDB;
5. When restoration is completed, Glacier will send a message to the restore_complete_results Queue. Also I add s3_results_key as job description to be part of the message;
6. In results_thaw.py, it keeps polling from to the restore_complete_results Queue;
7. When a completion message received, it will read the job body using job_restore_id and upload the body to s3 bucket using s3_results_key in the message;
8. After all are done, results_thaw.py will delete the job archived in Glacier, and then delete the archiveID in DynamoDB;
9. Finally, it will delete the restore_complete_message and send an email to the user, informing him that his job has been restored;

### Reason
1. The most important part is, after a user upgrade to premium, we need to restore all the jobs that belong to this user. Thus we need to pass the user_id all the way along.
2. Adding s3_results_key as job description to be part of the restore_complete_message makes it easier to put the job back to where it belongs;
3. In results_thaw.py, the order matters a lot. We must first upload, then delete archive, then delete archiveID in DynamoDB and finally delete the message. Otherwise when an unexpected crash happens, we can restart the unfinished thaw using the restore_complete_message.
4. After restoration complete, I also send an email containing job_id and url to inform the user that the job has been restored and one can go to the page and download again; This is what a premimum user deserves;

## E13
![web instance auto sacling](https://github.com/mpcs-cc/cp-zyx5256/blob/master/images/web_instance.png?raw=true)
### Figure Analysis
1. Observed & Analysis:  
	O. At the beginning, the number of instance is 2.  
	A. We set the desired number as 2. Though the scale-in alarm was triggered( load for the page is low, thus the response time is high), it stayed at 2 because we set the minimum numer to be 2 also;

2. Observed & Analysis:  
	O. At the first stage, the number of instance(started as 2) began to increase, 1 by every 5 minutes. And When it reached 10, it stopped increasing;  
	A. As the attack began, after some latency, the scale-out alarm was triggered, and the scale-out policy was executed in every 5 minutes. Thus,
	the number of instances began to increase, one by every 5 minutes, as the policy execution has 5 minutes cool-down. But we set the maximum instance to be 10, thus it stopped increasing when it reached 10.

3. Observed & Analysis:  
	O. At the second stage, the number of instance(started as 10) began to decrease, 1 by every 5 minutes. And When it reached 2, it stopped decreasing;  
	A. At the second stage, after some latency, the scale-in alarm was triggered, and the scale-in policy was executed in every 5 minutes. Thus,
	the number of instances began to decrease, one by every 5 minutes, as the policy execution has 5 minutes cool-down. But we set the minimum instance to be 2, thus it stopped decreasing when it reached 2.

### Something else
1. Observed & Analysis:  
	O. The alarms has about 1-minute's latency.  
	A. The CloudWatch alarm is not acting optimally: if the alarm's time period is set to be 1 minute, then it will wait for at least 1 minute to judge if the alarm should be triggered or not, even if the data from the first 30 seconds is enough to make the judgement.

2. Observed & Analysis:  
	O. After the scale-out alarm triggered, each time when the scale-out policy actioned and one instance was added, the HTTPCode_Target_2XX_Count will drop.  
	A. When a new instance is created and in "running" status, it may not truly in service, as some of the initialization configuration maybe slow due to the network. But the ELB may not be aware of that and put this "rookie" instance in the field.

## E14
![ann instance auto sacling](https://github.com/mpcs-cc/cp-zyx5256/blob/master/images/ann_instance.png?raw=true)
1. Observed & Analysis:  
	O. At the beginning, the number of instance is 2.  
	A. We set the desired number as 2. Though the scale-in alarm was triggered( load for the page is low, thus the response time is high), it stayed at 2 because we set the minimum numer to be 2 also;

2. Observed & Analysis:  
	O. The number of the instance kept increased by one and then decreased by one.  
	A. I went to the CloudWatch page and check the alarms. I noticed that:  

       1. For both alarms(scale-in and scale-out), at the beginning of each time period, NumberOfMessageSent always started as 0, and then went up;
       2. Thus at the beginning of each time period, the scale-in alarm was triggered(because NumberOfMessageSent=0), and it killed one instance if there were more than 2 instances;
       3. Next, when NumberOfMessageSent was correct, the scale-out alarm was triggered, and it add one instance;
       4. loop...

	That's why the number of instance is always going up and down by one instance

# References Conclusion
1. Alarm descussion: https://aws.amazon.com/cloudwatch/faqs/
2. Cloudwatch INSUFFICIENT_DATA: https://forums.aws.amazon.com/thread.jspa?threadID=71596&tstart=50
3. CloudWatch alarm Insufficient data: https://medium.com/@martatatiana/insufficient-data-cloudwatch-alarm-based-on-custom-metric-filter-4e41c1f82050
4. Get object length: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Object.content_length
6. Compress .env file, Show all files in Finder: https://ianlunn.co.uk/articles/quickly-showhide-hidden-files-mac-os-x-mavericks/
5. Generate url: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.generate_presigned_urls
7. Debug, Socket error processing request: https://github.com/miguelgrinberg/Flask-SocketIO/issues/160
8. Debug, Socket error: https://stackoverflow.com/questions/51619559/socket-error-processing-request-with-flask-gunicorn-docker-and-azure
9. update item: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.update_item
10. Generate post: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.generate_presigned_post
11. add json pair: https://stackoverflow.com/questions/28527712/how-to-add-key-value-pair-in-the-json-object-already-declared/28527898
12. archive job: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.initiate_job
13. Delete archives: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.delete_archive
14. Upload, delete archives: https://aws.amazon.com/glacier/faqs/
15. using Stripe: https://stripe.com/docs/api
16. Convert string to JSON using Python: https://stackoverflow.com/questions/4528099/convert-string-to-json-using-python
17. Update DynamoDB, ConditionalExpression: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.UpdateExpressions.html
18. upload fileobj to S3: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Bucket.upload_fileobj
19. delete archive: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.delete_archive