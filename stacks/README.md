# AWS Cloudformation stacks

This repository contains some examples of AWS cloudformation stacks that can be used in nested stacks or modified.

## 1) Copy the stacks to s3

You will first want to create an s3 bucket to store these stacks.

```bash
export MY_STACK_BUCKET=my-stack-bucket
aws s3api create-bucket --bucket ${MY_STACK_BUCKET}
```

Then clone the repository:

```bash
git clone https://github.com/BFavier/bfavier-tools.git
```

Finally copy the stacks to the bucket (remember to change the name of the bucket here below - also remove the **--dryrun** once you are confident about the changelog)

```bash
aws s3 sync ./bfavier-tools/stacks/ s3://${MY_STACK_BUCKET} --delete --dryrun
```

## 2) Use the stacks in nested stack templates

You can then deploy them directly

```bash
aws cloudformation create-stack --capabilities CAPABILITY_NAMED_IAM --template-url s3://my-stack-bucket/network/stack-vpc.yaml --stack-name private-network --parameters ParameterKey=VpcName,ParameterValue=PrivateNetwork ParameterKey=PublicVpc,ParameterValue=false
```

Or you can then reference them in your local stacks

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: My test stack

Parameters:
  StacksBucketName:
    Type: String
    Description: Name of the bucket containing the stacks
  DomainName:
    Type: String
    Description: Domain name for the hosted zone and certificate

Resources:
  Network:
    Type: AWS::CloudFormation::Stack
    Properties:
      TemplateURL: !Sub https://${StacksBucketName}.s3.amazonaws.com/network/stack-vpc.yaml
  HostedZone:
    Type: AWS::CloudFormation::Stack
    Properties:
      TemplateURL: !Sub https://${StacksBucketName}.s3.amazonaws.com/network/stack-hosted-zone.yaml
      Parameters:
        DomainName: !Ref DomainName
  EC2Service:
    Type: AWS::CloudFormation::Stack
    Properties:
      TemplateURL: !Sub https://${StacksBucketName}.s3.amazonaws.com/services/ec2/stack-ec2-webapp.yaml
      Parameters:
          DockerImage: nginxdemos/hello
          VpcId: !GetAtt [Network, Outputs.VpcId]
          SubnetId: !Select ['0', !Split [', ', !GetAtt [Network, Outputs.PublicSubnetIds]]]
          HostedZoneId: !GetAtt [HostedZone, Outputs.HostedZoneId]
          ServiceUrl: !Sub www.${DomainName}
          CertificateArn: !GetAtt [HostedZone, Outputs.CertificateArn]

Outputs:
  HostedZoneId:
    Value: !GetAtt
      - HostedZone
      - Outputs.HostedZoneId
    Export:
      Name: HostedZoneId
```

Which you can deploy with

```bash
aws cloudformation create-stack --capabilities CAPABILITY_NAMED_IAM --template-body file://./local-stack.yaml --parameters ParameterKey=StacksBucketName,ParameterValue=${MY_STACK_BUCKET} --parameters ParameterKey=DomainName,ParameterValue=${MY_DOMAIN_NAME} --stack-name test-stack --on-failure DO_NOTHING
```

## 3) Identify resources that are not created by a cloudformation stack

To keep your system clean, you can detect AWS resources that do not issue from a cloudformation stack by using the following command:

```python
import boto3

client = boto3.client("resourcegroupstaggingapi")

paginator = client.get_paginator("get_resources")

orphans = []

for page in paginator.paginate(ResourcesPerPage=50):
    for res in page["ResourceTagMappingList"]:
        tags = {t["Key"]: t["Value"] for t in res.get("Tags", [])}
        if "aws:cloudformation:stack-id" not in tags:
            orphans.append(res["ResourceARN"])

for arn in orphans:
    print(arn)
```
