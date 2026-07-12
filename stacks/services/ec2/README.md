This stack creates an ec2 instance and pull the given docker image to run it as a service. There is no scalability.
A CloudFront resource is used in front to handle https. To avoid caching responses (which is billed by aws) add a **Cache-Control: no-store** header in the webapp responses.


You can find the logs of the UserData script located in **/var/log/cloud-init-output.log**. The UserData script itself can be found in **/var/lib/cloud/instances/<instance-id>/user-data.txt**. You will need **sudo cat** to read it though.